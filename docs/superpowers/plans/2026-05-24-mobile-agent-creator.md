# Mobile Agent Creator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the V1 mobile creator loop: one typed or spoken sentence becomes a default text-to-image generation request with minimal confirmation.

**Architecture:** Add a thin local agent layer that owns deterministic intent routing, prompt fallback cleanup, default workflow resolution, and structured output. The mobile system lives in its own backend route/service files and frontend module namespace, while reusing the existing auth, workflow metadata, workflow analysis, generation, job, and history systems through explicit integration points.

**Tech Stack:** FastAPI, Python standard library, existing prompt optimizer helpers, existing workflow metadata, vanilla JS ES modules, existing CSS/icon system, unittest/pytest-compatible tests.

---

## File Structure

- Create `modules/mobile_agent.py`
  - Pure backend orchestration logic: intent classification, prompt compilation fallback, workflow alias resolution, ratio dimensions, and response contract.
- Create `modules/speech_transcriber.py`
  - Optional local Whisper/faster-whisper adapter with timeout-safe failure output. V1 must work even if no backend is installed.
- Create `modules/mobile_agent_routes.py`
  - Mobile-only FastAPI route registration. It receives existing app dependencies through a small dependency map so route logic does not live in `app.py`.
- Modify `app.py`
  - Only import and register `modules.mobile_agent_routes.register_mobile_agent_routes(app, deps)`. Do not add mobile request models, route handlers, or business logic to `app.py`.
- Create `static/js/modules/mobile_agent/mobile-agent.js`
  - Mobile creator state machine, text/voice input, understand call, confirmation screen, and generate handoff.
- Modify `static/js/module_loader.js`
  - Load `mobile_agent/mobile-agent.js` after `generate.js` so it can reuse generation helpers.
- Modify `static/index.html`
  - Add one root container for the mobile creator shell. Keep it as a mount point only.
- Create `static/css/mobile-agent.css`
  - Mobile-first creator styles scoped under `.mobile-agent`.
- Add `tests/test_mobile_agent.py`
  - Unit tests for backend routing, prompt fallback, settings, and workflow rejection.
- Add `tests/test_mobile_agent_routes.py`
  - Direct route tests for fallback behavior and auth-safe workflow resolution.
- Add `tests/test_mobile_agent_ui.py`
  - Static contract tests for module loading, screen states, icons, and mobile viewport CSS.

## Task 1: Backend Pure Agent Module

**Files:**
- Create: `modules/mobile_agent.py`
- Test: `tests/test_mobile_agent.py`

- [ ] **Step 1: Write failing tests for intent routing and prompt fallback**

Add `tests/test_mobile_agent.py`:

```python
import unittest

from modules.mobile_agent import (
    DEFAULT_MOBILE_CREATOR_SETTINGS,
    IntentRouter,
    PromptCompiler,
    build_generate_fields,
    ratio_to_dimensions,
    build_agent_response,
)


class MobileAgentTests(unittest.TestCase):
    def test_text_without_media_routes_to_text_to_image(self):
        result = IntentRouter().classify("帮我出一张未来城市雨夜的照片")

        self.assertEqual(result["intent"], "text_to_image")
        self.assertGreaterEqual(result["confidence"], 0.8)
        self.assertEqual(result["reason"], "text_only_image_request")

    def test_video_words_do_not_route_to_v1_text_to_image(self):
        result = IntentRouter().classify("帮我把这张图动起来做成视频")

        self.assertEqual(result["intent"], "unsupported_video")
        self.assertLess(result["confidence"], 0.8)
        self.assertIn("视频", result["question"])

    def test_image_present_routes_to_deferred_image_edit(self):
        result = IntentRouter().classify("帮我把背景换成雨夜", has_image=True)

        self.assertEqual(result["intent"], "unsupported_image_edit")
        self.assertIn("图片编辑", result["question"])

    def test_prompt_compiler_removes_request_words_and_detects_ratio(self):
        compiled = PromptCompiler().compile("帮我出一张手机壁纸，未来城市雨夜，电影感")

        self.assertIn("未来城市雨夜", compiled["compiled_prompt"])
        self.assertNotIn("帮我", compiled["compiled_prompt"])
        self.assertEqual(compiled["aspect_ratio"], "9:16")
        self.assertEqual(compiled["style"], "cinematic")

    def test_ratio_to_dimensions_uses_mobile_creator_defaults(self):
        self.assertEqual(ratio_to_dimensions("9:16"), {"width": 720, "height": 1280})
        self.assertEqual(ratio_to_dimensions("1:1"), {"width": 1024, "height": 1024})

    def test_build_agent_response_uses_internal_workflow_alias(self):
        response = build_agent_response(
            text="帮我出一张切成片的西瓜",
            settings={**DEFAULT_MOBILE_CREATOR_SETTINGS, "default_text_to_image_workflow": "t2i-z-image.json"},
            workflow_available=True,
        )

        self.assertEqual(response["intent"], "text_to_image")
        self.assertEqual(response["workflow"], "default_text_to_image")
        self.assertEqual(response["resolved_workflow"], "t2i-z-image.json")
        self.assertFalse(response["needs_confirmation"])
        self.assertIn("compiled_prompt", response)
        self.assertIn("style", response["options"])
        self.assertIn("aspect_ratio", response["options"])

    def test_build_agent_response_handles_unavailable_workflow(self):
        response = build_agent_response(
            text="帮我出一张切成片的西瓜",
            settings={**DEFAULT_MOBILE_CREATOR_SETTINGS, "default_text_to_image_workflow": "missing.json"},
            workflow_available=False,
        )

        self.assertEqual(response["intent"], "text_to_image")
        self.assertTrue(response["needs_confirmation"])
        self.assertEqual(response["error_code"], "workflow_unavailable")

    def test_build_generate_fields_puts_prompt_into_prompt_like_field(self):
        fields = [
            {"node_id": "1", "field": "text", "label": "提示词", "class_type": "Text Multiline", "zone": "user_input"},
            {"node_id": "2", "field": "width", "label": "宽度", "class_type": "PrimitiveInt", "zone": "output"},
        ]

        result = build_generate_fields(fields, "未来城市雨夜")

        self.assertEqual(result, {"1::text": "未来城市雨夜"})

    def test_build_generate_fields_returns_empty_when_no_prompt_field_exists(self):
        fields = [{"node_id": "2", "field": "width", "label": "宽度", "class_type": "PrimitiveInt"}]

        self.assertEqual(build_generate_fields(fields, "未来城市雨夜"), {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_mobile_agent.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'modules.mobile_agent'`.

- [ ] **Step 3: Implement `modules/mobile_agent.py`**

Create `modules/mobile_agent.py`:

```python
"""Local mobile creator intent and prompt orchestration."""

from __future__ import annotations

import re
from typing import Any

from modules.prompt_optimizer import clean_user_prompt


DEFAULT_MOBILE_CREATOR_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "default_text_to_image_workflow": "t2i_Qwen_Image_2512_4steps.json",
    "allowed_styles": ["realistic", "cinematic", "anime"],
    "allowed_ratios": ["1:1", "3:4", "9:16"],
    "llm_timeout_ms": 1500,
    "speech_timeout_ms": 5000,
}

RATIO_DIMENSIONS = {
    "1:1": {"width": 1024, "height": 1024},
    "3:4": {"width": 960, "height": 1280},
    "9:16": {"width": 720, "height": 1280},
}

VIDEO_RE = re.compile(r"(视频|动起来|动画|运动|镜头|video|animate|motion|move)", re.I)
IMAGE_EDIT_RE = re.compile(r"(修改|换成|去掉|修图|编辑|改成|背景|image edit|retouch)", re.I)
WALLPAPER_RE = re.compile(r"(手机壁纸|竖屏|竖图|phone wallpaper|wallpaper|9:16)", re.I)
CINEMATIC_RE = re.compile(r"(电影感|cinematic|film|镜头感)", re.I)
ANIME_RE = re.compile(r"(动漫|动画风|二次元|anime|manga)", re.I)
PROMPT_FIELD_RE = re.compile(r"(prompt|positive|提示词|正向|text)", re.I)


def _clean_text(text: str) -> str:
    cleaned = clean_user_prompt(str(text or "").strip())
    return re.sub(r"\s+", " ", cleaned).strip()


def ratio_to_dimensions(ratio: str) -> dict[str, int]:
    return dict(RATIO_DIMENSIONS.get(str(ratio or ""), RATIO_DIMENSIONS["1:1"]))


def build_generate_fields(workflow_fields: list[dict[str, Any]], compiled_prompt: str) -> dict[str, Any]:
    for field in workflow_fields or []:
        label = " ".join(str(field.get(k) or "") for k in ("label", "field", "class_type", "zone"))
        if PROMPT_FIELD_RE.search(label):
            node_id = str(field.get("node_id") or "")
            field_name = str(field.get("field") or "")
            if node_id and field_name:
                return {f"{node_id}::{field_name}": compiled_prompt}
    return {}


class IntentRouter:
    def classify(self, text: str, has_image: bool = False, has_video: bool = False) -> dict[str, Any]:
        raw = str(text or "").strip()
        if has_video or VIDEO_RE.search(raw):
            return {
                "intent": "unsupported_video",
                "confidence": 0.55,
                "reason": "video_deferred",
                "question": "视频创作会在后续版本开放，当前先支持一句话出图。",
            }
        if has_image or IMAGE_EDIT_RE.search(raw) and "一张" not in raw:
            return {
                "intent": "unsupported_image_edit",
                "confidence": 0.55,
                "reason": "image_edit_deferred",
                "question": "图片编辑会在后续版本开放，当前先支持一句话出图。",
            }
        if len(_clean_text(raw)) < 4:
            return {
                "intent": "clarify",
                "confidence": 0.3,
                "reason": "too_short",
                "question": "你想生成什么画面？",
            }
        return {
            "intent": "text_to_image",
            "confidence": 0.9,
            "reason": "text_only_image_request",
            "question": "",
        }


class PromptCompiler:
    def compile(self, text: str, style: str = "", aspect_ratio: str = "") -> dict[str, Any]:
        raw = str(text or "").strip()
        cleaned = _clean_text(raw)
        selected_style = style or self._detect_style(raw)
        selected_ratio = aspect_ratio or self._detect_ratio(raw)
        display = cleaned[:80] if cleaned else raw[:80]
        prompt = self._append_style_hint(cleaned or raw, selected_style)
        return {
            "raw_text": raw,
            "display_summary": display,
            "compiled_prompt": prompt,
            "style": selected_style,
            "aspect_ratio": selected_ratio,
        }

    def _detect_style(self, text: str) -> str:
        if ANIME_RE.search(text):
            return "anime"
        if CINEMATIC_RE.search(text):
            return "cinematic"
        return "realistic"

    def _detect_ratio(self, text: str) -> str:
        if WALLPAPER_RE.search(text):
            return "9:16"
        if "3:4" in text:
            return "3:4"
        return "1:1"

    def _append_style_hint(self, prompt: str, style: str) -> str:
        hints = {
            "realistic": "真实照片风格",
            "cinematic": "电影感构图与光影",
            "anime": "动漫插画风格",
        }
        hint = hints.get(style, "")
        if hint and hint not in prompt:
            return f"{prompt}，{hint}"
        return prompt


def build_agent_response(
    text: str,
    settings: dict[str, Any] | None = None,
    workflow_available: bool = True,
    has_image: bool = False,
    has_video: bool = False,
) -> dict[str, Any]:
    cfg = {**DEFAULT_MOBILE_CREATOR_SETTINGS, **(settings or {})}
    intent = IntentRouter().classify(text, has_image=has_image, has_video=has_video)
    compiled = PromptCompiler().compile(text)
    dims = ratio_to_dimensions(compiled["aspect_ratio"])
    response: dict[str, Any] = {
        **intent,
        **compiled,
        **dims,
        "workflow": "default_text_to_image",
        "resolved_workflow": str(cfg.get("default_text_to_image_workflow") or ""),
        "needs_confirmation": intent["intent"] != "text_to_image",
        "error_code": "",
        "options": {
            "style": list(cfg.get("allowed_styles") or []),
            "aspect_ratio": list(cfg.get("allowed_ratios") or []),
        },
    }
    if intent["intent"] == "text_to_image" and not workflow_available:
        response["needs_confirmation"] = True
        response["error_code"] = "workflow_unavailable"
        response["question"] = "默认出图工作流暂不可用，请稍后重试。"
    return response
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
python -m pytest tests/test_mobile_agent.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/mobile_agent.py tests/test_mobile_agent.py
git commit -m "Add mobile creator agent core"
```

## Task 2: Backend Speech Adapter

**Files:**
- Create: `modules/speech_transcriber.py`
- Test: `tests/test_mobile_agent.py`

- [ ] **Step 1: Add failing tests for speech fallback**

Append to `tests/test_mobile_agent.py`:

```python
from modules.speech_transcriber import SpeechTranscriber


class SpeechTranscriberTests(unittest.TestCase):
    def test_missing_speech_backend_returns_editable_failure(self):
        result = SpeechTranscriber(command="definitely-missing-whisper").transcribe_bytes(
            b"fake audio",
            filename="voice.webm",
            timeout_ms=200,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["provider"], "none")
        self.assertEqual(result["transcript"], "")
        self.assertEqual(result["error_code"], "speech_backend_unavailable")

    def test_empty_audio_returns_validation_failure(self):
        result = SpeechTranscriber(command="whisper").transcribe_bytes(b"", filename="voice.webm")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "empty_audio")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_mobile_agent.py::SpeechTranscriberTests -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'modules.speech_transcriber'`.

- [ ] **Step 3: Implement timeout-safe speech adapter**

Create `modules/speech_transcriber.py`:

```python
"""Optional local speech-to-text adapter for mobile creator voice input."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Any


class SpeechTranscriber:
    def __init__(self, command: str | None = None) -> None:
        self.command = command or os.environ.get("EZ_WHISPER_COMMAND", "whisper")

    def transcribe_bytes(self, content: bytes, filename: str = "voice.webm", timeout_ms: int = 5000) -> dict[str, Any]:
        if not content:
            return self._failure("empty_audio", "No audio was received.")
        if not shutil.which(self.command):
            return self._failure("speech_backend_unavailable", "Local speech backend is not installed.")

        suffix = os.path.splitext(filename or "")[1] or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                [self.command, tmp_path, "--output_format", "txt", "--output_dir", os.path.dirname(tmp_path)],
                capture_output=True,
                text=True,
                timeout=max(1, timeout_ms / 1000),
            )
            if result.returncode != 0:
                return self._failure("speech_transcribe_failed", (result.stderr or "").strip()[:240])
            txt_path = os.path.splitext(tmp_path)[0] + ".txt"
            transcript = ""
            if os.path.exists(txt_path):
                with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                    transcript = f.read().strip()
            return {
                "ok": bool(transcript),
                "provider": self.command,
                "transcript": transcript,
                "duration_ms": 0,
                "error_code": "" if transcript else "empty_transcript",
            }
        except subprocess.TimeoutExpired:
            return self._failure("speech_timeout", "Speech transcription timed out.")
        finally:
            for path in (tmp_path, os.path.splitext(tmp_path)[0] + ".txt"):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _failure(self, code: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "provider": "none",
            "transcript": "",
            "duration_ms": 0,
            "error_code": code,
            "message": message,
        }
```

- [ ] **Step 4: Run speech tests**

Run:

```bash
python -m pytest tests/test_mobile_agent.py::SpeechTranscriberTests -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/speech_transcriber.py tests/test_mobile_agent.py
git commit -m "Add mobile creator speech adapter"
```

## Task 3: Mobile Agent API Routes

**Files:**
- Create: `modules/mobile_agent_routes.py`
- Modify: `app.py` only to register the mobile routes
- Test: `tests/test_mobile_agent_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `tests/test_mobile_agent_routes.py`:

```python
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.mobile_agent_routes import register_mobile_agent_routes


class MobileAgentRoutesTests(unittest.TestCase):
    def setUp(self):
        self.workflow_name = "t2i-test.json"
        self.settings = {"mobile_creator": {"default_text_to_image_workflow": self.workflow_name}}
        api = FastAPI()
        register_mobile_agent_routes(api, {
            "get_current_user": lambda: {"sub": "user1", "role": "user"},
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: {self.workflow_name: {}},
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}" if filename == self.workflow_name else None,
            "can_view_workflow": lambda filename, entry, user: filename == self.workflow_name,
            "analyze_workflow": lambda path: {"fields": [
                {"node_id": "1", "field": "text", "label": "提示词", "class_type": "Text Multiline", "zone": "user_input"}
            ]},
            "add_log": lambda *args, **kwargs: None,
            "user_id": lambda user: user.get("sub", ""),
        })
        self.client = TestClient(api)

    def test_understand_returns_structured_mobile_agent_payload(self):
        response = self.client.post("/api/mobile-agent/understand", json={"text": "帮我出一张未来城市雨夜的照片"})

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["ok"])
        data = result["data"]
        self.assertEqual(data["intent"], "text_to_image")
        self.assertEqual(data["workflow"], "default_text_to_image")
        self.assertEqual(data["resolved_workflow"], self.workflow_name)
        self.assertIn("compiled_prompt", data)
        self.assertEqual(data["field_values"], {"1::text": data["compiled_prompt"]})

    def test_understand_reports_unavailable_default_workflow(self):
        self.settings = {"mobile_creator": {"default_text_to_image_workflow": "missing.json"}}

        response = self.client.post("/api/mobile-agent/understand", json={"text": "帮我出一张未来城市雨夜的照片"})

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["error_code"], "workflow_unavailable")
        self.assertTrue(result["data"]["needs_confirmation"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_mobile_agent_routes.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'modules.mobile_agent_routes'`.

- [ ] **Step 3: Create mobile route registration module**

Create `modules/mobile_agent_routes.py`:

```python
"""FastAPI route registration for the mobile creator surface.

This module keeps mobile creator API handlers out of app.py while reusing app-owned
auth, workflow, settings, and logging dependencies through an explicit dependency map.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, File, Form, UploadFile
from pydantic import BaseModel

from modules.mobile_agent import (
    DEFAULT_MOBILE_CREATOR_SETTINGS,
    build_agent_response,
    build_generate_fields,
)
from modules.speech_transcriber import SpeechTranscriber


class MobileAgentUnderstandRequest(BaseModel):
    text: str = ""
    has_image: bool = False
    has_video: bool = False


def _mobile_creator_settings(load_system_settings: Callable[[], dict]) -> dict:
    settings = (load_system_settings() or {}).get("mobile_creator", {})
    return {**DEFAULT_MOBILE_CREATOR_SETTINGS, **(settings or {})}


def register_mobile_agent_routes(app: Any, deps: dict[str, Callable[..., Any]]) -> None:
    get_current_user = deps["get_current_user"]
    load_system_settings = deps["load_system_settings"]
    load_wf_meta = deps["load_wf_meta"]
    normalize_wf_meta_entry = deps["normalize_wf_meta_entry"]
    resolve_workflow = deps["resolve_workflow"]
    can_view_workflow = deps["can_view_workflow"]
    analyze_workflow = deps["analyze_workflow"]
    add_log = deps["add_log"]
    user_id = deps["user_id"]

    @app.post("/api/mobile-agent/understand")
    def api_mobile_agent_understand(
        req: MobileAgentUnderstandRequest,
        current_user: dict = Depends(get_current_user),
    ):
        settings = _mobile_creator_settings(load_system_settings)
        workflow = str(settings.get("default_text_to_image_workflow") or "")
        meta = load_wf_meta()
        entry = normalize_wf_meta_entry(workflow, meta.get(workflow, {}))
        workflow_path = resolve_workflow(workflow, entry) if workflow else None
        workflow_available = bool(
            workflow
            and workflow_path
            and can_view_workflow(workflow, entry, current_user)
        )
        data = build_agent_response(
            text=req.text,
            settings=settings,
            workflow_available=workflow_available,
            has_image=req.has_image,
            has_video=req.has_video,
        )
        if workflow_available and workflow_path:
            try:
                analysis = analyze_workflow(workflow_path)
                data["field_values"] = build_generate_fields(
                    analysis.get("fields", []),
                    data.get("compiled_prompt", ""),
                )
            except Exception as exc:
                add_log("warn", "mobile_agent", f"Mobile field mapping failed: {exc}", details=f"user={user_id(current_user)}")
                data["field_values"] = {}
        else:
            data["field_values"] = {}
        return {"ok": True, "data": data}

    @app.post("/api/mobile-agent/transcribe")
    async def api_mobile_agent_transcribe(
        file: UploadFile = File(...),
        timeout_ms: int = Form(5000),
        current_user: dict = Depends(get_current_user),
    ):
        content = await file.read()
        result = SpeechTranscriber().transcribe_bytes(
            content,
            filename=file.filename or "voice.webm",
            timeout_ms=timeout_ms,
        )
        level = "info" if result.get("ok") else "warn"
        add_log(level, "mobile_agent", "Voice transcription requested", details=f"user={user_id(current_user)} provider={result.get('provider')}")
        return result
```

- [ ] **Step 4: Register mobile routes from `app.py` with a minimal integration block**

In `app.py`, add one import near other module imports:

```python
from modules.mobile_agent_routes import register_mobile_agent_routes
```

After all referenced dependency functions are defined and before startup, add:

```python
register_mobile_agent_routes(app, {
    "get_current_user": get_current_user,
    "load_system_settings": _load_system_settings,
    "load_wf_meta": _load_wf_meta,
    "normalize_wf_meta_entry": _normalize_wf_meta_entry,
    "resolve_workflow": _resolve_workflow,
    "can_view_workflow": _can_view_workflow,
    "analyze_workflow": analyze_workflow,
    "add_log": add_log,
    "user_id": _user_id,
})
```

Do not add mobile request classes, mobile route functions, prompt compilation, or speech logic to `app.py`.

- [ ] **Step 5: Run route tests**

Run:

```bash
python -m pytest tests/test_mobile_agent_routes.py -q
```

Expected: PASS.

- [ ] **Step 6: Run nearby settings tests**

Run:

```bash
python -m pytest tests/test_system_settings_api.py tests/test_mobile_agent_routes.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app.py modules/mobile_agent_routes.py tests/test_mobile_agent_routes.py
git commit -m "Add mobile creator agent API"
```

## Task 4: Mobile Creator Frontend Shell

**Files:**
- Create: `static/js/modules/mobile_agent/mobile-agent.js`
- Modify: `static/js/module_loader.js`
- Modify: `static/index.html`
- Create: `static/css/mobile-agent.css`
- Test: `tests/test_mobile_agent_ui.py`

- [ ] **Step 1: Write failing frontend contract tests**

Create `tests/test_mobile_agent_ui.py`:

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MobileAgentUiContractTests(unittest.TestCase):
    def test_mobile_agent_module_is_loaded(self):
        loader = (ROOT / "static/js/module_loader.js").read_text()

        self.assertIn("/modules/mobile_agent/mobile-agent.js?v=", loader)
        self.assertIn("static/css/mobile-agent.css?v=", loader)
        self.assertLess(loader.index("/modules/generate.js?v="), loader.index("/modules/mobile_agent/mobile-agent.js?v="))

    def test_mobile_agent_root_exists(self):
        html = (ROOT / "static/index.html").read_text()

        self.assertIn('id="mobileAgentRoot"', html)
        self.assertIn('class="mobile-agent"', html)

    def test_mobile_agent_module_renders_core_states(self):
        js = (ROOT / "static/js/modules/mobile_agent/mobile-agent.js").read_text()

        self.assertIn("function renderHome", js)
        self.assertIn("function renderVoice", js)
        self.assertIn("function renderConfirm", js)
        self.assertIn("function renderGenerating", js)
        self.assertIn("function submitUnderstand", js)
        self.assertIn("/api/mobile-agent/understand", js)
        self.assertIn("/api/mobile-agent/transcribe", js)
        self.assertIn("CW.mobileAgent", js)
        self.assertIn("CW.icon('send'", js)
        self.assertIn("CW.icon('mic'", js)

    def test_mobile_agent_css_is_mobile_first_and_scoped(self):
        css = (ROOT / "static/css/mobile-agent.css").read_text()

        self.assertIn(".mobile-agent", css)
        self.assertIn(".mobile-agent-panel", css)
        self.assertIn(".mobile-agent-input-row", css)
        self.assertIn("@media (max-width: 700px)", css)
        self.assertIn("height: calc(var(--vh, 1vh) * 100", css)
        self.assertIn("overflow-x: hidden", css)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_mobile_agent_ui.py -q
```

Expected: FAIL because the module, root, and CSS do not exist.

- [ ] **Step 3: Add root container to `static/index.html`**

After the titlebar, add:

```html
<main class="mobile-agent hidden" id="mobileAgentRoot" aria-label="移动端智能创作入口"></main>
```

- [ ] **Step 4: Load mobile CSS and module after existing core assets**

In `static/js/module_loader.js`, load the separate mobile CSS next to the existing stylesheet:

```javascript
    await loadStylesheet('static/css/mobile-agent.css?v=' + version);
```

Then add `mobile_agent/mobile-agent.js` after `generate.js`:

```javascript
    base + '/modules/generate.js?v=' + version,
    base + '/modules/mobile_agent/mobile-agent.js?v=' + version,
    base + '/modules/auth.js?v=' + version,
```

- [ ] **Step 5: Implement `static/js/modules/mobile_agent/mobile-agent.js`**

Create `static/js/modules/mobile_agent/mobile-agent.js`:

```javascript
/**
 * Mobile Agent Creator Module
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, escH = A.escH;
  var API = A.API;
  var state = { screen: 'home', text: '', agent: null, busy: false, error: '' };

  function isMobileCreatorPreferred() {
    return window.matchMedia && window.matchMedia('(max-width: 700px)').matches;
  }

  function showRoot() {
    var root = $('#mobileAgentRoot');
    if (!root) return;
    root.classList.toggle('hidden', !isMobileCreatorPreferred());
  }

  function icon(name) {
    return window.CW && CW.icon ? CW.icon(name) : '';
  }

  function renderHome() {
    state.screen = 'home';
    var root = $('#mobileAgentRoot');
    if (!root) return;
    root.innerHTML =
      '<section class="mobile-agent-panel">' +
        '<div class="mobile-agent-avatar" aria-hidden="true">EZ</div>' +
        '<div class="mobile-agent-title">想创作什么图？</div>' +
        '<div class="mobile-agent-subtitle">输入或说一句想法，我来选择合适的出图方式。</div>' +
        '<div class="mobile-agent-input-row">' +
          '<textarea id="mobileAgentInput" rows="3" placeholder="例如：帮我出一张未来城市雨夜的照片">' + escH(state.text || '') + '</textarea>' +
        '</div>' +
        '<div class="mobile-agent-actions">' +
          '<button class="mobile-agent-icon-btn" type="button" data-action="future-image" disabled>' + icon('image') + '</button>' +
          '<button class="mobile-agent-icon-btn" type="button" data-action="voice">' + icon('mic') + '</button>' +
          '<button class="mobile-agent-send" type="button" data-action="send">' + icon('send') + '<span>发送</span></button>' +
        '</div>' +
        (state.error ? '<div class="mobile-agent-error">' + escH(state.error) + '</div>' : '') +
      '</section>';
  }

  function renderVoice() {
    state.screen = 'voice';
    var root = $('#mobileAgentRoot');
    if (!root) return;
    root.innerHTML =
      '<section class="mobile-agent-panel">' +
        '<div class="mobile-agent-title">语音输入</div>' +
        '<div class="mobile-agent-wave">Listening...</div>' +
        '<div class="mobile-agent-subtitle">录音完成后会先变成可编辑文字。</div>' +
        '<div class="mobile-agent-actions">' +
          '<button class="mobile-agent-send" type="button" data-action="voice-cancel">取消</button>' +
          '<button class="mobile-agent-send" type="button" data-action="voice-fake">使用示例语音</button>' +
        '</div>' +
      '</section>';
  }

  function renderConfirm() {
    state.screen = 'confirm';
    var data = state.agent || {};
    var root = $('#mobileAgentRoot');
    if (!root) return;
    root.innerHTML =
      '<section class="mobile-agent-panel">' +
        '<div class="mobile-agent-title">我会生成</div>' +
        '<div class="mobile-agent-summary">' + escH(data.display_summary || data.compiled_prompt || state.text) + '</div>' +
        '<div class="mobile-agent-option-label">风格</div>' +
        '<div class="mobile-agent-chips" data-option="style">' + renderChips(data.options && data.options.style, data.style) + '</div>' +
        '<div class="mobile-agent-option-label">比例</div>' +
        '<div class="mobile-agent-chips" data-option="aspect_ratio">' + renderChips(data.options && data.options.aspect_ratio, data.aspect_ratio) + '</div>' +
        '<div class="mobile-agent-actions">' +
          '<button class="mobile-agent-send" type="button" data-action="back">修改</button>' +
          '<button class="mobile-agent-send primary" type="button" data-action="generate">开始生成</button>' +
        '</div>' +
      '</section>';
  }

  function renderChips(options, selected) {
    return (options || []).map(function(opt) {
      return '<button class="mobile-agent-chip' + (opt === selected ? ' active' : '') + '" type="button" data-value="' + escH(opt) + '">' + escH(labelFor(opt)) + '</button>';
    }).join('');
  }

  function labelFor(value) {
    return ({ realistic: '真实', cinematic: '电影感', anime: '动漫' })[value] || value;
  }

  function renderGenerating() {
    state.screen = 'generating';
    var root = $('#mobileAgentRoot');
    if (!root) return;
    root.innerHTML =
      '<section class="mobile-agent-panel">' +
        '<div class="mobile-agent-title">正在创作</div>' +
        '<div class="mobile-agent-progress">排队中...</div>' +
        '<div class="mobile-agent-summary">' + escH((state.agent && state.agent.display_summary) || state.text) + '</div>' +
      '</section>';
  }

  async function submitUnderstand() {
    var input = $('#mobileAgentInput');
    state.text = input ? input.value.trim() : state.text;
    if (!state.text) {
      state.error = '先输入一句想法。';
      renderHome();
      return;
    }
    state.busy = true;
    state.error = '';
    var r = await A.authFetch(API + '/api/mobile-agent/understand', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: state.text })
    });
    var payload = await r.json();
    state.busy = false;
    state.agent = payload.data || null;
    renderConfirm();
  }

  function applyChip(target) {
    var group = target.closest('[data-option]');
    if (!group || !state.agent) return;
    var key = group.getAttribute('data-option');
    state.agent[key] = target.getAttribute('data-value');
    renderConfirm();
  }

  function submitGenerate() {
    renderGenerating();
    if (window.CW && CW.showToast) CW.showToast('已准备好进入生成队列', 'info');
  }

  function handleClick(e) {
    var actionEl = e.target.closest('[data-action]');
    var chip = e.target.closest('.mobile-agent-chip');
    if (chip) return applyChip(chip);
    if (!actionEl) return;
    var action = actionEl.getAttribute('data-action');
    if (action === 'send') submitUnderstand();
    else if (action === 'voice') renderVoice();
    else if (action === 'voice-cancel' || action === 'back') renderHome();
    else if (action === 'voice-fake') { state.text = '帮我出一张未来城市雨夜的照片'; renderHome(); }
    else if (action === 'generate') submitGenerate();
  }

  function initMobileAgent() {
    var root = $('#mobileAgentRoot');
    if (!root) return;
    root.addEventListener('click', handleClick);
    showRoot();
    renderHome();
    window.addEventListener('resize', showRoot);
  }

  if (!window.CW) window.CW = {};
  window.CW.mobileAgent = { init: initMobileAgent, renderHome: renderHome, renderConfirm: renderConfirm };

  document.addEventListener('DOMContentLoaded', initMobileAgent);
})();
```

- [ ] **Step 6: Add scoped CSS in its own file**

Create `static/css/mobile-agent.css`:

```css
.mobile-agent {
  display: none;
}

.mobile-agent.hidden {
  display: none;
}

@media (max-width: 700px) {
  .mobile-agent {
    display: flex;
    min-height: calc(var(--vh, 1vh) * 100 - var(--titlebar-h));
    overflow-x: hidden;
    padding: 16px;
    align-items: center;
    justify-content: center;
  }

  .mobile-agent-panel {
    width: min(100%, 420px);
    border: 1px solid var(--border);
    border-radius: 18px;
    background: rgba(10, 10, 15, .88);
    padding: 18px;
  }

  .mobile-agent-avatar {
    width: 64px;
    height: 64px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    margin: 0 auto 16px;
    color: var(--accent);
    border: 1px solid var(--border-accent);
  }

  .mobile-agent-title {
    font-size: 20px;
    font-weight: 700;
    text-align: center;
  }

  .mobile-agent-subtitle,
  .mobile-agent-summary,
  .mobile-agent-error {
    margin-top: 10px;
    color: var(--text-secondary);
    line-height: 1.5;
    overflow-wrap: anywhere;
  }

  .mobile-agent-input-row textarea {
    width: 100%;
    margin-top: 16px;
    resize: none;
  }

  .mobile-agent-actions,
  .mobile-agent-chips {
    display: flex;
    gap: 10px;
    margin-top: 14px;
    flex-wrap: wrap;
  }

  .mobile-agent-icon-btn,
  .mobile-agent-send,
  .mobile-agent-chip {
    min-height: 44px;
  }

  .mobile-agent-send.primary,
  .mobile-agent-chip.active {
    border-color: var(--border-accent);
    color: var(--accent);
  }
}
```

- [ ] **Step 7: Run frontend contract tests**

Run:

```bash
python -m pytest tests/test_mobile_agent_ui.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add static/index.html static/js/module_loader.js static/js/modules/mobile_agent/mobile-agent.js static/css/mobile-agent.css tests/test_mobile_agent_ui.py
git commit -m "Add mobile creator frontend shell"
```

## Task 5: Generate Handoff From Agent Output

**Files:**
- Modify: `static/js/modules/mobile_agent/mobile-agent.js`
- Test: `tests/test_mobile_agent_ui.py`

- [ ] **Step 1: Add failing frontend generate-handoff test**

Append to `tests/test_mobile_agent_ui.py`:

```python
    def test_generate_handoff_calls_existing_generate_api(self):
        js = (ROOT / "static/js/modules/mobile_agent/mobile-agent.js").read_text()

        self.assertIn("function submitGenerate", js)
        self.assertIn("/api/generate", js)
        self.assertIn("resolved_workflow", js)
        self.assertIn("field_values", js)
        self.assertIn("width", js)
        self.assertIn("height", js)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_mobile_agent_ui.py::MobileAgentUiContractTests::test_generate_handoff_calls_existing_generate_api -q
```

Expected: FAIL because `/api/generate` handoff is missing.

- [ ] **Step 3: Update frontend generate submission**

Replace the placeholder `submitGenerate()` in `static/js/modules/mobile_agent/mobile-agent.js` with:

```javascript
  async function submitGenerate() {
    var data = state.agent || {};
    if (!data.resolved_workflow || data.error_code) {
      state.error = data.question || '默认工作流暂不可用。';
      renderHome();
      return;
    }
    renderGenerating();
    var r = await A.authFetch(API + '/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workflow: data.resolved_workflow,
        fields: data.field_values || {},
        width: data.width || 0,
        height: data.height || 0
      })
    });
    var payload = await r.json();
    if (!r.ok) {
      state.error = payload.detail || '提交生成失败。';
      renderHome();
      return;
    }
    state.jobId = payload.job_id;
    if (window.CW && CW.showToast) CW.showToast('已开始生成', 'success');
  }
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
python -m pytest tests/test_mobile_agent.py tests/test_mobile_agent_routes.py tests/test_mobile_agent_ui.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/modules/mobile_agent/mobile-agent.js tests/test_mobile_agent_ui.py
git commit -m "Wire mobile creator to generate API"
```

## Task 6: Verification and Mobile QA

**Files:**
- Modify only if tests expose defects: `static/css/mobile-agent.css`, `static/js/modules/mobile_agent/mobile-agent.js`, `modules/mobile_agent_routes.py`, or the minimal route registration block in `app.py`

- [ ] **Step 1: Run backend and frontend contract tests**

Run:

```bash
python -m pytest tests/test_mobile_agent.py tests/test_mobile_agent_routes.py tests/test_mobile_agent_ui.py tests/test_prompt_optimizer.py tests/test_workflow_manager_ui.py -q
```

Expected: PASS.

- [ ] **Step 2: Start or restart the local app**

Run:

```bash
./quick-start.sh restart
```

Expected: service restarts and reports port `18000`.

- [ ] **Step 3: Confirm app health**

Run:

```bash
curl -sS -i http://127.0.0.1:18000/api/version
```

Expected: HTTP 200 with the current app version JSON.

- [ ] **Step 4: Browser-check mobile layout**

Use the available browser or Playwright workflow to open:

```text
http://127.0.0.1:18000/
```

Viewport:

```text
390 x 844
```

Expected:

- Mobile creator shell is visible.
- No horizontal overflow.
- Text input, mic, and send buttons fit without overlap.
- Sending a typed prompt reaches the confirmation state.
- The confirmation state shows summary, style chips, ratio chips, and generate.

- [ ] **Step 5: Browser-check desktop is not hijacked**

Viewport:

```text
1280 x 900
```

Expected:

- Existing desktop dashboard remains visible.
- Mobile creator shell is hidden.
- Workflow picker, history, and generation panel still load normally.

- [ ] **Step 6: Commit QA fixes if needed**

If Step 4 or Step 5 required fixes:

```bash
git add static/css/mobile-agent.css static/js/modules/mobile_agent/mobile-agent.js modules/mobile_agent_routes.py app.py
git commit -m "Polish mobile creator verification issues"
```

If no fixes were required, do not create an empty commit.

## Self-Review

Spec coverage:

- One-sentence text-to-image flow is covered by Tasks 1, 3, 4, and 5.
- Voice input with local Whisper-style fallback is covered by Tasks 2 and 4.
- Local LLM auxiliary behavior is represented by the prompt compiler fallback and leaves the later local Qwen/Gemma/Llama call behind a bounded adapter point.
- Rule-owned routing and constrained agent output are covered by Task 1.
- Existing generation, jobs, and history remain the source of truth through Task 5.
- Mobile viewport verification is covered by Task 6.

Placeholder scan:

- The plan uses concrete paths, concrete tests, concrete commands, and implementation snippets.
- No unresolved placeholder markers remain.

Type consistency:

- Backend response keys are `workflow`, `resolved_workflow`, `compiled_prompt`, `field_values`, `width`, and `height`.
- Frontend uses the same keys when calling `/api/generate`.
- Test names match the functions introduced in the implementation tasks.
