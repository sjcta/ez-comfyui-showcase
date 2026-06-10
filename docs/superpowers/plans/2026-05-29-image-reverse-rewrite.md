# Image Reverse Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current accumulated image reverse-prompt system with three clean, independent modes: standard, expert, and expert-team.

**Architecture:** Build a new `modules/image_reverse/` package with separate prompt contracts, schemas, parsers, pipelines, and compatibility adapters. Keep the public API response compatible during the rewrite (`prompt`, `structured_prompt`, `structured_prompt_json`, `negative_prompt`, `expert_interrogate`) while replacing the internal `visual_spec` and expert-team protocol completely.

**Tech Stack:** Python 3.13, existing FastAPI app entrypoint in `app.py`, existing shared multimodal LLM client in `modules/llm_client.py`, `unittest`, existing frontend consumers in `static/js/modules/generate.js` and `static/js/modules/ui.js`.

---

## File Structure

- Create `modules/image_reverse/__init__.py`
  - Public exports for the new reverse-prompt package.
- Create `modules/image_reverse/contracts.py`
  - Dataclasses and constants for `standard`, `expert`, and `expert_team` modes.
  - Canonical output shape and compatibility output shape.
- Create `modules/image_reverse/prompts.py`
  - Three independent multimodal prompt builders.
  - No legacy template fragments.
- Create `modules/image_reverse/schemas.py`
  - Schema dictionaries and validation helpers for the three mode outputs.
- Create `modules/image_reverse/parser.py`
  - JSON extraction, validation, normalization, and compatibility adapter.
- Create `modules/image_reverse/pipelines.py`
  - `run_standard_reverse`, `run_expert_reverse`, `run_expert_team_reverse`.
- Create `modules/image_reverse/legacy_adapter.py`
  - Thin wrappers that preserve old function names while calling the new pipelines.
- Create `tests/test_image_reverse_contracts.py`
  - Contract and prompt tests.
- Create `tests/test_image_reverse_pipelines.py`
  - Pipeline tests with fake multimodal responses.
- Modify `modules/prompt_interrogator.py`
  - Reduce to image preparation, ComfyUI fallback, and exports that delegate to `legacy_adapter.py`.
- Modify `app.py`
  - Route standard/expert/expert-team calls to the new package through existing names or direct imports.
- Modify `tests/test_prompt_interrogator.py`
  - Remove overfitted transitional expert-team tests.
  - Keep only compatibility, ComfyUI fallback, image preparation, and old extraction tests.
- Modify `tests/test_prompt_optimizer.py`
  - Update API tests to assert mode selection and compatibility response, not old internal JSON shapes.

---

### Task 1: Define Canonical Contracts

**Files:**
- Create: `modules/image_reverse/contracts.py`
- Create: `modules/image_reverse/__init__.py`
- Test: `tests/test_image_reverse_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Add `tests/test_image_reverse_contracts.py`:

```python
import unittest

from modules.image_reverse.contracts import (
    REVERSE_MODE_EXPERT,
    REVERSE_MODE_EXPERT_TEAM,
    REVERSE_MODE_STANDARD,
    ReverseOutput,
    mode_token_budget,
)


class ImageReverseContractTests(unittest.TestCase):
    def test_modes_have_distinct_token_budgets(self):
        self.assertLess(mode_token_budget(REVERSE_MODE_STANDARD), mode_token_budget(REVERSE_MODE_EXPERT))
        self.assertLess(mode_token_budget(REVERSE_MODE_EXPERT), mode_token_budget(REVERSE_MODE_EXPERT_TEAM))

    def test_reverse_output_exports_compatible_payload(self):
        output = ReverseOutput(
            mode=REVERSE_MODE_EXPERT,
            provider="test-vision",
            prompt="主体位于画面中心，红色上衣，灰色背景",
            negative_prompt=["文字", "水印"],
            visual_spec={"画面描述": {"基本概述": "红色主题人物图"}},
            raw={"visual_spec": {"summary": "raw"}},
            expert_interrogate={"enabled": True, "mode": "expert", "experts": []},
        )

        payload = output.to_api_payload()

        self.assertEqual(payload["prompt"], "主体位于画面中心，红色上衣，灰色背景")
        self.assertEqual(payload["promptgen"], payload["prompt"])
        self.assertEqual(payload["prompt_zh"], payload["prompt"])
        self.assertEqual(payload["negative_prompt"], "文字, 水印")
        self.assertIn('"画面描述"', payload["structured_prompt_json"])
        self.assertTrue(payload["expert_interrogate"]["enabled"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_reverse_contracts
```

Expected: `ModuleNotFoundError: No module named 'modules.image_reverse'`.

- [ ] **Step 3: Implement contracts**

Create `modules/image_reverse/__init__.py`:

```python
"""Image reverse-prompt package."""
```

Create `modules/image_reverse/contracts.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


REVERSE_MODE_STANDARD = "standard"
REVERSE_MODE_EXPERT = "expert"
REVERSE_MODE_EXPERT_TEAM = "expert_team"

MODE_TOKEN_BUDGETS = {
    REVERSE_MODE_STANDARD: 1536,
    REVERSE_MODE_EXPERT: 4096,
    REVERSE_MODE_EXPERT_TEAM: 6144,
}


def mode_token_budget(mode: str) -> int:
    return MODE_TOKEN_BUDGETS.get(mode, MODE_TOKEN_BUDGETS[REVERSE_MODE_STANDARD])


@dataclass
class ReverseOutput:
    mode: str
    provider: str
    prompt: str
    negative_prompt: list[str] = field(default_factory=list)
    visual_spec: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    expert_interrogate: dict[str, Any] | None = None
    elapsed_seconds: float | None = None

    def to_api_payload(self) -> dict[str, Any]:
        negative_text = ", ".join(item for item in self.negative_prompt if item)
        payload = {
            "ok": True,
            "provider": self.provider,
            "prompt_id": "",
            "prompt": self.prompt,
            "promptgen": self.prompt,
            "prompt_zh": self.prompt,
            "wd14_tags": "",
            "structured_raw": json.dumps(self.raw, ensure_ascii=False),
            "structured_prompt": self.visual_spec,
            "structured_prompt_json": json.dumps(self.visual_spec, ensure_ascii=False, indent=2),
        }
        if negative_text:
            payload["negative_prompt"] = negative_text
        if self.expert_interrogate is not None:
            payload["expert_interrogate"] = self.expert_interrogate
        if self.elapsed_seconds is not None:
            payload["interrogate_elapsed_seconds"] = self.elapsed_seconds
        return payload
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_reverse_contracts
```

Expected: `OK`.

---

### Task 2: Build Three Prompt Contracts

**Files:**
- Create: `modules/image_reverse/prompts.py`
- Modify: `tests/test_image_reverse_contracts.py`

- [ ] **Step 1: Write failing prompt tests**

Append to `tests/test_image_reverse_contracts.py`:

```python
from modules.image_reverse.prompts import (
    build_expert_prompt,
    build_expert_team_global_prompt,
    build_expert_team_review_prompt,
    build_expert_team_subject_prompt,
    build_standard_prompt,
)


class ImageReversePromptTests(unittest.TestCase):
    def test_standard_prompt_is_compact_and_not_expert_team(self):
        prompt = build_standard_prompt()
        self.assertIn("标准反推", prompt)
        self.assertIn("visible_facts", prompt)
        self.assertIn("final_prompt", prompt)
        self.assertNotIn("专家团", prompt)
        self.assertLess(len(prompt), 3500)

    def test_expert_prompt_requires_structured_subject_detail(self):
        prompt = build_expert_prompt()
        self.assertIn("专家反推", prompt)
        self.assertIn("subject_type", prompt)
        self.assertIn("body_chain", prompt)
        self.assertIn("left_hand_chain", prompt)
        self.assertIn("right_hand_chain", prompt)
        self.assertIn("camera_angle", prompt)
        self.assertIn("light_incidence", prompt)
        self.assertLess(len(prompt), 6500)

    def test_expert_team_prompts_are_separate_stages(self):
        global_prompt = build_expert_team_global_prompt()
        subject_prompt = build_expert_team_subject_prompt({"primary_subject": "人物", "subject_type": "person"})
        review_prompt = build_expert_team_review_prompt({"visual_spec": {"subject": {}}})

        self.assertIn("第1轮", global_prompt)
        self.assertIn("第2轮", subject_prompt)
        self.assertIn("复核", review_prompt)
        self.assertIn("subject_contract", subject_prompt)
        self.assertIn("reject_if", review_prompt)
        self.assertLess(len(global_prompt), 3200)
        self.assertLess(len(subject_prompt), 5200)
        self.assertLess(len(review_prompt), 4200)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_reverse_contracts
```

Expected: import failure for `modules.image_reverse.prompts`.

- [ ] **Step 3: Implement prompt builders**

Create `modules/image_reverse/prompts.py`:

```python
from __future__ import annotations

import json
from typing import Any


VISIBLE_ONLY_RULE = (
    "只写图片中可见事实；不可见、不确定、推测内容必须省略。"
    "所有方向必须带参照系，例如画面左侧、镜头近端、人物身体左侧、背景墙面。"
)

TEXT_RULE = (
    "图中有文字、水印、Logo、UI时才写 visible_text；没有文字时不要在正向字段提文字，只把文字、水印、Logo、UI字样放入 negative_prompt。"
)

NSFW_RULE = (
    "暴露内容统一写 exposure_details，只描述可见身体部位、衣物遮挡边界、接触动作和液体湿润反光；不输出安全标签。"
)

PERSON_CONTRACT = (
    "subject_contract: 当 subject_type=person 时，subject 必须是对象，固定字段为 "
    "identity_appearance, hair_face, body_support, torso_chain, head_pose_expression, "
    "left_hand_chain, right_hand_chain, leg_foot_chain, clothing_materials, occlusion_contact, exposure_details。"
    "每个字段必须是完整句，句式为 对象 + 画面位置/方向 + 链式动作/属性 + 接触或遮挡。"
    "禁止裸词、裸百分比、裸角度、标签串，例如 人物，画面中心，60%，0度，水平，高举。"
)

CAMERA_LIGHT_CONTRACT = (
    "camera_angle 必须写画幅、主体占比、机位高度、俯仰、roll倾斜、透视和裁切。"
    "light_incidence 必须写光源画面方位、光源高度、入射方向、阴影投射方向和高光落点。"
)


def _json_block(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2)


def build_standard_prompt() -> str:
    schema = {
        "mode": "standard",
        "visible_facts": {
            "primary_subject": "一句话说明主体",
            "subject_type": "person/object/animal/scene/vehicle/building/food/text/abstract",
            "scene": "背景和空间",
            "composition": "画幅、景别、主体位置",
            "style_light_color": "风格、光线、颜色",
            "visible_text": [],
        },
        "final_prompt": "一段自然语言正向提示词，不超过600字",
        "negative_prompt": ["文字", "水印"],
    }
    return (
        "标准反推：快速生成稳定可用的图像复刻提示词。"
        f"{VISIBLE_ONLY_RULE}{TEXT_RULE}"
        "输出必须是 JSON，结构如下："
        + _json_block(schema)
    )


def build_expert_prompt() -> str:
    schema = {
        "mode": "expert",
        "visual_spec": {
            "basic_summary": "一句短定位",
            "subject": {},
            "foreground": {},
            "background": {},
            "composition_camera": {},
            "light_color_style": {},
        },
        "evidence": {
            "primary_subject": "",
            "subject_type": "",
            "camera_angle": "",
            "light_incidence": "",
        },
        "final_prompt": "完整正向复刻提示词",
        "negative_prompt": [],
    }
    return (
        "专家反推：单次多模态读取，高颗粒度复刻。"
        f"{VISIBLE_ONLY_RULE}{TEXT_RULE}{NSFW_RULE}{PERSON_CONTRACT}{CAMERA_LIGHT_CONTRACT}"
        "foreground 只写非主体近景道具；background 只写环境；subject 是主体细节，不混入背景清单。"
        "输出必须是 JSON，结构如下："
        + _json_block(schema)
    )


def build_expert_team_global_prompt() -> str:
    schema = {
        "mode": "expert_team_global",
        "global_scan": {
            "primary_subject": "",
            "subject_type": "",
            "subject_regions": "",
            "non_subject_regions": "",
            "needed_focus": [],
        },
        "fact_cards": [],
        "negative_prompt": [],
    }
    return (
        "专家团第1轮：只做整体扫描、主体识别和深挖计划，不写最终复刻提示词。"
        f"{VISIBLE_ONLY_RULE}{TEXT_RULE}"
        "必须识别主体类型；非人物主体不得分配人体字段。输出 JSON："
        + _json_block(schema)
    )


def build_expert_team_subject_prompt(global_scan: dict[str, Any]) -> str:
    schema = {
        "mode": "expert_team_subject",
        "visual_spec": {
            "basic_summary": "一句短定位",
            "subject": {},
            "foreground": {},
            "background": {},
            "composition_camera": {},
            "light_color_style": {},
        },
        "fact_cards": [],
        "final_prompt": "",
        "negative_prompt": [],
    }
    return (
        "专家团第2轮：只深挖主体、主体持有/接触的道具、构图光色。"
        f"{VISIBLE_ONLY_RULE}{NSFW_RULE}{PERSON_CONTRACT}{CAMERA_LIGHT_CONTRACT}"
        "subject 必须比 basic_summary 更长更细。输出 JSON："
        + _json_block(schema)
        + "\n第1轮结果："
        + json.dumps(global_scan, ensure_ascii=False)
    )


def build_expert_team_review_prompt(draft: dict[str, Any]) -> str:
    schema = {
        "mode": "expert_team_review",
        "review": {
            "passed": False,
            "reject_if": [
                "subject 不是对象",
                "出现裸词/裸角度/标签串",
                "左右手前后矛盾",
                "道具或背景混入主体",
            ],
            "fixed_issues": [],
        },
        "visual_spec": {},
        "final_prompt": "",
        "negative_prompt": [],
    }
    return (
        "专家团复核：基于原图校对初稿，必须修正结构、矛盾和缺失。"
        f"{VISIBLE_ONLY_RULE}{PERSON_CONTRACT}{CAMERA_LIGHT_CONTRACT}"
        "reject_if 任一命中时必须修正后再输出。输出 JSON："
        + _json_block(schema)
        + "\n初稿："
        + json.dumps(draft, ensure_ascii=False)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_reverse_contracts
```

Expected: `OK`.

---

### Task 3: Implement Parser and Compatibility Adapter

**Files:**
- Create: `modules/image_reverse/parser.py`
- Modify: `tests/test_image_reverse_pipelines.py`

- [ ] **Step 1: Write parser tests**

Create `tests/test_image_reverse_pipelines.py`:

```python
import unittest

from modules.image_reverse.contracts import REVERSE_MODE_EXPERT
from modules.image_reverse.parser import parse_reverse_json


class ImageReverseParserTests(unittest.TestCase):
    def test_parse_expert_json_to_compatible_output(self):
        raw = """{
          "visual_spec": {
            "basic_summary": "红色主题人物图",
            "subject": {
              "torso_chain": "人物骨盆位于下中，胸腔向画面左上旋转，脊柱形成斜向C型趋势。",
              "left_hand_chain": "画面左侧手臂从肩部向左上抬起，肘部弯曲约90度，手指握住红色易拉罐。"
            },
            "foreground": {"drink_stack": "画面左下有红色易拉罐堆叠。"},
            "background": {"wall": "背景是灰色金属墙板。"},
            "composition_camera": {"camera_angle": "高机位俯拍，镜头向下约35度。"},
            "light_color_style": {"color": "红色服装与灰色背景形成强对比。"}
          },
          "final_prompt": "红色主题人物图，人物骨盆位于下中，胸腔向画面左上旋转",
          "negative_prompt": ["文字", "水印"]
        }"""

        output = parse_reverse_json(raw, mode=REVERSE_MODE_EXPERT, provider="test")

        self.assertIn("胸腔向画面左上旋转", output.prompt)
        self.assertIn("画面描述", output.visual_spec)
        self.assertIn("主体", output.visual_spec["画面描述"])
        self.assertIn("躯干链", output.visual_spec["画面描述"]["主体"])
        self.assertEqual(output.negative_prompt, ["文字", "水印"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_reverse_pipelines
```

Expected: `ModuleNotFoundError: No module named 'modules.image_reverse.parser'`.

- [ ] **Step 3: Implement parser**

Create `modules/image_reverse/parser.py`:

```python
from __future__ import annotations

import json
import re
from typing import Any

from .contracts import REVERSE_MODE_EXPERT, REVERSE_MODE_EXPERT_TEAM, REVERSE_MODE_STANDARD, ReverseOutput


SUBJECT_FIELD_LABELS = {
    "identity_appearance": "主体身份与外观",
    "hair_face": "头发脸部",
    "body_support": "空间支撑",
    "torso_chain": "躯干链",
    "head_pose_expression": "头部表情",
    "left_hand_chain": "画面左侧手臂链",
    "right_hand_chain": "画面右侧手臂链",
    "leg_foot_chain": "腿脚链",
    "clothing_materials": "服装材质",
    "occlusion_contact": "遮挡接触",
    "exposure_details": "暴露内容",
}


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = str(text or "").strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except Exception:
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}


def _list_negative(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，;；]+", value) if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _compat_subject(subject: Any) -> Any:
    if not isinstance(subject, dict):
        return subject
    result = {}
    for key, value in subject.items():
        label = SUBJECT_FIELD_LABELS.get(str(key), str(key))
        if value not in ("", None, [], {}):
            result[label] = value
    return result


def _compat_visual_spec(spec: dict[str, Any]) -> dict[str, Any]:
    visual_spec = spec.get("visual_spec") if isinstance(spec.get("visual_spec"), dict) else spec
    description = {
        "基本概述": visual_spec.get("basic_summary") or visual_spec.get("summary") or "",
        "主体": _compat_subject(visual_spec.get("subject") or {}),
        "前景": visual_spec.get("foreground") or {},
        "背景": visual_spec.get("background") or {},
        "整体画面": {
            "构图镜头": visual_spec.get("composition_camera") or {},
            "光影色彩风格": visual_spec.get("light_color_style") or {},
        },
    }
    return {"画面描述": {key: value for key, value in description.items() if value not in ("", None, [], {})}}


def _prompt_from_spec(parsed: dict[str, Any]) -> str:
    prompt = str(parsed.get("final_prompt") or parsed.get("keyword_prompt") or "").strip()
    if prompt:
        return prompt
    spec = parsed.get("visual_spec") if isinstance(parsed.get("visual_spec"), dict) else {}
    parts = []
    for value in (spec.get("basic_summary"), spec.get("subject"), spec.get("foreground"), spec.get("background")):
        if isinstance(value, dict):
            parts.extend(str(item) for item in value.values() if str(item).strip())
        elif value:
            parts.append(str(value))
    return "，".join(parts)


def parse_reverse_json(raw_text: str, *, mode: str, provider: str) -> ReverseOutput:
    parsed = extract_json_object(raw_text)
    prompt = _prompt_from_spec(parsed)
    visual_spec = _compat_visual_spec(parsed)
    expert = None
    if mode in {REVERSE_MODE_EXPERT, REVERSE_MODE_EXPERT_TEAM}:
        expert = {
            "enabled": True,
            "mode": "expert_team" if mode == REVERSE_MODE_EXPERT_TEAM else "expert",
            "experts": parsed.get("expert_observations") or [],
            "fact_cards": parsed.get("fact_cards") or [],
            "review": parsed.get("review") or parsed.get("expert_review"),
        }
    return ReverseOutput(
        mode=mode,
        provider=provider,
        prompt=prompt,
        negative_prompt=_list_negative(parsed.get("negative_prompt")),
        visual_spec=visual_spec,
        raw=parsed,
        expert_interrogate=expert,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_reverse_pipelines
```

Expected: `OK`.

---

### Task 4: Implement New Pipelines

**Files:**
- Create: `modules/image_reverse/pipelines.py`
- Modify: `tests/test_image_reverse_pipelines.py`

- [ ] **Step 1: Write pipeline tests**

Append to `tests/test_image_reverse_pipelines.py`:

```python
import tempfile
from pathlib import Path

from PIL import Image

from modules.image_reverse.contracts import (
    REVERSE_MODE_EXPERT,
    REVERSE_MODE_EXPERT_TEAM,
    REVERSE_MODE_STANDARD,
)
from modules.image_reverse.pipelines import (
    run_expert_reverse,
    run_expert_team_reverse,
    run_standard_reverse,
)


class ImageReversePipelineTests(unittest.TestCase):
    def _image_path(self):
        td = tempfile.TemporaryDirectory()
        path = Path(td.name) / "sample.png"
        Image.new("RGB", (640, 960), (120, 80, 70)).save(path)
        self.addCleanup(td.cleanup)
        return str(path)

    def test_standard_pipeline_calls_chat_once(self):
        calls = []

        def fake_chat(messages, **kwargs):
            calls.append(messages[1]["content"][0]["text"])
            return '{"final_prompt":"标准结果","visual_spec":{"basic_summary":"标准图"},"negative_prompt":["文字"]}'

        result = run_standard_reverse(self._image_path(), chat_fn=fake_chat, model="m")

        self.assertEqual(len(calls), 1)
        self.assertEqual(result.mode, REVERSE_MODE_STANDARD)
        self.assertEqual(result.prompt, "标准结果")

    def test_expert_pipeline_calls_chat_once(self):
        calls = []

        def fake_chat(messages, **kwargs):
            calls.append(messages[1]["content"][0]["text"])
            return '{"final_prompt":"专家结果","visual_spec":{"basic_summary":"专家图","subject":{"torso_chain":"躯干链完整句"}}}'

        result = run_expert_reverse(self._image_path(), chat_fn=fake_chat, model="m")

        self.assertEqual(len(calls), 1)
        self.assertEqual(result.mode, REVERSE_MODE_EXPERT)
        self.assertIn("躯干链完整句", result.visual_spec["画面描述"]["主体"]["躯干链"])

    def test_expert_team_pipeline_calls_three_stages(self):
        calls = []

        def fake_chat(messages, **kwargs):
            text = messages[1]["content"][0]["text"]
            calls.append(text)
            if "第1轮" in text:
                return '{"global_scan":{"primary_subject":"人物","subject_type":"person"},"fact_cards":[]}'
            if "第2轮" in text:
                return '{"visual_spec":{"basic_summary":"人物图","subject":{"torso_chain":"躯干链完整句"}},"final_prompt":"主体深挖结果","negative_prompt":["水印"]}'
            return '{"visual_spec":{"basic_summary":"人物图","subject":{"torso_chain":"复核后的躯干链完整句"}},"final_prompt":"复核结果","negative_prompt":["水印"],"review":{"passed":true}}'

        result = run_expert_team_reverse(self._image_path(), chat_fn=fake_chat, model="m")

        self.assertEqual(len(calls), 3)
        self.assertEqual(result.mode, REVERSE_MODE_EXPERT_TEAM)
        self.assertEqual(result.prompt, "复核结果")
        self.assertEqual(result.expert_interrogate["mode"], "expert_team")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_reverse_pipelines
```

Expected: import failure for `modules.image_reverse.pipelines`.

- [ ] **Step 3: Implement pipelines**

Create `modules/image_reverse/pipelines.py`:

```python
from __future__ import annotations

import time
from typing import Any, Callable

from modules.llm_client import DIRECT_FINAL_SYSTEM_PROMPT, image_to_data_url, llm_provider_name

from .contracts import (
    REVERSE_MODE_EXPERT,
    REVERSE_MODE_EXPERT_TEAM,
    REVERSE_MODE_STANDARD,
    ReverseOutput,
    mode_token_budget,
)
from .parser import extract_json_object, parse_reverse_json
from .prompts import (
    build_expert_prompt,
    build_expert_team_global_prompt,
    build_expert_team_review_prompt,
    build_expert_team_subject_prompt,
    build_standard_prompt,
)


def _chat_image(
    image_path: str,
    prompt: str,
    *,
    chat_fn: Callable[..., str],
    model: str | None,
    max_tokens: int,
    timeout: float,
    temperature: float,
) -> str:
    data_url = image_to_data_url(image_path)
    return chat_fn(
        [
            {"role": "system", "content": DIRECT_FINAL_SYSTEM_PROMPT + " Return only valid JSON."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        response_format={"type": "json_object"},
    )


def _with_elapsed(output: ReverseOutput, started_at: float) -> ReverseOutput:
    output.elapsed_seconds = round(max(0.0, time.monotonic() - started_at), 3)
    return output


def run_standard_reverse(
    image_path: str,
    *,
    chat_fn: Callable[..., str],
    model: str | None = None,
    timeout: float = 180.0,
) -> ReverseOutput:
    started = time.monotonic()
    raw = _chat_image(
        image_path,
        build_standard_prompt(),
        chat_fn=chat_fn,
        model=model,
        max_tokens=mode_token_budget(REVERSE_MODE_STANDARD),
        timeout=timeout,
        temperature=0.1,
    )
    return _with_elapsed(parse_reverse_json(raw, mode=REVERSE_MODE_STANDARD, provider=llm_provider_name(model, vision=True)), started)


def run_expert_reverse(
    image_path: str,
    *,
    chat_fn: Callable[..., str],
    model: str | None = None,
    timeout: float = 300.0,
) -> ReverseOutput:
    started = time.monotonic()
    raw = _chat_image(
        image_path,
        build_expert_prompt(),
        chat_fn=chat_fn,
        model=model,
        max_tokens=mode_token_budget(REVERSE_MODE_EXPERT),
        timeout=timeout,
        temperature=0.08,
    )
    return _with_elapsed(parse_reverse_json(raw, mode=REVERSE_MODE_EXPERT, provider=llm_provider_name(model, vision=True)), started)


def run_expert_team_reverse(
    image_path: str,
    *,
    chat_fn: Callable[..., str],
    model: str | None = None,
    timeout: float = 480.0,
) -> ReverseOutput:
    started = time.monotonic()
    global_raw = _chat_image(
        image_path,
        build_expert_team_global_prompt(),
        chat_fn=chat_fn,
        model=model,
        max_tokens=2048,
        timeout=timeout,
        temperature=0.05,
    )
    global_json = extract_json_object(global_raw)
    subject_raw = _chat_image(
        image_path,
        build_expert_team_subject_prompt(global_json.get("global_scan") or global_json),
        chat_fn=chat_fn,
        model=model,
        max_tokens=mode_token_budget(REVERSE_MODE_EXPERT_TEAM),
        timeout=timeout,
        temperature=0.05,
    )
    subject_json = extract_json_object(subject_raw)
    review_raw = _chat_image(
        image_path,
        build_expert_team_review_prompt(subject_json),
        chat_fn=chat_fn,
        model=model,
        max_tokens=4096,
        timeout=timeout,
        temperature=0.03,
    )
    output = parse_reverse_json(review_raw, mode=REVERSE_MODE_EXPERT_TEAM, provider=llm_provider_name(model, vision=True))
    output.raw = {
        "global_pass": global_json,
        "subject_pass": subject_json,
        "review_pass": extract_json_object(review_raw),
    }
    return _with_elapsed(output, started)
```

- [ ] **Step 4: Run pipeline tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_reverse_pipelines
```

Expected: `OK`.

---

### Task 5: Replace Legacy Entry Points

**Files:**
- Create: `modules/image_reverse/legacy_adapter.py`
- Modify: `modules/prompt_interrogator.py`
- Modify: `app.py`
- Test: `tests/test_prompt_optimizer.py`

- [ ] **Step 1: Add adapter tests around API mode selection**

Modify existing API tests in `tests/test_prompt_optimizer.py` so the expert-team test expects `mode == "expert_team"` instead of `"single_pass_team"`:

```python
self.assertEqual(result["expert_interrogate"]["mode"], "expert_team")
```

Keep existing tests that assert:

```python
self.assertTrue(kwargs.get("expert_team"))
self.assertTrue(result["expert_interrogate"]["enabled"])
```

- [ ] **Step 2: Run affected tests to verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_prompt_optimizer
```

Expected: failure where the old mode is still returned.

- [ ] **Step 3: Implement legacy adapter**

Create `modules/image_reverse/legacy_adapter.py`:

```python
from __future__ import annotations

from typing import Callable

from modules.llm_client import chat_text

from .pipelines import run_expert_reverse, run_expert_team_reverse, run_standard_reverse


def run_llm_image_interrogator_v2(
    image_path: str,
    *,
    chat_fn: Callable[..., str] = chat_text,
    timeout: float = 180.0,
    max_new_tokens: int = 3072,
    model: str | None = None,
    compact: bool = False,
    include_quality: bool = False,
) -> dict:
    return run_standard_reverse(
        image_path,
        chat_fn=chat_fn,
        model=model,
        timeout=timeout,
    ).to_api_payload()


def run_llm_expert_image_interrogator_v2(
    image_path: str,
    *,
    chat_fn: Callable[..., str] = chat_text,
    timeout: float = 300.0,
    max_new_tokens: int = 6144,
    model: str | None = None,
    single_pass: bool = False,
    stage: str = "full",
    review_enabled: bool = True,
    include_quality: bool = False,
    expert_team: bool = False,
) -> dict:
    if expert_team:
        return run_expert_team_reverse(
            image_path,
            chat_fn=chat_fn,
            model=model,
            timeout=timeout,
        ).to_api_payload()
    return run_expert_reverse(
        image_path,
        chat_fn=chat_fn,
        model=model,
        timeout=timeout,
    ).to_api_payload()
```

- [ ] **Step 4: Delegate old names to new adapter**

In `modules/prompt_interrogator.py`, replace the bodies of:

```python
run_llm_image_interrogator(...)
run_llm_expert_image_interrogator(...)
```

with calls to:

```python
from modules.image_reverse.legacy_adapter import (
    run_llm_expert_image_interrogator_v2,
    run_llm_image_interrogator_v2,
)
```

The wrapper bodies should be:

```python
return run_llm_image_interrogator_v2(
    image_path,
    chat_fn=chat_fn,
    timeout=timeout,
    max_new_tokens=max_new_tokens,
    model=model,
    compact=compact,
    include_quality=include_quality,
)
```

and:

```python
return run_llm_expert_image_interrogator_v2(
    image_path,
    chat_fn=chat_fn,
    timeout=timeout,
    max_new_tokens=max_new_tokens,
    model=model,
    single_pass=single_pass,
    stage=stage,
    review_enabled=review_enabled,
    include_quality=include_quality,
    expert_team=expert_team,
)
```

- [ ] **Step 5: Run compatibility tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_prompt_optimizer tests.test_image_reverse_contracts tests.test_image_reverse_pipelines
```

Expected: `OK`.

---

### Task 6: Remove Legacy Prompt/Test Accretion

**Files:**
- Modify: `modules/prompt_interrogator.py`
- Modify: `tests/test_prompt_interrogator.py`
- Modify: `tests/test_prompt_interrogate_ui.py`

- [ ] **Step 1: Identify unused legacy constants**

Run:

```bash
rg -n "RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE|EXPERT_TEAM_SECOND_REVIEW_TEMPLATE|EXPERT_TEAM_COMPLETE_SENTENCE_STANDARD|EXPERT_TEAM_VISUAL_SPEC_CONTRACT|BODY_STRUCTURE_REQUIRED_FIELDS|TRUNK_HAND_OBJECT_ANGLE_STANDARD" modules tests
```

Expected: after Task 5, these should only be referenced by old tests or unused legacy code.

- [ ] **Step 2: Delete legacy prompt constants and expert-team parser branches**

In `modules/prompt_interrogator.py`, delete:

```python
RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE
RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE
EXPERT_TEAM_GLOBAL_PASS_TEMPLATE
EXPERT_TEAM_SUBJECT_PASS_TEMPLATE
EXPERT_TEAM_SECOND_REVIEW_TEMPLATE
RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE
```

Keep:

```python
prepare_interrogate_image
build_image_interrogate_workflow
extract_interrogate_result
build_qwen_vqa_prompt_workflow
run_qwen_vqa_image_prompt
```

If deletion is too risky in one step, first leave constants but stop exporting or testing them; then delete after all tests pass.

- [ ] **Step 3: Replace transitional tests**

In `tests/test_prompt_interrogator.py`, remove tests whose only purpose is checking specific wording in old prompt constants. Keep tests for:

```python
prepare_interrogate_image
extract_interrogate_result
build_image_interrogate_workflow
run_llm_image_interrogator compatibility wrapper
run_llm_expert_image_interrogator compatibility wrapper
```

Move new behavior coverage to:

```python
tests/test_image_reverse_contracts.py
tests/test_image_reverse_pipelines.py
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_prompt_interrogator tests.test_prompt_interrogate_ui tests.test_image_reverse_contracts tests.test_image_reverse_pipelines
```

Expected: `OK`.

---

### Task 7: Verify API and Restart Service

**Files:**
- No source edits unless tests reveal an integration bug.

- [ ] **Step 1: Run API and prompt tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_prompt_optimizer tests.test_prompt_interrogator tests.test_prompt_interrogate_ui tests.test_image_reverse_contracts tests.test_image_reverse_pipelines
```

Expected: `OK`.

- [ ] **Step 2: Compile changed Python files**

Run:

```bash
.venv/bin/python -m py_compile app.py modules/prompt_interrogator.py modules/image_reverse/contracts.py modules/image_reverse/prompts.py modules/image_reverse/parser.py modules/image_reverse/pipelines.py modules/image_reverse/legacy_adapter.py
```

Expected: no output and exit code 0.

- [ ] **Step 3: Restart service**

Run:

```bash
./quick-start.sh restart
```

Expected: `EZ ComfyUI Showcase restarted at http://127.0.0.1:18000/`.

- [ ] **Step 4: Verify status**

Run:

```bash
curl -sS -i http://127.0.0.1:18000/api/status
```

Expected:

```text
HTTP/1.1 200 OK
```

and JSON includes:

```json
{"version":"v4.4.5"}
```

---

## Self-Review

- Spec coverage: The plan covers standard, expert, and expert-team modes; prompt contracts; output contracts; single-flow and multi-flow pipelines; compatibility output; cleanup of legacy prompt/test accretion.
- Placeholder scan: No task contains TBD/TODO/implement-later placeholders.
- Type consistency: Public wrappers return `dict` API payloads; new pipelines return `ReverseOutput`; parser accepts raw JSON text and emits `ReverseOutput`.
- Scope: This is one cohesive subsystem rewrite. UI changes are intentionally limited to compatibility unless later testing shows the result panel needs mode-specific display.

