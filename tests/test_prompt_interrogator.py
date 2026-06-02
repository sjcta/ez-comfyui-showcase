import json
import unittest
import tempfile
from pathlib import Path

from modules.prompt_optimizer import HIGH_SUCCESS_PROMPT_SPEC_GUIDE
from modules.image_reverse_skill import (
    DIRECT_REVERSE_PROMPT_WRITING_SKILL,
    IMAGE_REVERSE_RULEBOOK,
    IMAGE_REVERSE_RUNTIME_RULE_INDEX,
    REPLICATION_TARGET_SCORE,
    RULE_CATEGORY_FILES,
    RULES_DIR,
    validate_reverse_prompt_quality,
)
from modules.prompt_interrogator import (
    CAR_FRONT_SEAT_POSE_STANDARD,
    BEDROOM_SEATED_POSE_STANDARD,
    COLOR_PRECISION_STANDARD,
    STYLE_ANALYSIS_STANDARD,
    HAIR_APPEARANCE_STANDARD,
    CAMERA_AND_BODY_ANGLE_STANDARD,
    TRUNK_HAND_OBJECT_ANGLE_STANDARD,
    LIGHT_INCIDENCE_ANGLE_STANDARD,
    EXPERT_TEAM_COMPLETE_SENTENCE_STANDARD,
    EXPERT_TEAM_VISUAL_SPEC_CONTRACT,
    HUMAN_POSE_EXPERT_STANDARD,
    ARM_ELBOW_CHAIN_STANDARD,
    BODY_JOINT_CHAIN_COMPLETENESS_STANDARD,
    BODY_STRUCTURE_REQUIRED_FIELDS,
    SPATIAL_CONTROL_COORDINATE_STANDARD,
    TERMINAL_NODE_DETAIL_STANDARD,
    HEAD_POSE_REPLICATION_EXAMPLE,
    NSFW_DETAIL_STANDARD,
    REVERSE_MODE_PRECISION_STANDARD,
    STANDARD_REVERSE_SEVEN_LAYER_SCHEMA,
    EXPERT_REVERSE_DEEP_SCHEMA,
    EXPERT_TEAM_SELF_ASSEMBLY_STANDARD,
    SELF_DIRECTED_DIMENSION_STANDARD,
    TWO_LEVEL_JSON_STANDARD,
    VISIBLE_ONLY_STANDARD,
    SCENE_OBJECT_VERIFICATION_STANDARD,
    EXPERT_TEAM_DETAIL_SCHEMA,
    EXPERT_TEAM_SINGLE_EXPERT_QUALITY_STANDARD,
    EXPERT_TEAM_FACT_CARD_STANDARD,
    EXPERT_TEAM_REVIEW_CHECKLIST,
    FAST_IMAGE_INTERROGATE_TEMPLATE,
    EXPERT_IMAGE_INTERROGATE_TEMPLATE,
    EXPERT_IMAGE_REVIEW_TEMPLATE,
    EXPERT_IMAGE_MERGE_TEMPLATE,
    FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE,
    RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE,
    RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE,
    RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE,
    EXPERT_TEAM_GLOBAL_PASS_TEMPLATE,
    EXPERT_TEAM_SUBJECT_PASS_TEMPLATE,
    EXPERT_TEAM_SECOND_REVIEW_TEMPLATE,
    EXPERT_INTERROGATE_MAX_TOKENS,
    EXPERT_TEAM_GLOBAL_MAX_TOKENS,
    EXPERT_TEAM_SUBJECT_MAX_TOKENS,
    EXPERT_TEAM_REVIEW_MAX_TOKENS,
    IMAGE_INTERROGATE_EXPERTS,
    _clean_positive_prompt_text,
    _clean_negative_prompt_text,
    build_image_interrogate_workflow,
    build_qwen_vqa_prompt_workflow,
    extract_interrogate_result,
    _extract_json_object,
    _parse_structured_interrogate_text,
    prepare_interrogate_image,
    run_qwen_vqa_image_prompt,
    run_llm_expert_image_interrogator,
    run_llm_image_interrogator,
    _normalize_visual_evidence,
    _backfill_expert_results_from_visual_evidence,
    _clamp_expert_result_text,
    _prompt_from_structured_json,
    _select_experts_from_global_overview,
    _expert_specs_for_stage,
    _build_expert_batch_prompt,
    _expert_observation_from_markdown,
    _local_expert_detail_failure,
)


class PromptInterrogatorTests(unittest.TestCase):
    def test_expert_stage_ladder_limits_subject_experts(self):
        overview = {
            "has_person": True,
            "primary_subject": "人物主体",
            "visible_elements": ["人物", "粉色衣物"],
            "detail_focus": ["肢体动作", "服装边界", "裸露边界"],
            "recommended_experts": [
                "composition",
                "color_light",
                "body_pose",
                "clothing_makeup",
                "sexual_boundary",
            ],
        }

        one = _expert_specs_for_stage(overview, "overview_plus_1")
        two = _expert_specs_for_stage(overview, "overview_plus_2_subject")

        self.assertEqual([spec["id"] for spec in one], ["body_pose"])
        self.assertEqual([spec["id"] for spec in two], ["body_pose", "sexual_boundary"])

    def test_qwen_vqa_prompt_workflow_uses_supplied_expert_prompt(self):
        workflow = build_qwen_vqa_prompt_workflow(
            "uploads/test.jpg",
            "同一段专家提示词",
            max_new_tokens=777,
        )

        self.assertEqual(workflow["1"]["class_type"], "LoadImage")
        self.assertEqual(workflow["1"]["inputs"]["image"], "uploads/test.jpg")
        self.assertEqual(workflow["3"]["class_type"], "Qwen3_VQA")
        self.assertEqual(workflow["3"]["inputs"]["text"], "同一段专家提示词")
        self.assertEqual(workflow["3"]["inputs"]["max_new_tokens"], 777)

    def test_run_qwen_vqa_image_prompt_returns_show_text_output(self):
        submitted = {}

        def fake_post(path, payload, base_url):
            submitted["path"] = path
            submitted["payload"] = payload
            submitted["base_url"] = base_url
            return {"prompt_id": "abc"}

        def fake_get(path, base_url):
            self.assertEqual(path, "/history/abc")
            self.assertEqual(base_url, "http://qwen")
            return {
                "abc": {
                    "status": {"completed": True},
                    "outputs": {"4": {"text": ["Qwen 输出内容"]}},
                }
            }

        text = run_qwen_vqa_image_prompt(
            "uploads/test.jpg",
            "同一段专家提示词",
            "http://qwen",
            fake_post,
            fake_get,
            timeout=1,
            poll_interval=0.01,
        )

        self.assertEqual(text, "Qwen 输出内容")
        self.assertEqual(submitted["payload"]["prompt"]["3"]["inputs"]["text"], "同一段专家提示词")

    def test_run_qwen_vqa_image_prompt_tolerates_transient_history_timeout(self):
        calls = {"get": 0}

        def fake_post(path, payload, base_url):
            return {"prompt_id": "abc"}

        def fake_get(path, base_url):
            calls["get"] += 1
            if calls["get"] == 1:
                raise TimeoutError("history busy")
            return {
                "abc": {
                    "status": {"completed": True},
                    "outputs": {"4": {"text": ["pong"]}},
                }
            }

        text = run_qwen_vqa_image_prompt(
            "uploads/test.jpg",
            "只回复 pong",
            "http://qwen",
            fake_post,
            fake_get,
            timeout=1,
            poll_interval=0.01,
        )

        self.assertEqual(text, "pong")
        self.assertEqual(calls["get"], 2)

    def test_run_llm_expert_image_interrogator_calls_each_expert_and_merges_json(self):
        calls = []

        def fake_chat(messages, **kwargs):
            text = messages[1]["content"][0]["text"]
            calls.append(text)
            if "全局概览调度器" in text:
                return json.dumps(
                    {
                        "has_person": False,
                        "image_type": "人像",
                        "visible_elements": ["人物", "粉色衣物", "近距离低角度构图"],
                        "recommended_experts": [spec["id"] for spec in IMAGE_INTERROGATE_EXPERTS],
                        "reason": "图中有人物主体，需要完整人物专家组",
                    },
                    ensure_ascii=False,
                )
            if "accuracy_score = 属实断言数" in text:
                reviewed_specs = [
                    spec for spec in IMAGE_INTERROGATE_EXPERTS if f'"id":"{spec["id"]}"' in text
                ] or [IMAGE_INTERROGATE_EXPERTS[0]]
                return json.dumps(
                    {
                        "summary": "批次专家结论足够细腻且基本属实",
                        "retry_expert_ids": [],
                        "reviews": [
                            {
                                "id": reviewed_spec["id"],
                                "label": reviewed_spec["label"],
                                "passed": True,
                                "accuracy_score": 0.95,
                                "detail_score": 0.86,
                                "factual_score": 0.88,
                                "boundary_score": 0.9,
                                "claim_checks": [
                                    {"claim": "专家断言属实", "verdict": True, "reason": "图中可验证"}
                                ],
                                "missing": [],
                                "unsupported": [],
                                "retry_instruction": "",
                            }
                            for reviewed_spec in reviewed_specs
                        ],
                    },
                    ensure_ascii=False,
                )
            if "最终合并器" in text:
                self.assertIn("构图镜头专家", text)
                self.assertIn("摄影参数专家", text)
                self.assertIn("暴露内容专家", text)
                return """{
                  "keyword_prompt": "粉色衣物人物，低角度近距离抬腿构图，脸部和脚被裁切",
                  "english_prompt": "person in pink outfit, low-angle close raised-leg composition, face and feet cropped",
                  "structured_prompt": {
                    "画面描述": {
                      "人物": {"主体": "粉色衣物人物"},
                      "肢体动作": {"姿势": "一条腿高抬靠近镜头，身体侧向后方"},
                      "构图镜头": {
                        "遮挡裁切": "脸部上半部分和双脚被画幅裁切，胯部被抬起的大腿和衣物遮挡",
                        "镜头": "手机近距离低角度仰拍，前景腿部占比很大"
                      },
                      "服装妆容": {"服装": ["粉色短袖上衣", "短裙或短裤疑似"]}
                    },
                    "负面提示词": {
                      "构图镜头": ["不要误写成平视"],
                      "暴露内容": ["不要写可见性器官"]
                    }
                  },
                  "structured_prompt_en": {
                    "image_description": {
                      "subject": {"main": "person in pink outfit"},
                      "composition_camera": {"crop": "upper face and both feet cropped out, crotch occluded by raised thigh and clothing"}
                    },
                    "negative_prompt": {"composition_camera": ["do not describe as eye-level"]}
                  }
                }"""
            if "专家组批次任务" in text:
                parts = []
                for spec in IMAGE_INTERROGATE_EXPERTS:
                    if f"专家代号: {spec['id']}" not in text:
                        continue
                    if spec["id"] == "composition":
                        parts.append("## 构图镜头专家\n- 摘要: 低角度近距离构图\n- 断言: 前景腿部占比很大\n- 字段/镜头: 手机近距离低角度仰拍\n- 字段/空间坐标: 主体位于画面中心，前景腿部靠近镜头下方\n- 负面: 平视\n- 置信度: 0.9")
                    elif spec["id"] == "photography_parameters":
                        parts.append("## 摄影参数专家\n- 摘要: 手机近距离拍摄，大光圈浅景深倾向\n- 断言: 背景轻微虚化\n- 字段/曝光: 高调曝光，采光度充足\n- 负面: 过暗曝光\n- 置信度: 0.78")
                    elif spec["id"] == "sexual_boundary":
                        parts.append("## 暴露内容专家\n- 摘要: 胯部被抬起的大腿和衣物遮挡\n- 断言: 胯部被抬起的大腿和衣物遮挡\n- 负面: 可见性器官\n- 置信度: 0.82")
                    elif spec["id"] == "body_pose":
                        parts.append("## 肢体动作专家\n- 摘要: 主体位于画面中心，头部在画面上方，脸部正脸朝镜头，眼神朝镜头，前景腿部靠近镜头下方\n- 断言: 前景腿部靠近镜头下方\n- 字段/空间坐标: 主体位于画面中心，头部在画面上方，腿部在画面下方前景\n- 字段/末梢节点: 头部正脸朝镜头，眼神朝镜头，嘴唇闭合\n- 置信度: 0.8")
                    elif spec["id"] == "expression_language":
                        parts.append("## 表情语言专家\n- 摘要: 头部位于画面上方，正脸朝镜头，眼神朝镜头，嘴唇闭合，发丝贴近脸颊\n- 断言: 眼神朝镜头\n- 字段/空间坐标: 头部位于画面上方\n- 字段/末梢节点: 正脸朝镜头，眼神朝镜头，嘴唇闭合，发丝贴近脸颊\n- 置信度: 0.8")
                    else:
                        parts.append(f"## {spec['label']}\n- 摘要: 可见事实\n- 断言: 可见事实\n- 字段/空间坐标: 主体位于画面中心\n- 置信度: 0.7")
                return "\n".join(parts)
            if "专家代号: composition" in text:
                return "## 构图镜头专家\n- 摘要: 低角度近距离构图\n- 断言: 前景腿部占比很大\n- 字段/镜头: 手机近距离低角度仰拍\n- 负面: 平视\n- 置信度: 0.9"
            if "专家代号: photography_parameters" in text:
                return "## 摄影参数专家\n- 摘要: 手机近距离拍摄，大光圈浅景深倾向\n- 断言: 背景轻微虚化\n- 字段/曝光: 高调曝光，采光度充足\n- 负面: 过暗曝光\n- 置信度: 0.78"
            if "专家代号: sexual_boundary" in text:
                return "## 暴露内容专家\n- 摘要: 胯部被抬起的大腿和衣物遮挡\n- 断言: 胯部被抬起的大腿和衣物遮挡\n- 负面: 可见性器官\n- 置信度: 0.82"
            return "## 其他专家\n- 摘要: 可见事实\n- 断言: 可见事实\n- 置信度: 0.7"

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (32, 32), (245, 210, 220)).save(image_path)
            result = run_llm_expert_image_interrogator(str(image_path), chat_fn=fake_chat, include_quality=True)

        expected_group_count = (len(IMAGE_INTERROGATE_EXPERTS) + 2) // 3
        self.assertEqual(len(calls), expected_group_count * 2 + 1)
        self.assertFalse(any("最终合并器" in call for call in calls))
        self.assertEqual(len(result["expert_interrogate"]["experts"]), len(IMAGE_INTERROGATE_EXPERTS))
        self.assertEqual(len(result["expert_interrogate"]["expert_batches"]), len(IMAGE_INTERROGATE_EXPERTS))
        self.assertEqual(len(result["expert_interrogate"]["expert_groups"]), expected_group_count)
        self.assertTrue(all(batch.get("attempts") == 1 for batch in result["expert_interrogate"]["expert_batches"]))
        self.assertIn("timings", result["expert_interrogate"])
        self.assertEqual(result["expert_interrogate"]["timings"]["merge_seconds"], 0.0)
        self.assertTrue(all("timings" in batch for batch in result["expert_interrogate"]["expert_batches"]))
        self.assertEqual(result["expert_interrogate"]["mode"], "staged")
        self.assertIn("review", result["expert_interrogate"])
        self.assertEqual(result["expert_interrogate"]["review_retry_count"], 0)
        self.assertEqual(len(result["expert_interrogate"]["review"]["reviews"]), len(IMAGE_INTERROGATE_EXPERTS))
        self.assertEqual(result["expert_interrogate"]["expected_expert_count"], len(IMAGE_INTERROGATE_EXPERTS))
        self.assertIn("手机近距离低角度仰拍", result["prompt"])
        self.assertIn("reverse_prompt_quality", result)
        self.assertEqual(result["reverse_prompt_quality"]["target_score"], REPLICATION_TARGET_SCORE)
        self.assertIn("quality", result["expert_interrogate"])
        self.assertTrue(any("专家代号: photography_parameters" in call for call in calls))
        self.assertTrue(all(expert.get("format") == "markdown" for expert in result["expert_interrogate"]["experts"]))
        self.assertIn("平视", result["negative_prompt"])
        self.assertNotIn("不要", result["negative_prompt"])
        self.assertIn('"画面描述": {', result["structured_prompt_json"])
        self.assertIn('"整体画面": "手机近距离低角度仰拍', result["structured_prompt_json"])
        self.assertNotIn('"构图镜头": {', result["structured_prompt_json"])
        self.assertNotIn('"主体外貌": {', result["structured_prompt_json"])
        self.assertNotIn('"负面提示词"', result["structured_prompt_json"])
        self.assertNotIn("双脚", result["structured_prompt_json"])
        self.assertIn("胯部被抬起的大腿和衣物遮挡", result["structured_prompt_json"])

    def test_staged_expert_interrogator_can_skip_review_for_fast_model_compare(self):
        calls = []

        def fake_chat(messages, **kwargs):
            text = messages[1]["content"][0]["text"]
            calls.append(text)
            if "全局概览调度器" in text:
                return json.dumps(
                    {
                        "has_person": True,
                        "image_type": "人像",
                        "primary_subject": "人物主体",
                        "visible_elements": ["人物", "服装"],
                        "detail_focus": ["肢体动作", "裸露边界"],
                        "recommended_experts": ["body_pose", "sexual_boundary"],
                    },
                    ensure_ascii=False,
                )
            if "专家组批次任务" in text:
                return (
                    "## 肢体动作专家\n- 摘要: 人物主体呈坐姿\n- 断言: 手臂在画面中部弯曲\n- 置信度: 0.8\n"
                    "## 暴露内容专家\n- 摘要: 只记录可见暴露边界\n- 断言: 衣物遮挡胯部区域\n- 置信度: 0.8"
                )
            raise AssertionError(f"unexpected prompt: {text[:80]}")

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (32, 32), (245, 210, 220)).save(image_path)
            result = run_llm_expert_image_interrogator(
                str(image_path),
                chat_fn=fake_chat,
                stage="overview_plus_2_subject",
                review_enabled=False,
            )

        self.assertEqual(len(calls), 2)
        self.assertFalse(any("accuracy_score = 属实断言数" in call for call in calls))
        self.assertEqual(result["expert_interrogate"]["review"]["summary"], "快速对照模式跳过评审复验")
        self.assertEqual(result["expert_interrogate"]["review_retry_count"], 0)
        self.assertTrue(all(batch.get("passed") for batch in result["expert_interrogate"]["expert_batches"]))

    def test_run_llm_expert_image_interrogator_retries_failed_reviewed_expert_once(self):
        calls = []

        def fake_chat(messages, **kwargs):
            text = messages[1]["content"][0]["text"]
            calls.append(text)
            if "全局概览调度器" in text:
                return '{"has_person":false,"image_type":"产品","visible_elements":["产品"],"recommended_experts":["composition"],"reason":"只测构图专家"}'
            if "复审专家已打回" in text:
                self.assertIn("必须写清近距离低角度", text)
                return "## 构图镜头专家\n- 摘要: 近距离低角度构图\n- 断言: 主体占据画面大部分\n- 字段/镜头: 近距离低角度构图，主体占据画面大部分\n- 负面: 平视\n- 置信度: 0.91"
            if "专家代号: composition" in text:
                return "## 构图镜头专家\n- 摘要: 模糊构图\n- 断言: 平视\n- 字段/镜头: 平视\n- 置信度: 0.4"
            if "accuracy_score = 属实断言数" in text and "模糊构图" in text:
                return """{
                  "summary": "构图专家不够细且有平视误判",
                  "retry_expert_ids": ["composition"],
                  "reviews": [{
                    "id": "composition",
                    "label": "构图镜头专家",
                    "passed": false,
                    "accuracy_score": 0.5,
                    "detail_score": 0.42,
                    "factual_score": 0.4,
                    "boundary_score": 0.8,
                    "claim_checks": [
                      {"claim": "平视", "verdict": false, "reason": "图中不是平视"}
                    ],
                    "missing": ["缺少画面边界和镜头距离"],
                    "unsupported": ["平视"],
                    "retry_instruction": "必须写清近距离低角度和主体占比，删除平视"
                  }]
                }"""
            if "accuracy_score = 属实断言数" in text:
                return """{
                  "summary": "重写后通过",
                  "retry_expert_ids": [],
                  "reviews": [{
                    "id": "composition",
                    "label": "构图镜头专家",
                    "passed": true,
                    "accuracy_score": 1.0,
                    "detail_score": 0.9,
                    "factual_score": 0.88,
                    "boundary_score": 0.92,
                    "claim_checks": [
                      {"claim": "近距离低角度构图", "verdict": true, "reason": "图中可验证"}
                    ],
                    "missing": [],
                    "unsupported": [],
                    "retry_instruction": ""
                  }]
                }"""
            if "最终合并器" in text:
                self.assertIn("近距离低角度构图", text)
                self.assertNotIn("模糊构图", text)
                return """{
                  "keyword_prompt": "近距离低角度构图，主体占据画面大部分",
                  "english_prompt": "close low-angle composition, subject fills most of the frame",
                  "structured_prompt": {
                    "画面描述": {"构图镜头": {"镜头": "近距离低角度构图，主体占据画面大部分"}},
                    "负面提示词": {"构图镜头": ["平视"]}
                  }
                }"""
            return ""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (32, 32), (245, 210, 220)).save(image_path)
            result = run_llm_expert_image_interrogator(str(image_path), chat_fn=fake_chat)

        self.assertEqual(len(calls), 5)
        self.assertFalse(any("最终合并器" in call for call in calls))
        self.assertEqual(result["expert_interrogate"]["review_retry_count"], 1)
        self.assertEqual(result["expert_interrogate"]["review_retry_expert_ids"], ["composition"])
        self.assertIn("通过 1/1 个专家", result["expert_interrogate"]["final_review"]["summary"])
        self.assertEqual(result["expert_interrogate"]["expert_batches"][0]["attempts"], 2)
        self.assertTrue(result["expert_interrogate"]["expert_batches"][0]["passed"])
        self.assertTrue(result["expert_interrogate"]["experts"][0]["review_retry"]["from_review"])
        self.assertIn("近距离低角度构图", result["prompt"])

    def test_run_llm_expert_image_interrogator_retries_missing_batched_expert_once(self):
        calls = []

        def fake_chat(messages, **kwargs):
            text = messages[1]["content"][0]["text"]
            calls.append(text)
            if "全局概览调度器" in text:
                return json.dumps(
                    {
                        "has_person": True,
                        "image_type": "人像",
                        "visible_elements": ["人物"],
                        "recommended_experts": ["composition", "body_pose", "clothing_makeup"],
                    },
                    ensure_ascii=False,
                )
            if "专家组批次任务" in text:
                return "## 构图镜头专家\n- 摘要: 近距离构图\n- 断言: 主体位于画面中心\n- 置信度: 0.8\n## 服装妆容专家\n- 摘要: 白色上衣\n- 断言: 主体穿白色上衣\n- 置信度: 0.8"
            if "复审专家已打回" in text and "专家代号: body_pose" in text:
                return "## 肢体动作专家\n- 摘要: 坐姿，手部位于身体前方\n- 断言: 人物为坐姿\n- 字段/支撑点: 臀部由床面支撑\n- 置信度: 0.82"
            if "accuracy_score = 属实断言数" in text:
                reviewed_ids = []
                for expert_id in ("composition", "body_pose", "clothing_makeup"):
                    if f'"id":"{expert_id}"' in text:
                        reviewed_ids.append(expert_id)
                return json.dumps(
                    {
                        "summary": "通过",
                        "retry_expert_ids": [],
                        "reviews": [
                            {
                                "id": expert_id,
                                "label": expert_id,
                                "passed": True,
                                "accuracy_score": 1.0,
                                "detail_score": 0.9,
                                "factual_score": 0.9,
                                "boundary_score": 0.9,
                                "claim_checks": [{"claim": "可见事实", "verdict": True, "reason": "图中可验证"}],
                                "missing": [],
                                "unsupported": [],
                                "retry_instruction": "",
                            }
                            for expert_id in reviewed_ids
                        ],
                    },
                    ensure_ascii=False,
                )
            return ""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (32, 32), (245, 210, 220)).save(image_path)
            result = run_llm_expert_image_interrogator(str(image_path), chat_fn=fake_chat)

        body = next(item for item in result["expert_interrogate"]["experts"] if item.get("id") == "body_pose")
        self.assertTrue(body["review_retry"]["from_review"])
        self.assertIn("坐姿", result["prompt"])
        self.assertTrue(any("批次输出缺少该专家内容" in json.dumps(call, ensure_ascii=False) for call in result["expert_interrogate"]["expert_batches"][1]["reviews"]))

    def test_build_image_interrogate_workflow_replaces_image_filename(self):
        workflow = build_image_interrogate_workflow("u1/2026-05-20/ref.png")

        self.assertEqual(workflow["1"]["class_type"], "LoadImage")
        self.assertEqual(workflow["1"]["inputs"]["image"], "u1/2026-05-20/ref.png")
        self.assertEqual(workflow["2"]["class_type"], "WD14Tagger|pysssss")
        self.assertEqual(workflow["5"]["class_type"], "Qwen3_VQA")
        self.assertEqual(workflow["4"]["class_type"], "ImageScaleToMaxDimension")
        self.assertEqual(workflow["4"]["inputs"]["largest_size"], 1024)
        self.assertNotIn("crop", workflow["4"]["inputs"])
        self.assertEqual(workflow["5"]["inputs"]["image"], ["4", 0])
        self.assertEqual(workflow["5"]["inputs"]["model"], "Qwen3-VL-4B-Instruct")
        self.assertEqual(workflow["5"]["inputs"]["quantization"], "4bit")
        self.assertIn("structured_prompt_en", workflow["5"]["inputs"]["text"])
        self.assertIn("foreground", workflow["5"]["inputs"]["text"])
        self.assertIn("background", workflow["5"]["inputs"]["text"])
        self.assertIn("描述场景，不要只堆关键词", workflow["5"]["inputs"]["text"])
        self.assertIn("身体可见范围", workflow["5"]["inputs"]["text"])
        self.assertIn("pose_details", workflow["5"]["inputs"]["text"])
        self.assertIn("hand_details", workflow["5"]["inputs"]["text"])
        self.assertIn("foot_details", workflow["5"]["inputs"]["text"])
        self.assertIn("joint_body_mechanics", workflow["5"]["inputs"]["text"])
        self.assertIn("facial_expression_details", workflow["5"]["inputs"]["text"])
        self.assertIn("occlusion_crop_details", workflow["5"]["inputs"]["text"])
        self.assertIn("intimate_body_details", workflow["5"]["inputs"]["text"])
        self.assertIn("sexual_act_details", workflow["5"]["inputs"]["text"])
        self.assertIn("genital_details", workflow["5"]["inputs"]["text"])
        self.assertIn("fluid_contact_details", workflow["5"]["inputs"]["text"])
        self.assertNotIn("content_safety_labels", workflow["5"]["inputs"]["text"])
        self.assertIn("exposed_body_details", workflow["5"]["inputs"]["text"])
        self.assertIn("nsfw_content_details", workflow["5"]["inputs"]["text"])
        self.assertIn("手部必须写清每只手", workflow["5"]["inputs"]["text"])
        self.assertIn("脚部只有进入画面时才写", workflow["5"]["inputs"]["text"])
        self.assertIn("关节和肢体受力", workflow["5"]["inputs"]["text"])
        self.assertIn("脸部细节和表情", workflow["5"]["inputs"]["text"])
        self.assertIn("不可见内容直接省略", workflow["5"]["inputs"]["text"])
        self.assertIn("不要把不可见脚写成“脚部细节不清晰”", workflow["5"]["inputs"]["text"])
        self.assertIn("不要把字段填成笼统的“不可见/无/不清晰”", workflow["5"]["inputs"]["text"])
        self.assertIn("近距离透视和前景肢体占比", workflow["5"]["inputs"]["text"])
        self.assertIn("不要把明显低角度仰拍或极近距离透视写成平视", workflow["5"]["inputs"]["text"])
        self.assertIn("看不到肩带不要写吊带", workflow["5"]["inputs"]["text"])
        self.assertIn("不能只写是否存在性行为", workflow["5"]["inputs"]["text"])
        self.assertIn("插入、摩擦、接触、自慰、口交、性交、手指进入", workflow["5"]["inputs"]["text"])
        self.assertIn("液体、分泌物、白色液体", workflow["5"]["inputs"]["text"])
        self.assertIn("不输出分类词、英文标签或内部判断词", workflow["5"]["inputs"]["text"])
        self.assertIn("成人裸露或性化", workflow["5"]["inputs"]["text"])
        self.assertIn("只写可见事实", workflow["5"]["inputs"]["text"])
        self.assertIn("禁止用“尺度较大、性感、诱人、青春可爱”等主观词", workflow["5"]["inputs"]["text"])
        self.assertIn("人物动作和姿势必须拆解", workflow["5"]["inputs"]["text"])
        self.assertIn("坐姿不能只写“坐在xxx”", workflow["5"]["inputs"]["text"])
        self.assertIn("正坐、侧坐、半跪坐、跪坐、蹲坐、盘腿坐、跨坐、倚坐", workflow["5"]["inputs"]["text"])
        self.assertIn("人物跪坐在车厢前排座椅上，面部朝向镜头，躯干转向座椅靠背方向", workflow["5"]["inputs"]["text"])
        self.assertIn("车内前排人物姿态标准样例", workflow["5"]["inputs"]["text"])
        self.assertIn("白色贴身短袖衬衫", workflow["5"]["inputs"]["text"])
        self.assertIn("深红色百褶短裙", workflow["5"]["inputs"]["text"])
        self.assertIn("黑色过膝丝袜", workflow["5"]["inputs"]["text"])
        self.assertIn("画面右侧可见方向盘和车门区域，但不能写手搭方向盘", workflow["5"]["inputs"]["text"])
        self.assertIn("绝不能写“全身、脚踝、脚部可见”", workflow["5"]["inputs"]["text"])
        self.assertIn("可见外貌特征、肤色和年龄感", workflow["5"]["inputs"]["text"])
        self.assertIn("方向和相对位置必须以画面坐标描述", workflow["5"]["inputs"]["text"])
        self.assertIn("前/后/左/右/向前”不是绝对方向", workflow["5"]["inputs"]["text"])
        self.assertIn("先画面外围再中心", workflow["5"]["inputs"]["text"])
        self.assertIn("左上角、右上角、左下角、右下角", workflow["5"]["inputs"]["text"])
        self.assertIn("手臂向座椅靠背方向延伸到画面边缘", workflow["5"]["inputs"]["text"])
        self.assertIn("不要删除没有参照物的动作信息", workflow["5"]["inputs"]["text"])
        self.assertIn("车内有方向盘不等于手搭方向盘", workflow["5"]["inputs"]["text"])
        self.assertIn("不明确时写“车厢前排区域”", workflow["5"]["inputs"]["text"])
        self.assertIn("只有看到农作物行列、田埂或农田结构时", workflow["5"]["inputs"]["text"])
        self.assertIn("袜类必须拆分“长度款式”和“材质透明度”", workflow["5"]["inputs"]["text"])
        self.assertIn("黑色过膝丝袜", workflow["5"]["inputs"]["text"])
        self.assertIn("不要把“疑似/可能/隐约”写进最终正向提示词", workflow["5"]["inputs"]["text"])
        self.assertIn("暴露皮肤、裸露身体、内衣泳装", workflow["5"]["inputs"]["text"])
        self.assertIn("服装领口/袖型/长度/贴合度", workflow["5"]["inputs"]["text"])
        self.assertIn("如果人物从头部到腿部大范围可见，绝不能写成特写", workflow["5"]["inputs"]["text"])
        self.assertIn("不要笼统写室内", workflow["5"]["inputs"]["text"])
        self.assertIn("important_details 需要尽量列出 14 到 30 条", workflow["5"]["inputs"]["text"])
        self.assertIn("必须包含以下四个顶层键", workflow["5"]["inputs"]["text"])
        self.assertEqual(workflow["5"]["inputs"]["max_new_tokens"], 3072)
        self.assertTrue(workflow["5"]["inputs"]["keep_model_loaded"])
        self.assertEqual(workflow["6"]["class_type"], "ShowText|pysssss")

    def test_staged_expert_interrogator_uses_global_overview_to_limit_experts(self):
        calls = []
        selected = ["composition", "photography_parameters", "color_light", "mood_style", "materials_texture"]

        def fake_chat(messages, **kwargs):
            text = messages[1]["content"][0]["text"]
            calls.append(text)
            if "全局概览调度器" in text:
                return json.dumps(
                    {
                        "has_person": False,
                        "image_type": "产品",
                        "visible_elements": ["白色陶瓷杯", "木质桌面", "窗边自然光"],
                        "recommended_experts": selected,
                        "reason": "无人物主体，只需要物体复刻专家",
                    },
                    ensure_ascii=False,
                )
            if "最终合并器" in text:
                return """{
                  "keyword_prompt": "白色陶瓷杯放在木质桌面，窗边自然光，浅景深",
                  "structured_prompt": {
                    "画面描述": {
                      "构图镜头": {"构图": "桌面静物中近景"},
                      "材质纹理": {"材质": "白色陶瓷光滑高光，木桌细密纹理"}
                    },
                    "负面提示词": {"质量错误": ["水印"]}
                  }
                }"""
            if "accuracy_score = 属实断言数" in text:
                reviewed_expert_ids = [item for item in selected if f'"id":"{item}"' in text] or [selected[0]]
                return json.dumps(
                    {
                        "summary": "产品专家结论属实",
                        "retry_expert_ids": [],
                        "reviews": [
                            {
                                "id": reviewed_expert_id,
                                "label": reviewed_expert_id,
                                "passed": True,
                                "accuracy_score": 1.0,
                                "detail_score": 0.85,
                                "factual_score": 0.9,
                                "boundary_score": 0.9,
                                "claim_checks": [{"claim": "可见事实", "verdict": True, "reason": "图中可验证"}],
                                "missing": [],
                                "unsupported": [],
                                "retry_instruction": "",
                            }
                            for reviewed_expert_id in reviewed_expert_ids
                        ],
                    },
                    ensure_ascii=False,
                )
            expert_id = ""
            for item in selected:
                if f"专家代号: {item}" in text:
                    expert_id = item
                    break
            if "专家组批次任务" in text:
                parts = []
                for item in selected:
                    if f"专家代号: {item}" not in text:
                        continue
                    if item == "composition":
                        parts.append("## composition\n- 摘要: 白色陶瓷杯放在木质桌面\n- 断言: 白色陶瓷杯位于桌面主体位置\n- 字段/构图: 桌面静物中近景\n- 置信度: 0.8")
                    elif item == "materials_texture":
                        parts.append("## materials_texture\n- 摘要: 白色陶瓷光滑高光，木桌细密纹理\n- 断言: 桌面有木质纹理\n- 字段/材质: 白色陶瓷光滑高光，木桌细密纹理\n- 置信度: 0.8")
                    else:
                        parts.append(f"## {item}\n- 摘要: 可见事实\n- 断言: 可见事实\n- 字段/观察: 可见事实\n- 置信度: 0.8")
                return "\n".join(parts)
            if expert_id == "composition":
                return "## composition\n- 摘要: 白色陶瓷杯放在木质桌面\n- 断言: 白色陶瓷杯位于桌面主体位置\n- 字段/构图: 桌面静物中近景\n- 置信度: 0.8"
            if expert_id == "materials_texture":
                return "## materials_texture\n- 摘要: 白色陶瓷光滑高光，木桌细密纹理\n- 断言: 桌面有木质纹理\n- 字段/材质: 白色陶瓷光滑高光，木桌细密纹理\n- 置信度: 0.8"
            return f"## {expert_id}\n- 摘要: 可见事实\n- 断言: 可见事实\n- 字段/观察: 可见事实\n- 置信度: 0.8"

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "product.png"
            from PIL import Image

            Image.new("RGB", (640, 640), (235, 230, 220)).save(image_path)
            result = run_llm_expert_image_interrogator(str(image_path), chat_fn=fake_chat)

        self.assertEqual(result["expert_interrogate"]["expected_expert_count"], len(selected))
        self.assertEqual(result["expert_interrogate"]["selected_experts"], selected)
        self.assertFalse(any("专家代号: body_pose" in call for call in calls))
        self.assertFalse(any("专家代号: expression_language" in call for call in calls))
        self.assertIn("白色陶瓷杯", result["prompt"])

    def test_expert_prompts_require_face_makeup_and_photography_parameters(self):
        expert_ids = {spec["id"] for spec in IMAGE_INTERROGATE_EXPERTS}

        self.assertIn("photography_parameters", expert_ids)
        self.assertIn("评审专家", EXPERT_IMAGE_REVIEW_TEMPLATE)
        self.assertIn("retry_expert_ids", EXPERT_IMAGE_REVIEW_TEMPLATE)
        self.assertIn("accuracy_score", EXPERT_IMAGE_REVIEW_TEMPLATE)
        self.assertIn("claim_checks", EXPERT_IMAGE_REVIEW_TEMPLATE)
        self.assertIn("accuracy_score >= 0.90", EXPERT_IMAGE_REVIEW_TEMPLATE)
        self.assertIn("detail_score", EXPERT_IMAGE_REVIEW_TEMPLATE)
        self.assertIn("请不要生成图片", FAST_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("高精度视觉规格书", FAST_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("画面总体概述、构图与镜头、主体与空间关系", FAST_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("A. 结构化视觉规格书", FAST_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("B. 一段完整图像生成提示词", FAST_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("C. 一段负面约束", FAST_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("顶层键固定为 visual_spec, keyword_prompt, negative_prompt", FAST_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("专家反推定位：1:1 复刻精度", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("可执行的复刻参数", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("高成功率提示词规格书", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(HIGH_SUCCESS_PROMPT_SPEC_GUIDE, FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("反推闭环技能", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("visual_evidence 是内部证据表", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("allow_positive=true", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("confidence>=0.75", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("foot_or_shoe_contact", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("复刻成功率目标为 95 分", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("任务目标、保真要求、主体、动作姿态、场景、构图镜头、光线色彩、材质细节、风格媒介、文字版式、负向限制", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("The positive prompt is the main control surface", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不要输出复刻约束维度", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("五官细节", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("脸部妆造", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("参考光圈", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("快门、ISO", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("ISO 400", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不代表真实 EXIF", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("f/2.8-f/4 是大光圈或中大光圈", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("最终提示词不要出现“推断", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("参考参数：35mm，f/2.8，1/125s，ISO 400", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("袜子/丝袜/内衣", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("肩带/罩杯/钢圈", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不要把丝袜误写成裸腿", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("近似 HEX 色值", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("色温", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("颗粒度", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("人物肤色、可见外貌倾向", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("腿部可见起止边界", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("坐姿不得只写“坐在xxx”", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("人物跪坐在车厢前排座椅上，面部朝向镜头，躯干转向座椅靠背方向", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(CAR_FRONT_SEAT_POSE_STANDARD, FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(BEDROOM_SEATED_POSE_STANDARD, FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("前景手部因运动或焦外呈模糊", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不得写双臂自然垂落、裁切到大腿中部、adult_nudity", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("车内有方向盘不等于手搭方向盘", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(SCENE_OBJECT_VERIFICATION_STANDARD, FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(SCENE_OBJECT_VERIFICATION_STANDARD, EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(SCENE_OBJECT_VERIFICATION_STANDARD, EXPERT_IMAGE_REVIEW_TEMPLATE)
        self.assertIn(SCENE_OBJECT_VERIFICATION_STANDARD, EXPERT_IMAGE_MERGE_TEMPLATE)
        self.assertIn("塑料瓶不得评审通过为易拉罐", EXPERT_IMAGE_REVIEW_TEMPLATE)
        self.assertIn("不能把红色塑料瓶合并成易拉罐", EXPERT_IMAGE_MERGE_TEMPLATE)
        self.assertIn("前/后/左/右/向前必须写明参照物", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("画面外围到中心", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不要剔除动作", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("向座椅靠背", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不能写包含脚踝、脚部或全身", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("禁止输出“双腿并拢或轻微分开”", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("蹲姿，鞋底踩在碎石地面承重", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("禁止写“半蹲坐姿 (Half-crouching Sit)”", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("双膝和小腿接触于前景岩石表面", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不得写“小腿和脚踝区域被黑色丝袜包裹”", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("手靠近画面右侧太阳穴/发丝", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不要强行写人物左手/右手或“头部左上方发梢”", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不明确时写车厢前排区域", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不要自动写远处田野/农田", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("闭唇表情默认写平静闭唇", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("黑色过膝袜不能直接替代黑色丝袜", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("黑色过膝丝袜", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("看不清就省略具体款式", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)

    def test_runtime_expert_prompt_keeps_detail_standards_with_bounded_size(self):
        self.assertLess(len(RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE), 11000)
        self.assertIn("visual_evidence 是内部证据简表", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("请把当前图片拆解成一份适合图像生成模型使用的高精度视觉描述", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("visual_spec 等同结构化视觉规格书", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("keyword_prompt 必须是一段可直接给图像生成模型使用的纯词汇", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(DIRECT_REVERSE_PROMPT_WRITING_SKILL, RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(REVERSE_MODE_PRECISION_STANDARD, RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(EXPERT_REVERSE_DEEP_SCHEMA, RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("图片拆解七层法", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("视觉施工图", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("foot_or_shoe_contact", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("visual_spec 必须按用户指定的 A.结构化视觉规格书章节组织", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("当前图片必须独立分析", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertNotIn("visual_spec 归档 基本概述、前景、主体、背景、整体画面", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("primary_subject", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("subject_type", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("非人物主体不要输出这些字段", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(BODY_STRUCTURE_REQUIRED_FIELDS, RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("各维度字段必须互补", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不要互相复述整段", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("车内有方向盘不能自动写手搭方向盘", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("黑色过膝丝袜", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不写推断/估计", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertNotIn(HIGH_SUCCESS_PROMPT_SPEC_GUIDE, RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)

    def test_front_reverse_rules_define_three_modes_and_seven_layers(self):
        self.assertTrue(RULES_DIR.is_dir())
        self.assertEqual(len(RULE_CATEGORY_FILES), 7)
        self.assertIn("02 人物与躯干关节", IMAGE_REVERSE_RULEBOOK)
        self.assertIn("05 暴露内容与 NSFW 细节", IMAGE_REVERSE_RULEBOOK)
        self.assertIn("规则来源", IMAGE_REVERSE_RUNTIME_RULE_INDEX)
        self.assertIn(IMAGE_REVERSE_RUNTIME_RULE_INDEX, FAST_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(IMAGE_REVERSE_RUNTIME_RULE_INDEX, RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(IMAGE_REVERSE_RUNTIME_RULE_INDEX, RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn(IMAGE_REVERSE_RUNTIME_RULE_INDEX, EXPERT_TEAM_GLOBAL_PASS_TEMPLATE)
        self.assertIn(IMAGE_REVERSE_RUNTIME_RULE_INDEX, EXPERT_TEAM_SUBJECT_PASS_TEMPLATE)
        self.assertIn(IMAGE_REVERSE_RUNTIME_RULE_INDEX, EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("不要写感觉，要写可见事实", DIRECT_REVERSE_PROMPT_WRITING_SKILL)
        self.assertIn("图片拆解七层法", DIRECT_REVERSE_PROMPT_WRITING_SKILL)
        self.assertIn("画面主题", DIRECT_REVERSE_PROMPT_WRITING_SKILL)
        self.assertIn("构图与镜头", DIRECT_REVERSE_PROMPT_WRITING_SKILL)
        self.assertIn("空间位置关系", DIRECT_REVERSE_PROMPT_WRITING_SKILL)
        self.assertIn("必须设置复刻优先级", DIRECT_REVERSE_PROMPT_WRITING_SKILL)
        self.assertIn("标准反推", REVERSE_MODE_PRECISION_STANDARD)
        self.assertIn("专家反推", REVERSE_MODE_PRECISION_STANDARD)
        self.assertIn("专家团反推", REVERSE_MODE_PRECISION_STANDARD)
        self.assertIn("七层视觉规格", STANDARD_REVERSE_SEVEN_LAYER_SCHEMA)
        self.assertIn("1:1 复刻规格", EXPERT_REVERSE_DEEP_SCHEMA)
        self.assertIn("专家团总观察员第一眼看图任务", EXPERT_TEAM_SELF_ASSEMBLY_STANDARD)
        self.assertIn("expert_plan", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("自行生成最符合该图的专家组", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("主体类型门控", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("非人物主体不要输出人体骨架字段", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("非人物主体不要分配人体专家", EXPERT_TEAM_GLOBAL_PASS_TEMPLATE)
        self.assertIn("先读取第1轮 subject_type", EXPERT_TEAM_SUBJECT_PASS_TEMPLATE)

    def test_expert_result_text_is_clamped_to_100_chars(self):
        item = {
            "id": "body_pose",
            "label": "肢体动作专家",
            "summary": "人物坐在床铺上，躯干正对镜头略微前倾，画面左侧手臂向镜头前方抬起，前景手部焦外模糊，画面右侧手臂下垂靠近床面",
            "fields": {
                "姿势": "人物坐在床铺上，躯干正对镜头略微前倾，肩膀放松，腰部自然弯曲，腿部向画面下方延伸",
                "手部": "画面左侧手臂向镜头前方抬起，手部位于前景并明显焦外模糊，画面右侧手臂下垂靠近床面",
            },
            "observations": ["腿部裁切到膝部附近，白色长筒袜上缘可见", "身体重心落在床面"],
        }

        unclamped = _clamp_expert_result_text(item)
        self.assertEqual(unclamped["fields"]["姿势"], item["fields"]["姿势"])

        clamped = _clamp_expert_result_text(item, max_chars=100)
        total = len(clamped["summary"])
        total += sum(len(str(value)) for value in clamped["fields"].values())
        total += sum(len(str(value)) for value in clamped["observations"])

        self.assertLessEqual(total, 100)
        self.assertIn("…", json.dumps(clamped, ensure_ascii=False))

    def test_expert_prompt_uses_chinese_and_boundary_limited_opinions(self):
        self.assertIn("必须统一使用中文输出", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("临时专家属性", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("专家报告 Markdown 规范手册", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("只返回 Markdown，不要 JSON", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("断言必须能被评审专家直接判定", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("前肢离开地面", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("后肢向后伸展并承担发力动作", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("只能描述本专业范围内", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不限制固定字数", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("必填角度", EXPERT_IMAGE_REVIEW_TEMPLATE)
        self.assertIn("是否有某物/动作", EXPERT_IMAGE_REVIEW_TEMPLATE)
        expert_text = json.dumps(IMAGE_INTERROGATE_EXPERTS, ensure_ascii=False)
        self.assertIn("手臂端点", expert_text)
        self.assertIn("腿部起止边界", expert_text)
        self.assertIn("可见乳头", expert_text)
        self.assertIn("可见性器官", expert_text)
        self.assertIn("内衣/文胸/内裤只能", expert_text)
        self.assertIn("下装类型", expert_text)
        batch_prompt = _build_expert_batch_prompt([next(spec for spec in IMAGE_INTERROGATE_EXPERTS if spec["id"] == "body_pose")])
        self.assertIn("空间控图标准", batch_prompt)
        self.assertIn("自然九宫格", batch_prompt)
        self.assertIn("左上、上中、右上", batch_prompt)
        self.assertIn("时钟方向", batch_prompt)
        self.assertIn("每个对象字段必须内嵌自然坐标", batch_prompt)
        self.assertNotIn("\n- 字段/空间坐标", batch_prompt)
        self.assertIn("字段/末梢节点", batch_prompt)
        self.assertIn("末梢节点标准", batch_prompt)
        self.assertIn("头部描述示例", batch_prompt)
        self.assertIn("人物专家视觉规格协议", batch_prompt)
        self.assertIn("头部姿态必须拆成三轴", batch_prompt)
        self.assertIn("脸朝向、眼睛视线、身体朝向分开写", batch_prompt)
        self.assertIn("上臂位置、肘部弯曲角度、前臂延伸方向", batch_prompt)
        composition_batch = _build_expert_batch_prompt([next(spec for spec in IMAGE_INTERROGATE_EXPERTS if spec["id"] == "composition")])
        self.assertNotIn("人物专家视觉规格协议", composition_batch)
        self.assertIn("下巴贴紧右肩", batch_prompt)
        self.assertIn("缺少可进入最终提示词的自然画面坐标", _local_expert_detail_failure(
            {"id": "body_pose", "label": "肢体动作专家"},
            {"summary": "人物坐在金属架上，腿部透视强烈", "fields": {}, "observations": []},
        ))
        self.assertEqual("", _local_expert_detail_failure(
            {"id": "expression_language", "label": "表情语言专家"},
            {"summary": "头部位于画面右上，脸向画面右侧扭转，鼻尖指向肩部，下巴贴肩，视线向右下，发丝贴近脸颊", "fields": {}, "observations": []},
        ))

    def test_extract_json_object_uses_first_complete_object_before_garbage_tail(self):
        parsed = _extract_json_object('{"visual_evidence":{"aspect_ratio":"9:16"},"keyword_prompt":"abc"}\\n}\\n}\\n}')

        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["visual_evidence"]["aspect_ratio"], "9:16")

    def test_global_overview_routes_person_images_to_person_experts(self):
        overview = {
            "has_person": True,
            "global_summary": "车内前排人物，白衬衫红裙，黑色过膝丝袜，人物跪坐在座椅上",
            "visible_elements": ["人物", "汽车内饰", "车窗草地"],
        }

        experts = _select_experts_from_global_overview(overview)

        self.assertIn("body_pose", experts)
        self.assertIn("expression_language", experts)
        self.assertIn("clothing_makeup", experts)
        self.assertIn("sexual_boundary", experts)
        self.assertIn("composition", experts)

    def test_global_overview_routes_non_person_images_to_object_scene_experts(self):
        overview = {
            "has_person": False,
            "global_summary": "桌面产品静物，金属设备和玻璃杯，室内自然光",
            "visible_elements": ["桌面", "金属设备", "玻璃杯"],
        }

        experts = _select_experts_from_global_overview(overview)

        self.assertIn("composition", experts)
        self.assertIn("photography_parameters", experts)
        self.assertIn("materials_texture", experts)
        self.assertIn("color_light", experts)
        self.assertNotIn("expression_language", experts)

    def test_markdown_expert_observation_is_parsed_without_dimension_clamp(self):
        spec = {"id": "body_pose", "label": "肢体动作专家"}
        markdown = """
        ## 肢体动作专家
        姿势：人物蹲在碎石海岸，鞋底踩地承重，膝盖弯曲靠近身体，躯干向镜头轻微前倾。
        断言：鞋底踩地承重。
        手部：画面右侧手靠近头发，画面左侧手臂贴近身体。
        腿部：黑色过膝丝袜覆盖膝上到鞋口区域，黑色厚底运动鞋接触碎石。
        不确定：画面左右手身份不可靠。
        负面：膝盖支撑地面、1:1正方形
        置信度：0.91
        """

        result = _expert_observation_from_markdown(markdown, spec)
        total = len(result["summary"])
        total += sum(len(str(value)) for value in result["fields"].values())
        total += sum(len(str(value)) for value in result["observations"])

        self.assertEqual(result["id"], "body_pose")
        self.assertIn("姿势", result["fields"])
        self.assertIn("鞋底踩地承重", "，".join(result["observations"]))
        self.assertIn("画面左右手身份不可靠", "，".join(result["uncertain"]))
        self.assertAlmostEqual(result["confidence"], 0.91)
        self.assertEqual(result["format"], "markdown")
        self.assertIn("膝盖支撑地面", result["negative_constraints"])
        self.assertGreater(total, 100)

    def test_loose_visual_evidence_list_is_normalized_for_quality_gate(self):
        loose = [
            {
                "value": {
                    "aspect_ratio": "9:16",
                    "visible_body_range": "头部到膝部",
                    "support_points": ["坐在床面"],
                    "hand_endpoints": ["画面左侧手部靠近镜头"],
                    "foot_or_shoe_contact": "画面裁切到膝部，鞋子未入镜",
                    "clothing_materials": ["白色蕾丝吊带", "浅色抽绳短裤"],
                    "visible_text_confidence": 0.0,
                    "nsfw_visible_evidence": "低领和乳沟可见，未见乳头或性器官",
                    "foreground_background_regions": ["前景模糊手部", "背景床铺和窗帘"],
                },
                "evidence": "模型宽松证据汇总",
                "confidence": 0.86,
                "allow_positive": True,
            }
        ]

        normalized = _normalize_visual_evidence(loose)

        self.assertIsInstance(normalized, dict)
        self.assertEqual(normalized["aspect_ratio"]["value"], "9:16")
        self.assertEqual(normalized["hand_endpoints"]["value"], ["画面左侧手部靠近镜头"])
        self.assertGreaterEqual(normalized["support_points"]["confidence"], 0.86)

    def test_visual_evidence_backfills_missing_sexual_boundary_expert(self):
        experts = [{"id": "body_pose", "label": "肢体动作专家", "summary": "坐姿", "observations": ["坐姿"], "fields": {}, "confidence": 0.8}]
        evidence = {
            "nsfw_visible_evidence": {
                "value": "低领和乳沟可见，未见乳头或性器官",
                "evidence": "胸口衣物边界",
                "confidence": 0.9,
                "allow_positive": True,
            }
        }

        backfilled = _backfill_expert_results_from_visual_evidence(experts, evidence)

        sexual = [item for item in backfilled if item.get("id") == "sexual_boundary"]
        self.assertEqual(len(sexual), 1)
        self.assertFalse(sexual[0].get("missing"))
        self.assertIn("低领和乳沟可见", sexual[0]["summary"])
        body_pose = next(spec for spec in IMAGE_INTERROGATE_EXPERTS if spec["id"] == "body_pose")
        self.assertIn("正坐、侧坐、半跪坐", body_pose["instruction"])
        self.assertIn("真实接触身体或物体", body_pose["instruction"])
        self.assertIn("双腿并拢或轻微分开", body_pose["instruction"])
        self.assertIn("方向词必须有参照系", body_pose["instruction"])
        self.assertIn("不要删除无参照动作", body_pose["instruction"])
        self.assertIn("面部朝镜头，躯干朝座椅靠背", body_pose["instruction"])
        self.assertIn("人物跪坐在车厢前排座椅上，面部朝向镜头，躯干转向座椅靠背方向", body_pose["instruction"])
        self.assertIn(CAR_FRONT_SEAT_POSE_STANDARD, body_pose["instruction"])
        self.assertIn("跪坐或半跪坐", body_pose["instruction"])
        self.assertIn("人物下蹲/蹲姿，鞋底踩在地面承重", body_pose["instruction"])
        self.assertIn("禁止写“半蹲坐姿 (Half-crouching Sit)”", body_pose["instruction"])
        self.assertIn("不得写“小腿和脚踝区域被丝袜包裹”", body_pose["instruction"])
        self.assertIn("画面右侧手臂弯曲抬起", body_pose["instruction"])
        composition = next(spec for spec in IMAGE_INTERROGATE_EXPERTS if spec["id"] == "composition")
        self.assertIn("不能写包含脚踝或全身", composition["instruction"])
        self.assertIn("窗外绿色不能自动写成田野/农田", composition["instruction"])
        clothing = next(spec for spec in IMAGE_INTERROGATE_EXPERTS if spec["id"] == "clothing_makeup")
        self.assertIn("长度款式和材质本质", clothing["instruction"])
        self.assertIn("复合词", clothing["instruction"])
        self.assertIn("黑色过膝丝袜", clothing["instruction"])
        self.assertIn("不能把黑色过膝袜直接等同于黑色丝袜", clothing["instruction"])
        expression = next(spec for spec in IMAGE_INTERROGATE_EXPERTS if spec["id"] == "expression_language")
        self.assertIn("可见外貌倾向、肤色", expression["instruction"])
        self.assertIn("嘴唇闭合且嘴角不明显时写平静闭唇", expression["instruction"])
        self.assertIn("发型发色", expression["instruction"])
        self.assertIn("染发信息", expression["instruction"])
        self.assertIn("染发风格", expression["instruction"])
        self.assertIn("发饰", expression["instruction"])
        self.assertIn("发尾染", HAIR_APPEARANCE_STANDARD)
        body_pose = next(spec for spec in IMAGE_INTERROGATE_EXPERTS if spec["id"] == "body_pose")
        self.assertIn("人物自身朝向角度", body_pose["instruction"])
        self.assertIn("肩线角度", CAMERA_AND_BODY_ANGLE_STANDARD)
        self.assertIn("胯部角度", CAMERA_AND_BODY_ANGLE_STANDARD)
        self.assertIn("躯干向画面左侧转约 30 度", CAMERA_AND_BODY_ANGLE_STANDARD)
        self.assertIn("画面顺时针/逆时针倾斜", CAMERA_AND_BODY_ANGLE_STANDARD)
        self.assertIn("相机向上仰拍或向下俯拍", CAMERA_AND_BODY_ANGLE_STANDARD)
        self.assertIn("躯干弯折幅度", TRUNK_HAND_OBJECT_ANGLE_STANDARD)
        self.assertIn("骨盆到腰线、胸腔、肩线、头颈", TRUNK_HAND_OBJECT_ANGLE_STANDARD)
        self.assertIn("左右手必须分开写", TRUNK_HAND_OBJECT_ANGLE_STANDARD)
        self.assertIn("手持物体位置", TRUNK_HAND_OBJECT_ANGLE_STANDARD)
        self.assertIn("采光入射角", LIGHT_INCIDENCE_ANGLE_STANDARD)
        self.assertIn("阴影投射方向", LIGHT_INCIDENCE_ANGLE_STANDARD)
        self.assertIn("yaw", HUMAN_POSE_EXPERT_STANDARD)
        self.assertIn("pitch", HUMAN_POSE_EXPERT_STANDARD)
        self.assertIn("roll", HUMAN_POSE_EXPERT_STANDARD)
        self.assertIn("脸部朝向、眼睛视线和头部倾斜必须分开写", HUMAN_POSE_EXPERT_STANDARD)
        self.assertIn("胸腔朝向、骨盆朝向", HUMAN_POSE_EXPERT_STANDARD)
        self.assertIn("躯干弯折必须写幅度、方向和趋势", HUMAN_POSE_EXPERT_STANDARD)
        self.assertIn("肩线左高右低", HUMAN_POSE_EXPERT_STANDARD)
        self.assertIn("上臂-肘-前臂-手腕-手指", HUMAN_POSE_EXPERT_STANDARD)
        self.assertIn("头顶、下巴、左肩、右肩", HUMAN_POSE_EXPERT_STANDARD)
        self.assertIn("OpenPose", HUMAN_POSE_EXPERT_STANDARD)
        self.assertIn("肘部是必填中间节点", ARM_ELBOW_CHAIN_STANDARD)
        self.assertIn("肩-上臂-肘-前臂-腕-掌-指", BODY_JOINT_CHAIN_COMPLETENESS_STANDARD)
        self.assertIn("髋-大腿-膝-小腿-踝", BODY_JOINT_CHAIN_COMPLETENESS_STANDARD)
        self.assertIn("肩线、胸腔朝向、肋骨/上身倾斜、腰线、骨盆朝向、胯线、脊柱线", BODY_JOINT_CHAIN_COMPLETENESS_STANDARD)
        self.assertIn(HUMAN_POSE_EXPERT_STANDARD, body_pose["instruction"])
        self.assertIn(TRUNK_HAND_OBJECT_ANGLE_STANDARD, body_pose["instruction"])
        composition = next(spec for spec in IMAGE_INTERROGATE_EXPERTS if spec["id"] == "composition")
        color_light = next(spec for spec in IMAGE_INTERROGATE_EXPERTS if spec["id"] == "color_light")
        photography = next(spec for spec in IMAGE_INTERROGATE_EXPERTS if spec["id"] == "photography_parameters")
        self.assertIn(LIGHT_INCIDENCE_ANGLE_STANDARD, composition["instruction"])
        self.assertIn(LIGHT_INCIDENCE_ANGLE_STANDARD, color_light["instruction"])
        self.assertIn(LIGHT_INCIDENCE_ANGLE_STANDARD, photography["instruction"])
        self.assertIn(ARM_ELBOW_CHAIN_STANDARD, body_pose["instruction"])
        self.assertIn(BODY_JOINT_CHAIN_COMPLETENESS_STANDARD, body_pose["instruction"])
        self.assertIn(HUMAN_POSE_EXPERT_STANDARD, expression["instruction"])

    def test_positive_prompt_cleaner_keeps_action_while_removing_ambiguous_alternatives(self):
        cleaned = _clean_positive_prompt_text(
            "双腿并拢或轻微分开，膝盖弯曲，穿着黑色过膝袜，短裙或短裤疑似，参考大光圈或中大光圈，手臂向前伸展，手臂向座椅靠背方向延伸到画面边缘"
        )

        self.assertNotIn("双腿并拢或轻微分开", cleaned)
        self.assertNotIn("短裙或短裤疑似", cleaned)
        self.assertIn("手臂向前伸展", cleaned)
        self.assertIn("膝盖弯曲", cleaned)
        self.assertIn("穿着黑色过膝袜", cleaned)
        self.assertIn("参考大光圈或中大光圈", cleaned)
        self.assertIn("手臂向座椅靠背方向延伸到画面边缘", cleaned)

    def test_single_pass_expert_result_falls_back_to_json_when_model_omits_structured_prompt(self):
        def fake_chat(messages, **kwargs):
            text = messages[1]["content"][0]["text"]
            self.assertIn(RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE, text)
            self.assertNotIn(HIGH_SUCCESS_PROMPT_SPEC_GUIDE, text)
            self.assertEqual(kwargs.get("max_tokens"), EXPERT_INTERROGATE_MAX_TOKENS)
            return """{
              "keyword_prompt": "人物肖像，浅景深，参考参数：35mm，f/2.8，1/125s，ISO 400，浅樱粉 #F6C9D6 上衣",
              "expert_observations": [
                {
                  "id": "photography_parameters",
                  "label": "摄影参数专家",
                  "summary": "参考参数：35mm，f/2.8，1/125s，ISO 400，浅景深",
                  "fields": {"参考参数": "35mm，f/2.8，1/125s，ISO 400，浅景深"},
                  "observations": ["背景虚化，浅景深"],
                  "negative_constraints": ["过暗曝光"],
                  "confidence": 0.8
                }
              ]
            }"""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (32, 32), (246, 201, 214)).save(image_path)
            result = run_llm_expert_image_interrogator(str(image_path), chat_fn=fake_chat, single_pass=True)

        experts = result["expert_interrogate"]["experts"]
        self.assertEqual(len(experts), len(IMAGE_INTERROGATE_EXPERTS))
        self.assertEqual(
            [item["id"] for item in experts],
            [spec["id"] for spec in IMAGE_INTERROGATE_EXPERTS],
        )
        self.assertTrue(any(item.get("missing") for item in experts))
        self.assertIn('"画面描述": {', result["structured_prompt_json"])
        self.assertIn('"整体画面": "35mm', result["structured_prompt_json"])
        self.assertNotIn('"摄影参数": {', result["structured_prompt_json"])
        self.assertIn("f/2.8", result["structured_prompt_json"])
        self.assertIn("过暗曝光", result["negative_prompt"])
        self.assertNotIn('"负面提示词"', result["structured_prompt_json"])
        self.assertNotIn("推断", result["structured_prompt_json"])
        self.assertNotIn("模型未返回该专家维度", result["structured_prompt_json"])

    def test_single_pass_expert_drops_replication_constraints_dimension(self):
        def fake_chat(messages, **kwargs):
            return """{
              "visual_evidence": {
                "aspect_ratio": "9:16",
                "visible_body_range": "头部到膝部",
                "support_points": ["坐在床面"],
                "hand_endpoints": ["手部在画面中部"],
                "foot_or_shoe_contact": "画面裁切到膝部",
                "clothing_materials": ["浅色上衣"],
                "visible_text_confidence": 0,
                "nsfw_visible_evidence": "日常衣物",
                "foreground_background_regions": ["前景人物", "背景床铺"]
              },
              "detailed_analysis": {
                "主体外貌": {"人物": "人物坐在床面，面部朝向镜头"},
                "构图镜头": {"画幅": "9:16 竖幅"},
                "复刻约束": {"约束": "保持相同人物、相同构图和相同姿态"}
              },
              "keyword_prompt": "人物坐在床面，9:16 竖幅，面部朝向镜头",
              "negative_prompt": ["水印"]
            }"""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (768, 1280), (240, 230, 220)).save(image_path)
            result = run_llm_expert_image_interrogator(str(image_path), chat_fn=fake_chat, single_pass=True)

        self.assertNotIn("复刻约束", result["structured_prompt"]["画面描述"])
        self.assertNotIn("复刻约束", result["structured_prompt_json"])
        self.assertIn("主体", result["structured_prompt"]["画面描述"])

    def test_prompt_from_structured_json_extracts_all_richer_sections(self):
        structured = {
            "画面描述": {
                "主体": {
                    "主体外貌": "长直黑发人物，齐刘海，肤色暖白",
                    "肢体动作": "坐在床面，躯干正对镜头略微前倾",
                    "服装妆容": "白色蕾丝吊带，浅色抽绳短裤",
                    "裸露与NSFW": "锁骨、上胸和大腿皮肤可见，上衣覆盖胸部",
                },
                "背景": {"场景背景": "背景为床铺和窗帘"},
                "整体画面": {"构图镜头": "9:16 竖幅中近景", "摄影参数": "35mm，f/2.8，浅景深"},
            }
        }

        prompt = _prompt_from_structured_json(structured, "卧室人像")

        self.assertIn("长直黑发人物", prompt)
        self.assertIn("白色蕾丝吊带", prompt)
        self.assertIn("锁骨、上胸和大腿皮肤可见", prompt)
        self.assertIn("35mm", prompt)
        self.assertNotEqual(prompt, "卧室人像")

    def test_prompt_from_structured_json_rewrites_grid_codes_to_natural_regions(self):
        structured = {
            "画面描述": {
                "主体": {
                    "肢体动作": "人物位于bb到cb的床面中景，画面左侧前景手部位于ba并靠近镜头近端",
                },
                "整体画面": {"构图镜头": "9:16 竖幅中近景"},
            }
        }

        prompt = _prompt_from_structured_json(structured, "卧室人像")

        self.assertIn("人物位于中心到下中的床面中景", prompt)
        self.assertIn("画面左侧前景手部位于中左并靠近镜头近端", prompt)
        self.assertNotIn("bb", prompt)
        self.assertNotIn("ba", prompt)

    def test_grid_codes_and_raw_json_do_not_leak_into_structured_overview(self):
        from modules.prompt_interrogator import _fallback_expert_structured_prompt

        raw_json_prompt = (
            '九宫格坐标规则：画面等分三行三列，aa左上、bb中心，'
            '{"expert_review":{"summary":"复核内容"},"fact_cards":[{"dimension":"构图"}],"expert_observations":{"构图":"人物位于bb"}}'
        )
        structured = _fallback_expert_structured_prompt(
            raw_json_prompt,
            "",
            [
                {
                    "id": "body_pose",
                    "label": "肢体动作专家",
                    "summary": "人物位于bb中心区域坐姿，头部位于ac右上区域，脸向3点方向扭转",
                    "fields": {"姿势": "人物位于bb中心区域坐姿，头部位于ac右上区域，脸向3点方向扭转"},
                    "observations": [],
                    "negative_constraints": [],
                }
            ],
        )

        text = json.dumps(structured, ensure_ascii=False)
        self.assertNotIn("九宫格坐标规则", text)
        self.assertNotIn("expert_review", text)
        self.assertNotIn("fact_cards", text)
        self.assertIn("人物位于中心区域坐姿", text)
        self.assertIn("头部位于右上区域", text)
        self.assertNotIn("bb", text)
        self.assertNotIn("ac", text)

    def test_prompt_from_structured_json_does_not_add_coordinate_explainer(self):
        structured = {
            "画面描述": {
                "主体": {"肢体动作": "人物位于画面中心偏下，画面左侧前景手部靠近镜头近端"},
                "整体画面": {"构图镜头": "9:16 竖幅中近景"},
            }
        }

        prompt = _prompt_from_structured_json(structured, "卧室人像")

        self.assertNotIn("九宫格坐标规则", prompt)
        self.assertIn("人物位于画面中心偏下", prompt)

    def test_visual_spec_format_parses_to_structured_prompt_and_negative_constraints(self):
        raw = json.dumps(
            {
                "visual_spec": {
                    "画面总体概述": "室内人像，人物坐在中心区域，红色服装为主体",
                    "构图与镜头": "竖版中近景，人物主体位于中心到下中，镜头近距离平视",
                    "主体与空间关系": "人物位于中景，前景手部在画面左侧，背景为灰色墙面",
                    "人物姿态": "头部向画面右侧 yaw 约20度，pitch 接近平视，roll 轻微向右侧倾，视线看向镜头",
                    "服装与材质": "红色布料上衣，布料褶皱沿腰部横向堆叠",
                    "光线": "左前方柔和白光，右侧形成浅灰阴影",
                    "颜色": "红色服装（#CC2233），灰色背景（#8C8C8C）",
                    "风格与质感": "室内写实摄影，皮肤高光平滑，背景轻微虚化",
                    "必须保留的关键点": "头部右转，红色服装，中心坐姿",
                    "易错点与禁止项": ["左右镜像动作", "水印"],
                    "不确定项": "鞋子被裁切，不进入正向提示词",
                    "最终可用于图像生成的一段完整提示词": "室内写实人像，中心坐姿，红色服装",
                },
                "keyword_prompt": "室内写实人像，中心坐姿，头部向画面右侧旋转约20度，红色服装",
                "negative_prompt": ["文字"],
            },
            ensure_ascii=False,
        )

        parsed = _parse_structured_interrogate_text(raw)
        text = parsed["prompt"]
        structured_text = parsed["structured_prompt_json"]

        self.assertIn("头部向画面右侧 yaw 约20度", text)
        self.assertIn("A. 结构化视觉规格书", structured_text)
        self.assertIn("画面总体概述", structured_text)
        self.assertIn("红色服装（#CC2233）", structured_text)
        self.assertIn("左右镜像动作", parsed["negative_prompt"])
        self.assertIn("文字", parsed["negative_prompt"])
        self.assertNotIn("鞋子被裁切", text)
        self.assertNotIn('"画面描述"', structured_text)

    def test_single_expert_visual_spec_preserves_user_template_in_result(self):
        def fake_chat(messages, **kwargs):
            return json.dumps(
                {
                    "visual_spec": {
                        "画面总体概述": "室内人像，主体位于画面中心，红色服装为视觉焦点",
                        "构图与镜头": {
                            "画幅": "竖版画幅",
                            "主体位置": "人物从中心延伸到右上区域",
                            "视角": "低角度仰拍",
                        },
                        "主体拆解": {
                            "主体1": "年轻女性坐姿，头部位于右上区域，腿部向下方镜头近端延伸"
                        },
                        "人物高精度分析（如有）": {
                            "头部 yaw": "头部向画面右侧旋转约25度",
                            "视线方向": "眼睛看向镜头方向",
                            "左臂": "画面左侧手臂向左上方伸出并握持红色塑料瓶",
                        },
                        "颜色与色调": "红色服装（#CC2233）与冷灰背景（#8A8E91）形成对比",
                        "易错点与禁止项": ["左右镜像动作", "散落多罐饮料"],
                    },
                    "keyword_prompt": "室内人像，竖版低角度仰拍，人物中心坐姿，头部向画面右侧旋转约25度，红色服装（#CC2233）",
                    "negative_prompt": ["水印"],
                },
                ensure_ascii=False,
            )

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (768, 1280), (120, 90, 80)).save(image_path)
            result = run_llm_expert_image_interrogator(
                str(image_path),
                chat_fn=fake_chat,
                single_pass=True,
                expert_team=False,
                review_enabled=False,
            )

        structured_text = result["structured_prompt_json"]
        self.assertIn('"A. 结构化视觉规格书": {', structured_text)
        self.assertIn('"画面总体概述"', structured_text)
        self.assertIn('"人物高精度分析（如有）"', structured_text)
        self.assertNotIn('"画面描述"', structured_text)
        self.assertIn("头部向画面右侧旋转约25度", result["prompt"])
        self.assertIn("左右镜像动作", result["negative_prompt"])
        self.assertIn("散落多罐饮料", result["negative_prompt"])
        self.assertIn("水印", result["negative_prompt"])

    def test_detailed_analysis_spatializes_subject_and_lifts_single_child_dimensions(self):
        def fake_chat(messages, **kwargs):
            return """{
              "visual_evidence": {
                "aspect_ratio": "9:16",
                "visible_body_range": "头部到膝部",
                "support_points": ["坐在床面"],
                "hand_endpoints": ["画面左侧手部靠近镜头"],
                "foot_or_shoe_contact": "画面裁切到膝部",
                "clothing_materials": ["浅色上衣"],
                "visible_text_confidence": 0,
                "nsfw_visible_evidence": "日常衣物",
                "foreground_background_regions": ["前景手部", "背景床铺"]
              },
              "detailed_analysis": {
                "主体外貌": {"人物": "人物坐在床面，面部朝向镜头"},
                "肢体动作": {"姿势": "躯干正对镜头略微前倾"},
                "场景背景": {"环境": "背景为床铺和窗帘"},
                "摄影参数": {"参考参数": "35mm，f/2.8，1/125s，ISO 400"},
                "构图镜头": {"画幅": "9:16 竖幅"},
                "材质纹理": {"面料": {"褶皱": "布料褶皱沿腰部横向堆叠"}}
              },
              "keyword_prompt": "人物坐在床面，9:16 竖幅，背景为床铺和窗帘",
              "negative_prompt": ["水印"]
            }"""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (768, 1280), (240, 230, 220)).save(image_path)
            result = run_llm_expert_image_interrogator(str(image_path), chat_fn=fake_chat, single_pass=True)

        description = result["structured_prompt"]["画面描述"]
        self.assertIn("基本概述", description)
        self.assertIn("图片内容", description["基本概述"])
        self.assertIn("主角", description["基本概述"])
        self.assertIn("风格", description["基本概述"])
        self.assertIn("重点内容", description["基本概述"])
        self.assertIn("人物坐在床面", description["基本概述"]["图片内容"])
        self.assertIn("人物坐在床面", description["基本概述"]["主角"])
        self.assertIn("35mm", description["基本概述"]["风格"])
        self.assertIn("人物坐在床面", description["基本概述"]["重点内容"])
        self.assertIn("主体", description)
        self.assertIn("背景", description)
        self.assertIn("整体画面", description)
        self.assertEqual(description["主体"]["主体外貌"], "人物坐在床面，面部朝向镜头")
        self.assertEqual(description["主体"]["肢体动作"], "躯干正对镜头略微前倾")
        self.assertEqual(description["背景"]["场景背景"], "背景为床铺和窗帘")
        self.assertIn("35mm", description["整体画面"]["摄影参数"])
        self.assertIn("f/2.8", description["整体画面"]["摄影参数"])
        self.assertIn("布料褶皱沿腰部横向堆叠", description["整体画面"]["材质细节"])
        self.assertNotIsInstance(description["整体画面"]["材质细节"], dict)
        self.assertNotIn('"参考参数": {', result["structured_prompt_json"])
        self.assertNotIn('"负面提示词"', result["structured_prompt_json"])
        self.assertIn("水印", result["negative_prompt"])

    def test_single_pass_expert_keeps_subject_section_focused(self):
        raw = """{
          "visual_spec": {
            "画面总体概述": "这是一张竖版人像摄影作品，主角为一名年轻东亚女性，身着红色系服装，坐在灰色金属背景前的地面上",
            "主体拆解": "年轻女性，画面中心偏右，呈坐姿，黑色齐刘海长发，白皙皮肤，红色吊带背心，红黑格纹百褶裙，红色高帮帆布鞋，头部向右侧倾斜",
            "重要物体细节": "可口可乐饮料，画面左侧地面堆叠，右侧地面单瓶，人物手中持有一罐，红色罐身，白色品牌标识，黄色瓶盖",
            "空间关系与层次": "人物腿部、脚部、地面、堆叠的饮料罐，灰色金属板墙面，带有横向接缝",
            "构图与镜头": "竖版约3:4，全身照，高机位俯拍，中焦段人像镜头，浅景深",
            "颜色与色调": "人物主体占据画面中心及右侧区域"
          },
          "keyword_prompt": "年轻东亚女性红色系服装坐在灰色金属背景前，红色饮料道具"
        }"""

        parsed = _parse_structured_interrogate_text(raw)
        description = parsed["structured_prompt"]

        self.assertIn("画面总体概述", description)
        self.assertIn("主体拆解", description)
        self.assertIn("重要物体细节", description)
        self.assertNotIn("画面描述", description)
        subject_text = json.dumps(description["主体拆解"], ensure_ascii=False)
        self.assertIn("年轻女性", subject_text)
        self.assertIn("红黑格纹百褶裙", subject_text)
        self.assertIn("头部向右侧倾斜", subject_text)
        self.assertNotIn("可口可乐", subject_text)
        self.assertNotIn("堆叠的饮料罐", subject_text)
        self.assertNotIn("金属板墙面", subject_text)
        self.assertNotIn("高机位俯拍", subject_text)
        self.assertIn("可口可乐饮料", description["重要物体细节"])
        self.assertIn("黄色瓶盖", description["重要物体细节"])
        self.assertIn("灰色金属板墙面", description["空间关系与层次"])
        overall_text = json.dumps(description["构图与镜头"], ensure_ascii=False)
        self.assertIn("高机位俯拍", overall_text)
        self.assertIn("中焦段人像镜头", overall_text)

    def test_expert_team_compacts_basic_overview_and_keeps_subject_detail(self):
        raw = """{
          "visual_spec": {
            "基本概述": {
              "图片内容": "一位年轻东亚女性坐在灰色金属墙前的地面上，右手高举红色易拉罐，左手伸向左下角饮料罐堆，穿红色吊带背心、红黑格纹百褶裙、红色高帮帆布鞋，背景有灰色金属墙板和水磨石地面，画面右下有红色塑料瓶，整体为高机位俯拍街头时尚人像",
              "主角": "年轻东亚女性，黑色长发齐刘海，白皙肤色，红色吊带背心，红黑格纹百褶短裙，红色高帮鞋，银色项链和手表",
              "风格": "高饱和度红灰对比街头时尚摄影，清晰锐利，自然光，平台截图感",
              "重点内容": "人物躯干从骨盆向画面左上扭转，胸腔向镜头抬起，右臂肩部抬高、肘部弯曲、前臂向左上折返，右手握住红色易拉罐"
            },
            "主体": {
              "肢体动作": "人物坐在地面中心偏右，骨盆落在下中偏右，胸腔向画面左上旋转，脊柱形成斜向 C 型趋势，右肩高于左肩，右上臂从肩部向左上抬起，肘部位于左上并弯曲约90度，右前臂向下折到手腕，右手握住红色易拉罐；左臂从胸前向左下伸展，左手靠近饮料罐堆。",
              "手持物体": "红色易拉罐位于左上，靠近镜头中远端，罐口朝上偏左，手指包裹罐身上半部。"
            }
          },
          "keyword_prompt": "红色主题高机位人像，人物坐地并手持饮料罐"
        }"""

        parsed = _parse_structured_interrogate_text(raw)
        description = parsed["structured_prompt"]

        self.assertIn("A. 结构化视觉规格书", parsed["structured_prompt_json"])
        self.assertNotIn('"画面描述"', parsed["structured_prompt_json"])
        overview_text = json.dumps(description["基本概述"], ensure_ascii=False)
        subject_text = json.dumps(description["主体"], ensure_ascii=False)
        self.assertIn("一位年轻东亚女性", overview_text)
        self.assertIn("脊柱形成斜向 C 型趋势", subject_text)
        self.assertIn("肘部位于左上并弯曲约90度", subject_text)
        self.assertIn("红色易拉罐位于左上", subject_text)

    def test_compacting_overview_relocates_details_before_clipping(self):
        raw = """{
          "visual_spec": {
            "基本概述": "一位年轻东亚女性坐在灰色金属墙前的地面上，人物头部位于画面右上并直视镜头，人物躯干从骨盆到胸腔向画面左上扭转，右上臂抬高且肘部位于左上弯曲约90度，右手握住红色易拉罐，画面左下有五个红色易拉罐堆叠，画面右下有红色塑料瓶和黄色瓶盖，背景是灰色金属墙板和水磨石地面，整体为高机位俯拍，镜头向下约35度，画面略顺时针倾斜",
            "主体": "年轻女性，红色吊带背心，红黑格纹百褶裙"
          },
          "keyword_prompt": "红色主题高机位人像"
        }"""

        parsed = _parse_structured_interrogate_text(raw)
        description = parsed["structured_prompt"]
        structured_text = parsed["structured_prompt_json"]

        self.assertIn("A. 结构化视觉规格书", structured_text)
        self.assertNotIn('"画面描述"', structured_text)
        self.assertIn("躯干从骨盆到胸腔向画面左上扭转", json.dumps(description, ensure_ascii=False))
        self.assertIn("肘部位于左上弯曲约90度", json.dumps(description, ensure_ascii=False))
        self.assertIn("右手握住红色易拉罐", json.dumps(description, ensure_ascii=False))
        self.assertIn("五个红色易拉罐堆叠", json.dumps(description, ensure_ascii=False))
        self.assertIn("黄色瓶盖", json.dumps(description, ensure_ascii=False))
        self.assertIn("灰色金属墙板", json.dumps(description, ensure_ascii=False))
        self.assertIn("高机位俯拍", json.dumps(description, ensure_ascii=False))
        self.assertIn("顺时针倾斜", json.dumps(description, ensure_ascii=False))

    def test_single_pass_expert_repackages_loose_expert_fields_into_grouped_json(self):
        def fake_chat(messages, **kwargs):
            return """{
              "visual_evidence": [{
                "value": {
                  "aspect_ratio": "9:16",
                  "visible_body_range": "头部到膝部",
                  "support_points": ["坐在床面"],
                  "hand_endpoints": ["画面左侧手部靠近镜头"],
                  "foot_or_shoe_contact": "画面裁切到膝部",
                  "clothing_materials": ["白色蕾丝吊带", "浅色抽绳短裤"],
                  "visible_text_confidence": 0,
                  "nsfw_visible_evidence": "低领和乳沟可见，未见乳头或性器官",
                  "foreground_background_regions": ["前景模糊手部", "背景床铺和窗帘"]
                },
                "evidence": "宽松专家事实",
                "confidence": 0.88,
                "allow_positive": true
              }],
              "keyword_prompt": "东亚女性坐在床上，白色蕾丝吊带，浅色抽绳短裤，前景手部模糊",
              "expert_observations": [
                {"id":"body_pose","label":"肢体动作专家","summary":"床上正坐，画面左侧手靠近镜头","fields":{"姿势":"人物位于中心到下中的床面中景，躯干正对镜头略微前倾","手部":"画面左侧前景手部位于中左并靠近镜头近端，手臂从中心向9点方向伸出形成模糊"},"observations":["腿部位于下中并裁切到膝部"],"negative_constraints":["全身入镜"],"confidence":0.9},
                {"id":"clothing_makeup","label":"服装妆容专家","summary":"白色蕾丝吊带和浅色抽绳短裤","fields":{"服装":"白色蕾丝吊带，浅色抽绳短裤"},"observations":["领口蕾丝边可见"],"negative_constraints":["普通T恤"],"confidence":0.88},
                {"id":"composition","label":"构图镜头专家","summary":"竖幅床上中近景","fields":{"构图":"9:16 竖幅，人物从上中延伸到下中，中左前景手部靠近镜头，背景床铺和窗帘位于中后景"},"observations":["前景手部模糊"],"negative_constraints":["1:1正方形"],"confidence":0.86}
              ]
            }"""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (768, 1280), (240, 230, 220)).save(image_path)
            result = run_llm_expert_image_interrogator(
                str(image_path),
                chat_fn=fake_chat,
                single_pass=True,
                include_quality=True,
            )

        structured = result["structured_prompt"]
        self.assertIn("床面中景", structured["画面描述"]["主体"]["肢体动作"])
        self.assertIn("白色蕾丝吊带", structured["画面描述"]["主体"]["服装妆容"])
        self.assertIn("9:16", structured["画面描述"]["整体画面"]["构图镜头"])
        self.assertNotIn("空间坐标", structured["画面描述"]["整体画面"])
        self.assertNotIn("九宫格坐标规则", result["prompt"])
        self.assertIn("画面左侧前景手部位于中左并靠近镜头近端", result["prompt"])
        self.assertNotIn("ba", result["prompt"])
        self.assertNotIn("空间坐标：", result["prompt"])
        issue_codes = {issue["code"] for issue in result["reverse_prompt_quality"]["issues"]}
        self.assertNotIn("missing_visual_evidence", issue_codes)
        self.assertNotIn("sparse_fallback_structured_prompt", issue_codes)

    def test_single_pass_expert_accepts_object_style_expert_observations(self):
        def fake_chat(messages, **kwargs):
            return """{
              "visual_evidence": {
                "aspect_ratio": "9:16",
                "visible_body_range": "头部到鞋子",
                "support_points": ["鞋底踩在碎石地面"],
                "hand_endpoints": ["画面右侧手靠近头发"],
                "foot_or_shoe_contact": ["黑色运动鞋接触碎石"],
                "clothing_materials": ["深蓝连帽卫衣", "黑色过膝丝袜", "黑色厚底运动鞋"],
                "visible_text_confidence": 0.3,
                "nsfw_visible_evidence": "日常服装，未见成人裸露",
                "foreground_background_regions": ["前景碎石", "背景海岸和阴天"]
              },
              "expert_observations": {
                "body_pose": {"姿势": "人物蹲在碎石海岸，鞋底踩地承重，膝盖弯曲靠近身体"},
                "clothing_makeup": {"服装": "深蓝连帽卫衣，黑色过膝丝袜，黑色厚底运动鞋"},
                "composition": {"构图": "竖幅手机图，人物近全身入镜，背景为岩石海岸"}
              },
              "keyword_prompt": "碎石海岸蹲姿人物，深蓝卫衣，黑色过膝丝袜，黑色厚底运动鞋",
              "negative_prompt": ["1:1正方形"]
            }"""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (768, 1280), (120, 130, 140)).save(image_path)
            result = run_llm_expert_image_interrogator(
                str(image_path),
                chat_fn=fake_chat,
                single_pass=True,
                include_quality=True,
            )

        description = result["structured_prompt"]["画面描述"]
        self.assertIn("基本概述", description)
        self.assertIn("碎石海岸蹲姿人物", description["基本概述"]["图片内容"])
        self.assertIn("人物蹲在碎石海岸", description["基本概述"]["重点内容"])
        self.assertIn("人物蹲在碎石海岸", description["主体"]["肢体动作"])
        self.assertIn("深蓝连帽卫衣", description["主体"]["服装妆容"])
        self.assertIn("竖幅手机图", description["整体画面"]["构图镜头"])
        self.assertNotIn("sparse_fallback_structured_prompt", {issue["code"] for issue in result["reverse_prompt_quality"]["issues"]})

    def test_single_pass_expert_preserves_adaptive_dimensions_and_exposure_alias(self):
        def fake_chat(messages, **kwargs):
            return """{
              "visual_evidence": {
                "aspect_ratio": "9:16",
                "visible_body_range": "头部到膝部",
                "support_points": ["人物坐在车内座椅上"],
                "hand_endpoints": ["画面左侧手臂伸向座椅靠背"],
                "foot_or_shoe_contact": "画面裁切到膝部附近",
                "clothing_materials": ["白色衬衫", "红色百褶裙"],
                "visible_text_confidence": 0,
                "nsfw_visible_evidence": "短裙和大腿皮肤可见",
                "foreground_background_regions": ["前景座椅靠背", "背景车窗草地"]
              },
              "expert_observations": {
                "composition": {"构图": "9:16 车内竖幅人像，主体在画面中部偏下"},
                "exposure_content": {"暴露内容": "短裙下方大腿皮肤可见", "衣物遮挡边界": "红色裙摆遮挡胯部"},
                "reflection_detail": {"车窗反射": "画面右侧车窗有浅色反光带", "遮挡关系": "反光覆盖在窗框边缘"}
              },
              "keyword_prompt": "车内竖幅人像，红色百褶裙，大腿皮肤可见，车窗浅色反光",
              "negative_prompt": ["文字", "水印"]
            }"""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (768, 1280), (80, 90, 100)).save(image_path)
            result = run_llm_expert_image_interrogator(
                str(image_path),
                chat_fn=fake_chat,
                single_pass=True,
                include_quality=True,
            )

        description = result["structured_prompt"]["画面描述"]
        self.assertIn("暴露内容", description["主体"])
        self.assertIn("短裙下方大腿皮肤可见", json.dumps(description["主体"]["暴露内容"], ensure_ascii=False))
        self.assertIn("reflection_detail", description["整体画面"])
        self.assertIn("车窗", description["整体画面"]["reflection_detail"])

    def test_expert_json_prompts_require_text_signage_dimension(self):
        visible_text = next(spec for spec in IMAGE_INTERROGATE_EXPERTS if spec["id"] == "visible_text")
        self.assertEqual(visible_text["label"], "文字标识专家")
        self.assertIn("visible_text 返回空对象", visible_text["instruction"])
        self.assertIn("文字标识", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("visible_text", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("negative_prompt 必须包含文字、水印、Logo、UI字样", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("visible_text", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("无文字时为空对象", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertNotIn("负面建议", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)

    def test_expert_prompts_require_precise_color_and_nsfw_detail_dimensions(self):
        expert_text = json.dumps(IMAGE_INTERROGATE_EXPERTS, ensure_ascii=False)
        self.assertIn("近似 HEX", COLOR_PRECISION_STANDARD)
        self.assertIn("画面风格细节标准", STYLE_ANALYSIS_STANDARD)
        self.assertIn("媒介类型、成像质感、视觉语言、后期痕迹、情绪基调", expert_text)
        self.assertLess(len(RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE), 5900)
        self.assertLess(len(EXPERT_TEAM_SECOND_REVIEW_TEMPLATE), 3100)
        self.assertIn("媒介类型、成像质感、视觉语言、后期痕迹", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("不能只写写实、自然、柔和、氛围好", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("风格必须说明媒介类型、成像质感、视觉语言、后期痕迹", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("主体肤色", expert_text)
        self.assertIn("服装色卡", expert_text)
        self.assertIn("覆盖肤色、发色、服装、背景、光源、阴影和高光", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("所有 HEX 写在括号里", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("隐私部位细节", NSFW_DETAIL_STANDARD)
        self.assertIn("暴露内容", NSFW_DETAIL_STANDARD)
        self.assertIn("衣物边界", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("液体/湿润反光", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("暴露内容必须直接描述可见部位", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertNotIn("安全标签", NSFW_DETAIL_STANDARD)
        self.assertNotIn("安全标签", EXPERT_TEAM_DETAIL_SCHEMA)
        self.assertNotIn('"安全标签"', RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertNotIn('"安全标签"', RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertNotIn("安全标签", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("自适应维度", SELF_DIRECTED_DIMENSION_STANDARD)
        self.assertIn("从外到内、从左到右、从上到下、从前到后", SELF_DIRECTED_DIMENSION_STANDARD)
        self.assertIn("互补去重", SELF_DIRECTED_DIMENSION_STANDARD)
        self.assertIn("JSON 层级标准", TWO_LEVEL_JSON_STANDARD)
        self.assertIn("不要继续嵌套对象", TWO_LEVEL_JSON_STANDARD)
        self.assertIn("看不见的不回答、不补全、不猜测", VISIBLE_ONLY_STANDARD)
        self.assertIn("某项看不见就省略该字段", VISIBLE_ONLY_STANDARD)
        self.assertIn("可见事实硬指标", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("只写可见证据", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("只能基于图中可见像素修正", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("场景与物体身份复核标准", SCENE_OBJECT_VERIFICATION_STANDARD)
        self.assertIn("塑料瓶有瓶颈、瓶盖", SCENE_OBJECT_VERIFICATION_STANDARD)
        self.assertIn("不能因为有一个红色饮料道具就补写易拉罐堆", SCENE_OBJECT_VERIFICATION_STANDARD)
        self.assertIn("腿脚悬空、鞋底靠近镜头", SCENE_OBJECT_VERIFICATION_STANDARD)
        self.assertIn(SCENE_OBJECT_VERIFICATION_STANDARD, RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("塑料瓶不能写成易拉罐", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("坐在金属架/横梁不能写成地面跪坐", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("红色塑料瓶不能写成易拉罐", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("坐在金属架/横梁不能写成地面跪坐", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("第一层 key 用中文观点标签", EXPERT_TEAM_DETAIL_SCHEMA)
        self.assertIn("观点标签: 详细细节", EXPERT_TEAM_DETAIL_SCHEMA)
        self.assertIn("事实卡标准", EXPERT_TEAM_FACT_CARD_STANDARD)
        self.assertIn("fact_cards", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("专家观点的唯一事实来源", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("复核检查表", EXPERT_TEAM_REVIEW_CHECKLIST)
        self.assertIn("fact_cards", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertNotIn("基础专家 id", EXPERT_TEAM_DETAIL_SCHEMA)
        self.assertNotIn("第一层只能是固定维度 id", EXPERT_TEAM_DETAIL_SCHEMA)
        self.assertIn("禁止在 expert_observations 的 value 中继续嵌套对象", EXPERT_TEAM_DETAIL_SCHEMA)
        self.assertIn("继承单专家提示词的观察质量", EXPERT_TEAM_SINGLE_EXPERT_QUALITY_STANDARD)
        self.assertIn("value 只能是一句话高密度观点", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("手脚端点和遮挡", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("按以下结构输出", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("禁止微尘、漂浮粒子", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("画面总体概述", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("结构化视觉规格书", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("新增中文观点标签", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("基本概述 只能短写一句定位", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("主体 成为最细部分", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn(EXPERT_TEAM_VISUAL_SPEC_CONTRACT, RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn(EXPERT_TEAM_VISUAL_SPEC_CONTRACT, EXPERT_TEAM_SUBJECT_PASS_TEMPLATE)
        self.assertIn(EXPERT_TEAM_VISUAL_SPEC_CONTRACT, EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("主体必须是对象", EXPERT_TEAM_VISUAL_SPEC_CONTRACT)
        self.assertIn("不得把主体写成一整段字符串", EXPERT_TEAM_VISUAL_SPEC_CONTRACT)
        self.assertIn("对象 + 画面位置/方向 + 链式动作/属性 + 接触或遮挡", EXPERT_TEAM_VISUAL_SPEC_CONTRACT)
        self.assertIn("禁止输出模板残片句式", EXPERT_TEAM_VISUAL_SPEC_CONTRACT)
        self.assertIn(EXPERT_TEAM_COMPLETE_SENTENCE_STANDARD, RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("前后矛盾禁止", EXPERT_TEAM_COMPLETE_SENTENCE_STANDARD)
        self.assertIn("主体字段必须比基本概述更长、更细、更集中", EXPERT_TEAM_SUBJECT_PASS_TEMPLATE)
        self.assertIn("visual_spec.基本概述 是否过长", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("细节迁移到 主体、前景、背景、整体画面", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertNotIn("10 个专家键必须全部出现", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertNotIn("第二层必须是该维度的放大细节字段", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("#RRGGBB", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("所有色值必须放在括号里", COLOR_PRECISION_STANDARD)
        self.assertIn("中文观点字符串", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("头发发色/染发/发饰必须具体", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("人物站位角度", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("拍摄角度", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("镜头旋转倾斜", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("镜头旋转倾斜", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("画面 roll", CAMERA_AND_BODY_ANGLE_STANDARD)
        self.assertIn("顺时针或逆时针倾斜", CAMERA_AND_BODY_ANGLE_STANDARD)
        self.assertIn("头部旋转/倾斜", CAMERA_AND_BODY_ANGLE_STANDARD)
        self.assertIn(TRUNK_HAND_OBJECT_ANGLE_STANDARD, RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(TRUNK_HAND_OBJECT_ANGLE_STANDARD, RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn(TRUNK_HAND_OBJECT_ANGLE_STANDARD, EXPERT_TEAM_SUBJECT_PASS_TEMPLATE)
        self.assertIn(TRUNK_HAND_OBJECT_ANGLE_STANDARD, EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn(LIGHT_INCIDENCE_ANGLE_STANDARD, RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(LIGHT_INCIDENCE_ANGLE_STANDARD, RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn(LIGHT_INCIDENCE_ANGLE_STANDARD, EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("左右手位置", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("手持物体位置", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("采光入射角", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("阴影投射方向", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("yaw/pitch/roll", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn(HUMAN_POSE_EXPERT_STANDARD, RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("肘部为必填中间节点", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn(BODY_JOINT_CHAIN_COMPLETENESS_STANDARD, RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("头部 yaw/pitch/roll", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("肩-上臂-肘-前臂-腕-掌-指链路", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn(BODY_JOINT_CHAIN_COMPLETENESS_STANDARD, RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("手腕旋转", CAMERA_AND_BODY_ANGLE_STANDARD)
        self.assertIn("脚踝倾斜", CAMERA_AND_BODY_ANGLE_STANDARD)
        self.assertIn("看不见就省略", CAMERA_AND_BODY_ANGLE_STANDARD)
        self.assertIn("九宫格", SPATIAL_CONTROL_COORDINATE_STANDARD)
        self.assertIn("时钟方向", SPATIAL_CONTROL_COORDINATE_STANDARD)
        self.assertIn("左上、上中、右上", SPATIAL_CONTROL_COORDINATE_STANDARD)
        self.assertIn("不要输出任何英文字母区域代码", SPATIAL_CONTROL_COORDINATE_STANDARD)
        self.assertIn("12点上", SPATIAL_CONTROL_COORDINATE_STANDARD)
        self.assertIn("不要单独集中输出 spatial_coordinates", SPATIAL_CONTROL_COORDINATE_STANDARD)
        self.assertIn("坐标必须嵌入每个对象", SPATIAL_CONTROL_COORDINATE_STANDARD)
        self.assertIn("人体末梢节点强制标准", TERMINAL_NODE_DETAIL_STANDARD)
        self.assertIn("鼻尖方向", TERMINAL_NODE_DETAIL_STANDARD)
        self.assertIn("下巴贴肩", TERMINAL_NODE_DETAIL_STANDARD)
        self.assertIn("指尖方向", TERMINAL_NODE_DETAIL_STANDARD)
        self.assertIn("脚尖方向", TERMINAL_NODE_DETAIL_STANDARD)
        self.assertIn("头部后仰位于画面右上区域", HEAD_POSE_REPLICATION_EXAMPLE)
        self.assertIn("下巴贴紧右肩", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("九宫格和时钟方向", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("英文字母区域代码", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("九宫格", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("鼻尖", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("肩-上臂-肘-前臂-腕-掌-指链路", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertIn("髋膝踝角度", RUNTIME_DETAILED_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("画面 roll", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn(BODY_JOINT_CHAIN_COMPLETENESS_STANDARD, EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertIn("只写正面/侧面不够细", EXPERT_TEAM_SECOND_REVIEW_TEMPLATE)
        self.assertNotIn("...", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)
        self.assertNotIn("……", RUNTIME_SINGLE_PASS_EXPERT_TEAM_TEMPLATE)

    def test_expert_team_viewpoint_strings_wrap_hex_and_add_mirror_negative(self):
        def fake_chat(messages, **kwargs):
            return """{
              "visual_evidence": {
                "aspect_ratio": "9:16",
                "visible_body_range": "头部到膝部",
                "support_points": ["座椅坐垫"],
                "hand_endpoints": ["画面左侧手臂伸向座椅靠背"],
                "foot_or_shoe_contact": "画面裁切到膝部",
                "clothing_materials": ["红色百褶裙"],
                "visible_text_confidence": 0,
                "nsfw_visible_evidence": "短裙和大腿皮肤可见",
                "foreground_background_regions": ["前景座椅", "背景车窗"]
              },
              "expert_observations": {
                "色彩": "服装主色: 红色 #FF0033，头发颜色: 深黑 #111111，背景为绿色草地 #55AA33",
                "肢体": "人物跪坐在车厢前排座椅上，画面左侧手臂伸向座椅靠背，面部朝镜头，躯干朝座椅靠背方向"
              },
              "keyword_prompt": "车内人像，红色 #FF0033 百褶裙，画面左侧手臂伸向座椅靠背",
              "negative_prompt": ["水印"]
            }"""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (768, 1280), (80, 90, 100)).save(image_path)
            result = run_llm_expert_image_interrogator(
                str(image_path),
                chat_fn=fake_chat,
                single_pass=True,
                expert_team=True,
                review_enabled=False,
            )

        self.assertIn("红色（#FF0033）", result["prompt"])
        self.assertIn("深黑（#111111）", result["prompt"])
        self.assertNotIn("服装主色:", result["prompt"])
        self.assertNotIn("头发颜色:", result["prompt"])
        self.assertIn("左右镜像动作", result["negative_prompt"])
        self.assertIn("镜像翻转构图", result["negative_prompt"])
        self.assertIn("红色（#FF0033）", result["structured_prompt_json"])
        self.assertNotIn("红色 #FF0033", result["structured_prompt_json"])

    def test_expert_team_fact_cards_are_preserved_and_backfill_missing_experts(self):
        def fake_chat(messages, **kwargs):
            return """{
              "visual_evidence": {
                "aspect_ratio": "9:16",
                "visible_body_range": "头部到膝部",
                "support_points": ["坐在床面"],
                "hand_endpoints": ["画面左侧手靠近镜头"],
                "foot_or_shoe_contact": "画面裁切到膝部",
                "clothing_materials": ["白色蕾丝吊带"],
                "visible_text_confidence": 0,
                "nsfw_visible_evidence": "低领和乳沟可见",
                "foreground_background_regions": ["前景手部", "背景床铺"]
              },
              "fact_cards": [
                {
                  "dimension": "风格",
                  "visible_content": "手机感室内暖光人像，浅景深和轻微美颜平滑感可见",
                  "location": "整体画面",
                  "evidence": "背景床铺柔焦，肤色平滑，暖白室内光",
                  "confidence": 0.92,
                  "allow_positive": true
                },
                {
                  "dimension": "文字标识",
                  "visible_content": "图中无可读文字",
                  "location": "整体画面",
                  "evidence": "未见清晰字形",
                  "confidence": 0.7,
                  "allow_positive": false
                }
              ],
              "expert_observations": {
                "构图": "9:16 竖幅室内中近景，人物位于中心中景，画面左侧前景手部位于中左并靠近镜头近端，背景床铺位于中右到右下后景"
              },
              "expert_review": {"summary": "事实卡已校验", "passed_experts": ["构图"], "weak_experts": ["风格"], "unsupported_claims": []},
              "keyword_prompt": "室内暖光人像，9:16 竖幅，人物居中，浅景深",
              "negative_prompt": ["水印", "文字"]
            }"""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (768, 1280), (240, 230, 220)).save(image_path)
            result = run_llm_expert_image_interrogator(
                str(image_path),
                chat_fn=fake_chat,
                single_pass=True,
                expert_team=True,
                review_enabled=False,
            )

        fact_cards = result["expert_interrogate"]["fact_cards"]
        self.assertEqual(len(fact_cards), 2)
        self.assertEqual(fact_cards[0]["dimension"], "风格")
        self.assertTrue(fact_cards[0]["allow_positive"])
        self.assertFalse(fact_cards[1]["allow_positive"])
        mood_items = [item for item in result["expert_interrogate"]["experts"] if item.get("id") == "mood_style"]
        self.assertTrue(any(item.get("from_fact_cards") for item in mood_items))
        self.assertIn("手机感室内暖光人像", json.dumps(mood_items, ensure_ascii=False))
        self.assertNotIn("图中无可读文字", result["prompt"])
        self.assertNotIn("九宫格坐标规则", result["prompt"])
        self.assertIn("画面左侧前景手部位于中左并靠近镜头近端", result["prompt"])
        self.assertNotIn("ba", result["prompt"])
        self.assertNotIn("空间坐标：", result["prompt"])
        self.assertNotIn("空间坐标", result["structured_prompt"]["画面描述"]["整体画面"])

    def test_expert_team_plain_prompt_preserves_similar_json_details(self):
        def fake_chat(messages, **kwargs):
            return """{
              "visual_evidence": {
                "aspect_ratio": "9:16",
                "visible_body_range": "头部到鞋子",
                "support_points": ["坐在金属架横梁"],
                "hand_endpoints": ["画面左侧手持红色饮料瓶", "画面右侧手撑在金属架"],
                "foot_or_shoe_contact": "红色高帮靴悬空靠近镜头",
                "clothing_materials": ["红色挂脖上衣", "红黑格纹短裙", "红色高帮靴"],
                "visible_text_confidence": 0,
                "nsfw_visible_evidence": "短裙下方大腿皮肤可见",
                "foreground_background_regions": ["前景红色靴子", "背景玻璃幕墙"]
              },
              "fact_cards": [
                {
                  "dimension": "摄影",
                  "visible_content": "窗框竖线略向画面右侧倾斜，低机位广角透视明显",
                  "location": "背景玻璃幕墙",
                  "evidence": "竖直窗框与画幅边缘不完全平行，前景靴子显著放大",
                  "confidence": 0.9,
                  "allow_positive": true
                }
              ],
              "expert_observations": {
                "构图": "人物位于画面中心偏右，红色上衣和红色靴子形成主色，低角度仰拍，前景双靴在画面下方放大，背景玻璃幕墙位于上半部",
                "肢体": "人物位于画面中心偏右，红色上衣和红色靴子形成主色，头部在画面右上向3点方向侧转，画面左侧手持红色饮料瓶，画面右侧手撑住金属架边缘，双腿向画面下方镜头近端伸出",
                "服装": "人物位于画面中心偏右，红色上衣和红色靴子形成主色，红色挂脖紧身上衣露出肩颈，红黑格纹短裙覆盖臀部并露出白色内搭边缘，红色高帮靴配白色鞋带",
                "材质": "人物位于画面中心偏右，红色上衣和红色靴子形成主色，玻璃幕墙有冷色反光，金属架为灰色哑光方管，饮料瓶为红色半透明塑料并有瓶盖高光"
              },
              "expert_review": {"summary": "多维度细节已校验", "passed_experts": ["构图", "肢体", "服装", "材质"], "weak_experts": [], "unsupported_claims": []},
              "keyword_prompt": "低角度红色主题人像",
              "negative_prompt": ["水印", "文字"]
            }"""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (768, 1280), (180, 80, 70)).save(image_path)
            result = run_llm_expert_image_interrogator(
                str(image_path),
                chat_fn=fake_chat,
                single_pass=True,
                expert_team=True,
                review_enabled=False,
            )

        self.assertIn("头部在画面右上向3点方向侧转", result["prompt"])
        self.assertIn("红黑格纹短裙覆盖臀部并露出白色内搭边缘", result["prompt"])
        self.assertIn("饮料瓶为红色半透明塑料并有瓶盖高光", result["prompt"])
        self.assertIn("坐在金属架横梁", result["prompt"])
        self.assertIn("红色高帮靴悬空靠近镜头", result["prompt"])
        self.assertIn("窗框竖线略向画面右侧倾斜", result["prompt"])
        self.assertIn("头部在画面右上向3点方向侧转", result["structured_prompt_json"])
        self.assertGreater(len(result["prompt"]), 300)

    def test_expert_team_absent_text_moves_to_negative_prompt_only(self):
        calls = []
        token_calls = []

        def fake_chat(messages, **kwargs):
            text = messages[1]["content"][0]["text"]
            calls.append(text)
            token_calls.append(kwargs.get("max_tokens"))
            if "专家团初稿 JSON" in text:
                return """{
                  "expert_review": {"summary": "复核通过", "accuracy_score": 0.94, "fixed_issues": [], "unsupported_claims": [], "missing_dimensions": []},
                  "expert_observations": {
                    "composition": {"构图": "9:16 竖幅，人物位于画面中央"},
                    "photography_parameters": {"参考参数": "35mm，f/2.8，1/125s，ISO 400"},
                    "color_light": {"颜色": "暖白光，低对比"},
                    "mood_style": {"氛围": "室内写实照片"},
                    "body_pose": {"姿势": "人物正坐，躯干朝向镜头"},
                    "expression_language": {"表情": "平静闭唇，视线朝镜头"},
                    "sexual_boundary": {"可见事实": "日常衣物，未见成人裸露"},
                    "clothing_makeup": {"服装": "浅色上衣"},
                    "materials_texture": {"材质": "布料柔软轻微褶皱"},
                    "visible_text": {}
                  },
                  "keyword_prompt": "室内竖幅人物照片，暖白光，人物正坐，浅色上衣",
                  "negative_prompt": ["水印", "文字", "Logo", "UI字样"]
                }"""
            self.assertIn("visible_text", text)
            return """{
              "visual_evidence": {
                "aspect_ratio": "9:16",
                "visible_body_range": "头部到膝部",
                "support_points": ["坐在床面"],
                "hand_endpoints": ["手部在画面中部"],
                "foot_or_shoe_contact": "画面裁切到膝部",
                "clothing_materials": ["浅色上衣"],
                "visible_text_confidence": 0,
                "nsfw_visible_evidence": "日常衣物，未见成人裸露",
                "foreground_background_regions": ["前景人物", "背景床铺"]
              },
              "expert_observations": {
                "composition": {"构图": "9:16 竖幅，人物位于画面中央"},
                "photography_parameters": {"参考参数": "35mm，f/2.8，1/125s，ISO 400"},
                "color_light": {"颜色": "暖白光，低对比"},
                "mood_style": {"氛围": "室内写实照片"},
                "body_pose": {"姿势": "人物正坐，躯干朝向镜头"},
                "expression_language": {"表情": "平静闭唇，视线朝镜头"},
                "sexual_boundary": {"可见事实": "日常衣物，未见成人裸露"},
                "clothing_makeup": {"服装": "浅色上衣"},
                "materials_texture": {"材质": "布料柔软轻微褶皱"},
                "visible_text": {}
              },
              "expert_review": {"summary": "十个专家维度已自检", "passed_experts": ["visible_text"], "weak_experts": [], "unsupported_claims": []},
              "keyword_prompt": "室内竖幅人物照片，暖白光，人物正坐，浅色上衣",
              "negative_prompt": ["水印", "文字", "Logo", "UI字样"]
            }"""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (768, 1280), (240, 230, 220)).save(image_path)
            result = run_llm_expert_image_interrogator(
                str(image_path),
                chat_fn=fake_chat,
                single_pass=True,
                expert_team=True,
                review_enabled=True,
                include_quality=True,
            )

        self.assertEqual(len(calls), 3)
        self.assertEqual(token_calls, [EXPERT_TEAM_GLOBAL_MAX_TOKENS, EXPERT_TEAM_SUBJECT_MAX_TOKENS, EXPERT_TEAM_REVIEW_MAX_TOKENS])
        self.assertIn("专家团第1轮", calls[0])
        self.assertIn("只做整体扫描", calls[0])
        self.assertIn("专家团第2轮", calls[1])
        self.assertIn("只深挖主体", calls[1])
        self.assertIn("专家团初稿 JSON", calls[2])
        self.assertNotIn("文字标识", result["structured_prompt"]["画面描述"])
        self.assertNotIn("可见文字", result["structured_prompt"]["画面描述"])
        self.assertIn("文字", result["negative_prompt"])
        self.assertIn("水印", result["negative_prompt"])
        self.assertIn("Logo", result["negative_prompt"])
        self.assertIn("UI字样", result["negative_prompt"])
        material = result["structured_prompt"]["画面描述"]["整体画面"]["材质纹理"]
        self.assertIn("布料柔软", material)
        self.assertNotIsInstance(material, dict)
        self.assertNotIn("图中无可读文字", result["structured_prompt_json"])
        self.assertNotIn('"负面提示词"', result["structured_prompt_json"])
        self.assertNotIn("负面建议", result["structured_prompt_json"])
        self.assertIn("global_pass", result["expert_interrogate"]["initial_raw"])
        self.assertIn("subject_pass", result["expert_interrogate"]["initial_raw"])
        self.assertTrue(result["expert_interrogate"]["second_review_enabled"])

    def test_expert_team_removes_ellipsis_from_visible_results(self):
        long_tail = "，并且保留这一段用于确认专家团可见内容没有被系统截断，头发贴近脸颊，鼻尖朝向肩部，指尖朝向画面下方，鞋底靠近镜头前景"

        def fake_chat(messages, **kwargs):
            return """{
              "visual_evidence": {
                "aspect_ratio": "9:16",
                "visible_body_range": "头部到鞋子",
                "support_points": ["坐在金属台架边缘..."],
                "hand_endpoints": ["画面左侧手握瓶身…"],
                "foot_or_shoe_contact": "前景红色靴子接近镜头……",
                "clothing_materials": ["红色上衣", "红黑格纹裙摆"],
                "visible_text_confidence": 0.8,
                "nsfw_visible_evidence": "短裙下方大腿皮肤可见",
                "foreground_background_regions": ["玻璃窗背景", "前景靴子"]
              },
              "fact_cards": [
                {
                  "dimension": "肢体",
                  "visible_content": "头部位于画面右上，脸向画面右侧扭转，下巴贴肩，视线向右下看__LONG_TAIL__……",
                  "location": "画面右上区域...",
                  "evidence": "脸部只露侧脸，肩颈相邻…",
                  "confidence": 0.93,
                  "allow_positive": true
                }
              ],
              "expert_observations": {
                "肢体": "头部位于画面右上，脸向画面右侧扭转，下巴贴肩，视线向右下看__LONG_TAIL__……",
                "构图": "低机位广角仰拍，前景靴子放大..."
              },
              "expert_review": {"summary": "已清理省略号…", "passed_experts": ["肢体"], "weak_experts": [], "unsupported_claims": []},
              "keyword_prompt": "低机位广角红色主题人像，头部位于画面右上，脸向画面右侧扭转，下巴贴肩",
              "negative_prompt": ["水印", "文字"]
            }""".replace("__LONG_TAIL__", long_tail)

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (768, 1280), (180, 120, 110)).save(image_path)
            result = run_llm_expert_image_interrogator(
                str(image_path),
                chat_fn=fake_chat,
                single_pass=True,
                expert_team=True,
                review_enabled=False,
            )

        visible = json.dumps(result["expert_interrogate"], ensure_ascii=False)
        self.assertNotIn("...", visible)
        self.assertNotIn("…", visible)
        self.assertIn("下巴贴肩", visible)
        self.assertIn("保留这一段用于确认专家团可见内容没有被系统截断", visible)
        self.assertIn("鞋底靠近镜头前景", visible)

    def test_expert_team_does_not_turn_visual_evidence_keys_into_description(self):
        parsed = _parse_structured_interrogate_text(
            """{
              "visual_evidence": {
                "visible_body_range": "头部至大腿中部",
                "aspect_ratio": "竖幅",
                "support_points": "坐在金属架横梁",
                "hand_endpoints": "画面左侧手握红色塑料瓶",
                "foot_or_shoe_contact": "鞋子靠近镜头前景",
                "clothing_materials": "红色上衣和格纹短裙",
                "visible_text_confidence": 0.7,
                "nsfw_visible_evidence": "大腿皮肤可见",
                "foreground_background_regions": "背景玻璃幕墙"
              },
              "expert_review": {"summary": "初稿缺专家观点"},
              "keyword_prompt": ""
            }"""
        )

        self.assertNotIn("visible_body_range", json.dumps(parsed, ensure_ascii=False))
        self.assertNotIn('"visible_body_range": "头部至大腿中部"', json.dumps(parsed, ensure_ascii=False))
        self.assertIn("头部至大腿中部", parsed["prompt"])
        self.assertIn("坐在金属架横梁", parsed["prompt"])

    def test_final_prompt_is_not_clamped_after_expert_json_packaging(self):
        def fake_chat(messages, **kwargs):
            return """{
              "visual_evidence": {
                "aspect_ratio": "9:16",
                "visible_body_range": "头部到鞋子",
                "support_points": ["鞋底踩在碎石地面"],
                "hand_endpoints": ["画面右侧手靠近头发"],
                "foot_or_shoe_contact": ["黑色运动鞋接触碎石"],
                "clothing_materials": ["深蓝连帽卫衣", "黑色过膝丝袜", "黑色厚底运动鞋"],
                "visible_text_confidence": 0.3,
                "nsfw_visible_evidence": "日常服装",
                "foreground_background_regions": ["前景碎石", "背景海岸和阴天"]
              },
              "expert_observations": {
                "composition": {"构图": "竖幅手机图，人物近全身入镜，背景为岩石海岸，主体位于画面中心偏下，前景碎石延伸到鞋底位置，天空占上方大面积"},
                "photography_parameters": {"参数": "参考 35mm，f/2.8，1/250s，ISO 200，自然日光，手机感近距离拍摄，中等景深，背景仍保留可读海岸轮廓"},
                "color_light": {"颜色": "深蓝卫衣 #1B2740，黑色鞋袜 #08090B，灰色碎石 #6F7375，肤色暖白 #E6CDBB，天空冷灰 #AAB3B8"},
                "mood_style": {"风格": "手机感写实照片，阴天海岸，低对比自然色，日常休闲氛围，画面没有强烈棚拍感，整体柔和清冷"},
                "body_pose": {"姿势": "人物蹲在碎石海岸，鞋底踩地承重，膝盖弯曲靠近身体，躯干向镜头轻微前倾，画面右侧手靠近头发"},
                "expression_language": {"表情": "脸部朝向镜头，闭唇平静，眼神直视，齐刘海贴近额头，两颊有柔和粉色妆感，面部轮廓清晰"},
                "sexual_boundary": {"边界": "日常服装，未见成人裸露或性器官，大腿局部皮肤与过膝丝袜边界可见，但不构成 adult_nudity"},
                "clothing_makeup": {"服装": "深蓝连帽卫衣，黑色过膝丝袜，黑色厚底运动鞋，卫衣胸前有大号字母印花，丝袜贴肤并覆盖膝上区域"},
                "materials_texture": {"材质": "卫衣棉质哑光，丝袜贴肤微光，碎石粗糙颗粒，运动鞋皮革与橡胶边缘偏哑光，头发有细丝反光"}
              },
              "keyword_prompt": "碎石海岸蹲姿人物",
              "negative_prompt": ["1:1正方形"]
            }"""

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (768, 1280), (120, 130, 140)).save(image_path)
            result = run_llm_expert_image_interrogator(
                str(image_path),
                chat_fn=fake_chat,
                single_pass=True,
                include_quality=True,
            )

        self.assertGreater(len(result["prompt"]), 360)

    def test_reverse_prompt_skill_scores_known_replication_conflicts(self):
        structured = {
            "画面描述": {
                "构图镜头": {
                    "比例": "1:1 正方形",
                    "裁切边界": "画面主要聚焦于人物上半身至大腿区域",
                },
                "肢体动作": {
                    "整体姿态": "半蹲坐姿 (Half-crouching Sit)",
                    "支撑点": "双膝和小腿接触于前景岩石表面",
                    "腿部边界": "小腿和脚踝区域被黑色丝袜包裹",
                    "手臂端点": "右手手指触碰头部左上方发梢",
                },
                "服装妆容": {"鞋子": "黑色厚底运动鞋"},
                "性内容边界": {"NSFW/Adult_Nudity": "但丝袜覆盖至大腿中部"},
                "负面提示词": {"构图镜头": ["极端特写"]},
            }
        }

        report = validate_reverse_prompt_quality(structured, image_size=(591, 1280), expert_results=[])

        self.assertFalse(report["passed"])
        self.assertLess(report["score"], REPLICATION_TARGET_SCORE)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("aspect_ratio_conflict", codes)
        self.assertIn("nested_negative_prompt", codes)
        self.assertIn("pose_taxonomy_drift", codes)
        self.assertIn("support_point_conflict", codes)
        self.assertIn("occluded_ankle_overwrite", codes)
        self.assertIn("hand_endpoint_side_error", codes)
        self.assertIn("crop_visibility_conflict", codes)
        self.assertIn("nsfw_label_without_visible_evidence", codes)

    def test_reverse_prompt_skill_rejects_sparse_fallback_and_empty_experts(self):
        structured = {
            "画面描述": {
                "合并提示词": "亚洲女性半身特写，白色上衣，白色过膝丝袜，卧室背景"
            }
        }
        experts = [{"id": spec["id"], "label": spec["label"], "missing": True} for spec in IMAGE_INTERROGATE_EXPERTS]

        report = validate_reverse_prompt_quality(structured, image_size=(768, 1280), expert_results=experts)

        self.assertFalse(report["passed"])
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("sparse_fallback_structured_prompt", codes)
        self.assertIn("empty_expert_observations", codes)

    def test_reverse_prompt_skill_rejects_adult_nudity_without_positive_evidence(self):
        structured = {
            "画面描述": {
                "性内容边界": {
                    "可见事实": ["胸部轮廓清晰可见", "大腿内侧皮肤暴露"],
                    "标签": "NSFW / adult_nudity (轻微)",
                }
            },
            "负面提示词": {
                "性内容边界": ["完全裸露上半身", "过度暴露的私密部位"]
            },
        }

        report = validate_reverse_prompt_quality(structured, image_size=(768, 1280))

        self.assertFalse(report["passed"])
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("nsfw_label_without_visible_evidence", codes)

    def test_reverse_prompt_skill_rejects_bedroom_hand_and_crop_conflicts(self):
        structured = {
            "画面描述": {
                "场景": {"位置": "卧室床铺区域"},
                "肢体动作": {
                    "手臂端点": "双臂自然垂于身侧，左手抬至胸前区域",
                    "腿部边界": "白色过膝袜覆盖至大腿中部，膝盖可见",
                },
                "构图镜头": {"裁切边界": "头部到大腿中部"},
            }
        }

        report = validate_reverse_prompt_quality(structured, image_size=(768, 1280))

        self.assertFalse(report["passed"])
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("hand_action_conflict", codes)
        self.assertIn("bedroom_crop_underdescribed", codes)

    def test_reverse_prompt_skill_rejects_car_front_pose_missing(self):
        structured = {
            "画面描述": {
                "场景": {"位置": "汽车前排座椅，方向盘和车窗可见"},
                "人物": {"服装": "红色百褶短裙，黑色过膝丝袜"},
                "肢体动作": {"姿态": "普通坐姿，身体略微前倾"},
            }
        }

        report = validate_reverse_prompt_quality(structured, image_size=(591, 1280))

        self.assertFalse(report["passed"])
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("car_front_pose_missing", codes)

    def test_grouped_prompt_lifts_nested_negative_prompt_out_of_description(self):
        entry = {
            "outputs": {
                "6": {
                    "text": [
                        """{
                          "keyword_prompt": "卧室坐姿人像",
                          "structured_prompt": {
                            "画面描述": {
                              "场景": {"位置": "卧室床铺区域"},
                              "负面提示词": {"构图镜头": ["不要极端特写"]}
                            }
                          }
                        }"""
                    ]
                }
            }
        }

        result = extract_interrogate_result(entry)

        self.assertIn('"画面描述": {', result["structured_prompt_json"])
        self.assertIn('"负面提示词": {', result["structured_prompt_json"])
        self.assertNotIn('"画面描述": {\n    "场景": {\n      "位置": "卧室床铺区域"\n    },\n    "负面提示词"', result["structured_prompt_json"])
        self.assertIn("极端特写", result["negative_prompt"])

    def test_reverse_prompt_skill_requires_visual_evidence_for_expert_loop(self):
        report = validate_reverse_prompt_quality(
            {"画面描述": {"场景": {"位置": "卧室床铺区域"}}},
            image_size=(768, 1280),
            visual_evidence=None,
            require_visual_evidence=True,
        )

        self.assertFalse(report["passed"])
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("missing_visual_evidence", codes)

        partial = validate_reverse_prompt_quality(
            {"画面描述": {"场景": {"位置": "卧室床铺区域"}}},
            image_size=(768, 1280),
            visual_evidence={"aspect_ratio": {"value": "9:16", "confidence": 1.0, "allow_positive": True}},
            require_visual_evidence=True,
        )

        self.assertFalse(partial["passed"])
        partial_codes = {issue["code"] for issue in partial["issues"]}
        self.assertIn("incomplete_visual_evidence", partial_codes)

    def test_extract_interrogate_result_prefers_promptgen_and_keeps_wd14_metadata(self):
        entry = {
            "outputs": {
                "3": {"text": ["tag one, tag two"]},
                "7": {"text": ["a detailed prompt generated from image"]},
            }
        }

        result = extract_interrogate_result(entry)

        self.assertEqual(result["prompt"], "a detailed prompt generated from image")
        self.assertEqual(result["wd14_tags"], "tag one, tag two")
        self.assertEqual(result["promptgen"], "a detailed prompt generated from image")

    def test_extract_interrogate_result_removes_duplicate_caption_and_wrong_tag_tail(self):
        caption = (
            "A photograph of a futuristic sports car driving on a winding mountain road during sunrise or sunset. "
            "The car is positioned in the center of the image, with its sleek aerodynamic design highlighted by warm golden light."
        )
        duplicate = (
            "In this image, the car is positioned at the center of the frame, with its sleek and aerodynamic design "
            "highlighted by the warm, golden light of the sunrise or sunset."
        )
        wrong_tags = "1girl, solo, wings, outdoors, sky, wheel, no people, driving, mountain, road, fog"
        entry = {
            "outputs": {
                "3": {"text": [wrong_tags]},
                "7": {"text": [caption + "\n\n" + duplicate + "\n\n" + wrong_tags]},
            }
        }

        result = extract_interrogate_result(entry)

        self.assertEqual(result["prompt"], caption)
        self.assertNotIn("1girl", result["prompt"])
        self.assertNotIn("wings", result["prompt"])
        self.assertEqual(result["wd14_tags"], wrong_tags)

    def test_extract_interrogate_result_does_not_use_wd14_tag_line_as_prompt(self):
        entry = {
            "outputs": {
                "3": {"text": ["1girl, solo, wings, outdoors, sky, wheel, no people, driving, mountain, road, fog"]},
                "7": {"text": [""]},
            }
        }

        result = extract_interrogate_result(entry)

        self.assertEqual(result["prompt"], "")
        self.assertEqual(result["promptgen"], "")
        self.assertIn("1girl", result["wd14_tags"])

    def test_extract_interrogate_result_parses_bilingual_qwen_json(self):
        entry = {
            "outputs": {
                "3": {"text": ["car, road, mountain"]},
                "6": {
                    "text": [
                        [
                            """{
                          "keyword_prompt": "未来主义超跑，蜿蜒山路，金色日落，薄雾山峦",
                          "english_prompt": "futuristic hypercar, winding mountain road, golden sunset, misty mountains",
                          "structured_prompt": {
                            "subject": "未来主义超跑",
                            "scene": "蜿蜒山路，薄雾山峦",
                            "lighting": "金色日落光"
                          },
                          "structured_prompt_en": {
                            "subject": "futuristic hypercar",
                            "scene": "winding mountain road, misty mountains",
                            "lighting": "golden sunset light"
                          }
                        }"""
                        ]
                    ]
                },
            }
        }

        result = extract_interrogate_result(entry)

        self.assertEqual(result["prompt"], "未来主义超跑，蜿蜒山路，金色日落，薄雾山峦")
        self.assertEqual(result["prompt_zh"], "未来主义超跑，蜿蜒山路，金色日落，薄雾山峦")
        self.assertEqual(result["prompt_en"], "futuristic hypercar, winding mountain road, golden sunset, misty mountains")
        self.assertIn('"subject": "未来主义超跑"', result["structured_prompt_json"])
        self.assertIn('"subject": "futuristic hypercar"', result["structured_prompt_json_en"])

    def test_extract_interrogate_result_builds_plain_prompt_from_richer_json(self):
        entry = {
            "outputs": {
                "3": {"text": ["1girl, neon, portrait"]},
                "6": {
                    "text": [
                        """{
                          "keyword_prompt": "霓虹灯效女性肖像",
                          "english_prompt": "neon female portrait",
                          "structured_prompt": {
                            "subject": "女性面部特写",
                            "action": "凝视镜头",
                            "scene": "室内",
                            "composition": "正面特写，聚焦面部",
                            "lighting": "粉红色霓虹灯光照射，冷色调背景",
                            "style": "赛博朋克风格",
                            "color_palette": "粉红色与青蓝色调",
                            "important_details": [
                              "发饰为发光珊瑚状装饰",
                              "耳环为发光椭圆形",
                              "颈间缠绕发光灯串"
                            ]
                          },
                          "structured_prompt_en": {
                            "subject": "female facial close-up",
                            "action": "gazing at the camera",
                            "composition": "front-facing close-up, face in sharp focus",
                            "lighting": "pink neon lighting, cool-toned background",
                            "style": "cyberpunk style",
                            "important_details": [
                              "glowing coral-like hair ornament",
                              "glowing oval earrings"
                            ]
                          }
                        }"""
                    ]
                },
            }
        }

        result = extract_interrogate_result(entry)

        self.assertIn("女性面部特写", result["prompt"])
        self.assertIn("粉红色霓虹灯光照射", result["prompt"])
        self.assertIn("发饰为发光珊瑚状装饰", result["prompt"])
        self.assertNotEqual(result["prompt"], "霓虹灯效女性肖像")
        self.assertIn("female facial close-up", result["prompt_en"])
        self.assertIn("pink neon lighting", result["prompt_en"])

    def test_extract_interrogate_result_preserves_detailed_scene_layers(self):
        entry = {
            "outputs": {
                "3": {"text": ["portrait, window, room"]},
                "6": {
                    "text": [
                        """{
                          "keyword_prompt": "窗边少女肖像，室内晨光",
                          "english_prompt": "girl portrait beside a window, morning indoor light",
                          "structured_prompt": {
                            "subject": "窗边少女",
                            "subject_attributes": "黑色长发，柔和表情，正面看向镜头",
                            "foreground": "浅色窗台与人物肩部占据画面下方",
                            "midground": "人物坐在窗边，白色衣物形成柔和轮廓",
                            "background": "窗外有模糊绿植和明亮玻璃反光",
                            "camera_lens": "中近景人像，轻微俯视，浅景深",
                            "mood_atmosphere": "安静、清晨、柔和",
                            "environment_objects": ["木质窗框", "窗外绿植", "室内白色墙面"],
                            "quality_notes": ["皮肤高光细腻", "背景虚化自然"],
                            "important_details": [
                              "发丝边缘被窗光勾亮",
                              "衣物褶皱沿肩部下垂",
                              "窗框竖线切分背景空间"
                            ]
                          },
                          "structured_prompt_en": {
                            "subject": "girl beside a window",
                            "subject_attributes": "long black hair, soft expression, looking at camera",
                            "foreground": "light windowsill and shoulders in the lower frame",
                            "background": "blurred greenery and bright glass reflections outside",
                            "camera_lens": "medium-close portrait, shallow depth of field",
                            "environment_objects": ["wooden window frame", "greenery outside"],
                            "quality_notes": ["delicate skin highlights"]
                          }
                        }"""
                    ]
                },
            }
        }

        result = extract_interrogate_result(entry)

        self.assertIn("浅色窗台", result["prompt"])
        self.assertIn("窗外有模糊绿植", result["prompt"])
        self.assertIn("中近景人像", result["prompt"])
        self.assertIn('"foreground": "浅色窗台与人物肩部占据画面下方"', result["structured_prompt_json"])
        self.assertIn('"camera_lens": "medium-close portrait, shallow depth of field"', result["structured_prompt_json_en"])
        self.assertIn("wooden window frame", result["prompt_en"])

    def test_extract_interrogate_result_expands_sparse_portrait_caption_from_structured_fields(self):
        entry = {
            "outputs": {
                "6": {
                    "text": [
                        """{
                          "keyword_prompt": "年轻女性，浅蓝色连衣裙，自然光",
                          "english_prompt": "young woman, light blue dress, natural light",
                          "structured_prompt": {
                            "subject": "年轻亚洲女性站立人像",
                            "subject_attributes": "长卷黑发，正面看向镜头，柔和自然表情，淡妆，五官清晰",
                            "action": "双臂自然下垂，手指贴近大腿两侧，身体略微前倾，双腿并拢站立",
                            "scene": "浅蓝色无缝影棚背景",
                            "composition": "竖幅全身到大腿下方人像，人物居中，占据画面主要高度，头顶与两侧留有干净留白",
                            "camera_lens": "轻微俯视的中全身人像视角，正面机位，柔和浅景深",
                            "lighting": "高调柔和漫射光，低对比阴影，皮肤高光平滑",
                            "style": "写实棚拍人像，略带柔焦的 AI 生成质感",
                            "color_palette": "浅蓝、冷白、自然肤色、深黑发色",
                            "materials_textures": ["浅蓝色针织纹理", "贴身连衣裙布料细密竖向纹理"],
                            "clothing_accessories": ["浅蓝色无袖贴身迷你连衣裙", "抹胸式平直领口", "裙摆到大腿上方"],
                            "important_details": [
                              "头发从右侧覆盖部分额头与脸颊",
                              "发尾在肩部和胸前形成卷曲弧线",
                              "肩膀与锁骨区域清晰可见",
                              "裙身腰部和腹部有细微褶皱",
                              "背景没有道具和可读文字",
                              "手指自然伸展"
                            ],
                            "constraints": ["不要裁成头像特写", "不要新增室内家具", "保持纯浅蓝背景和服装纹理"]
                          },
                          "structured_prompt_en": {
                            "subject": "young Asian woman standing portrait",
                            "composition": "vertical full-to-thigh portrait, centered subject, clean negative space",
                            "camera_lens": "slightly high-angle medium-full portrait view",
                            "clothing_accessories": ["light blue sleeveless fitted mini dress", "straight strapless neckline"],
                            "important_details": ["visible knit texture", "hands beside thighs"]
                          }
                        }"""
                    ]
                }
            }
        }

        result = extract_interrogate_result(entry)

        self.assertIn("竖幅全身到大腿下方人像", result["prompt"])
        self.assertIn("浅蓝色无缝影棚背景", result["prompt"])
        self.assertIn("抹胸式平直领口", result["prompt"])
        self.assertNotIn("不要裁成头像特写", result["prompt"])
        self.assertNotIn("保持纯浅蓝背景和服装纹理", result["prompt"])
        self.assertIn("头像特写", result["negative_prompt"])
        self.assertIn("室内家具", result["negative_prompt"])
        self.assertNotIn("不要", result["negative_prompt"])
        self.assertNotIn("保持纯浅蓝背景和服装纹理", result["negative_prompt"])
        self.assertNotEqual(result["prompt"], "年轻女性，浅蓝色连衣裙，自然光")
        self.assertIn('"composition": "竖幅全身到大腿下方人像', result["structured_prompt_json"])
        self.assertIn('"constraints": [', result["structured_prompt_json"])
        self.assertIn("保持纯浅蓝背景和服装纹理", result["structured_prompt_json"])

    def test_extract_interrogate_result_preserves_pose_and_exposed_body_details(self):
        entry = {
            "outputs": {
                "6": {
                    "text": [
                        """{
                          "keyword_prompt": "女性泳装人像，海边站姿",
                          "english_prompt": "woman in swimsuit portrait, standing at the beach",
                          "structured_prompt": {
                            "subject": "成年女性海边人像",
                            "subject_attributes": "长发，正面看向镜头，自然表情",
                            "action": "单腿承重站立，身体轻微侧转，一只手扶住帽檐，另一只手自然垂在身侧",
                            "pose_details": "肩膀打开，腰部轻微扭转，髋部偏向画面右侧，膝盖微弯，手指松弛",
                            "exposed_body_details": "肩颈、锁骨、手臂、腹部和大腿大面积可见，穿着比基尼泳装但未见完全裸露",
                            "clothing_accessories": ["比基尼上衣", "高腰泳装下装", "宽檐草帽"],
                            "important_details": ["腹部皮肤受侧光照亮", "大腿和手臂有海边暖光高光"]
                          },
                          "structured_prompt_en": {
                            "subject": "adult woman beach portrait",
                            "pose_details": "one leg bearing weight, shoulders open, waist slightly twisted, relaxed fingers",
                            "exposed_body_details": "visible shoulders, collarbone, arms, abdomen, and thighs, bikini swimwear, no full nudity"
                          }
                        }"""
                    ]
                }
            }
        }

        result = extract_interrogate_result(entry)

        self.assertIn("腰部轻微扭转", result["prompt"])
        self.assertIn("肩颈、锁骨、手臂、腹部和大腿大面积可见", result["prompt"])
        self.assertIn('"pose_details": "肩膀打开，腰部轻微扭转', result["structured_prompt_json"])
        self.assertIn('"exposed_body_details": "visible shoulders', result["structured_prompt_json_en"])

    def test_extract_interrogate_result_preserves_nsfw_content_details(self):
        entry = {
            "outputs": {
                "6": {
                    "text": [
                        """{
                          "keyword_prompt": "成人女性正面站立，棚拍背景，局部裸露",
                          "english_prompt": "adult woman standing forward, studio background, partial nudity",
                          "structured_prompt": {
                            "subject": "成人女性",
                            "pose_details": "正面站立，双臂自然下垂",
                            "exposed_body_details": "胸部、腹部和大腿可见，衣物覆盖范围有限",
                            "nsfw_content_details": "成人裸露内容，乳头和外阴区域可见，未出现性行为",
                            "important_details": ["胸部裸露边界清晰", "私密部位可见但无互动行为"]
                          },
                          "structured_prompt_en": {
                            "subject": "adult woman",
                            "pose_details": "standing forward, arms relaxed at both sides",
                            "exposed_body_details": "chest, abdomen, and thighs visible, limited clothing coverage",
                            "nsfw_content_details": "adult nudity, visible nipples and vulva area, no sexual act shown"
                          }
                        }"""
                    ]
                }
            }
        }

        result = extract_interrogate_result(entry)

        self.assertIn("成人裸露内容", result["prompt"])
        self.assertIn("乳头和外阴区域可见", result["prompt"])
        self.assertIn('"nsfw_content_details": "成人裸露内容', result["structured_prompt_json"])
        self.assertIn('"nsfw_content_details": "adult nudity', result["structured_prompt_json_en"])

    def test_extract_interrogate_result_preserves_body_mechanics_and_adult_nudity_labels(self):
        entry = {
            "outputs": {
                "6": {
                    "text": [
                        """{
                          "keyword_prompt": "成人女性裸露站姿，正面棚拍",
                          "english_prompt": "adult woman nude standing pose, frontal studio photo",
                          "structured_prompt": {
                            "subject": "成人女性",
                            "facial_expression_details": "嘴唇微张，眉毛放松，眼睛直视镜头",
                            "pose_details": "正面站立，脊柱直立，肩膀水平，髋部轻微左倾",
                            "hand_details": "左手垂在左大腿外侧，右手手指弯曲贴近髋部",
                            "foot_details": "双脚可见，左脚承重，右脚脚尖略向外",
                            "joint_body_mechanics": "肘关节轻微弯曲，膝关节自然伸直，重心落在左腿",
                            "exposed_body_details": "胸部、腹部、臀部和大腿完全裸露",
                            "intimate_body_details": "乳头、外阴轮廓和臀沟可见，无遮挡",
                            "nsfw_content_details": "NSFW，adult_nudity，成人全裸内容，乳头和外阴轮廓可见，未出现性行为",
                            "content_safety_labels": ["NSFW", "adult_nudity"]
                          },
                          "structured_prompt_en": {
                            "subject": "adult woman",
                            "facial_expression_details": "lips slightly parted, relaxed brows, eyes looking at the camera",
                            "hand_details": "left hand hanging beside the left thigh, right fingers bent near the hip",
                            "foot_details": "both feet visible, left foot bearing weight, right toes angled outward",
                            "joint_body_mechanics": "elbows slightly bent, knees naturally extended, weight on the left leg",
                            "intimate_body_details": "nipples, vulva outline, and gluteal cleft visible, unobstructed",
                            "nsfw_content_details": "NSFW, adult_nudity, adult full nudity, visible nipples and vulva outline, no sexual act shown",
                            "content_safety_labels": ["NSFW", "adult_nudity"]
                          }
                        }"""
                    ]
                }
            }
        }

        result = extract_interrogate_result(entry)

        self.assertIn("左手垂在左大腿外侧", result["prompt"])
        self.assertIn("右脚脚尖略向外", result["prompt"])
        self.assertIn("乳头、外阴轮廓和臀沟可见", result["prompt"])
        self.assertIn("NSFW", result["prompt"])
        self.assertIn("adult_nudity", result["prompt"])
        self.assertIn('"hand_details": "左手垂在左大腿外侧', result["structured_prompt_json"])
        self.assertIn('"foot_details": "双脚可见', result["structured_prompt_json"])
        self.assertIn('"joint_body_mechanics": "肘关节轻微弯曲', result["structured_prompt_json"])
        self.assertIn('"facial_expression_details": "嘴唇微张', result["structured_prompt_json"])
        self.assertIn('"intimate_body_details": "乳头、外阴轮廓和臀沟可见', result["structured_prompt_json"])
        self.assertIn('"content_safety_labels": [', result["structured_prompt_json"])
        self.assertIn('"hand_details": "left hand hanging', result["structured_prompt_json_en"])

    def test_extract_interrogate_result_removes_unseen_body_part_mentions(self):
        entry = {
            "outputs": {
                "6": {
                    "text": [
                        """{
                          "keyword_prompt": "粉色衣物人物，近距离低角度抬腿构图，室内门口",
                          "english_prompt": "person in pink outfit, close low-angle raised-leg composition, indoor doorway",
                          "structured_prompt": {
                            "subject": "年龄不可确认的人物，粉色短袖上衣和短裙或短裤疑似",
                            "pose_details": "一条腿高抬贴近镜头，身体侧向后方，躯干局部可见",
                            "foot_details": "双脚均在画面外不可见",
                            "joint_body_mechanics": "抬起腿的髋关节大幅屈曲，膝部靠近镜头形成近大远小透视",
                            "facial_expression_details": "脸部上半部分被裁切，表情不可准确判断",
                            "occlusion_crop_details": "头顶、眼睛和双脚被画幅裁切；胯部和内侧大腿被抬起的大腿及粉色衣物遮挡，隐私部位不可见",
                            "exposed_body_details": "腹部、腰侧和大腿大面积皮肤可见，但无可见性器官",
                            "camera_lens": "手机近距离低角度仰拍，前景大腿占据画面右侧大部分区域"
                          }
                        }"""
                    ]
                }
            }
        }

        result = extract_interrogate_result(entry)

        self.assertNotIn("双脚", result["prompt"])
        self.assertNotIn("隐私部位", result["prompt"])
        self.assertNotIn("性器官", result["prompt"])
        self.assertIn("手机近距离低角度仰拍", result["prompt"])
        self.assertNotIn("双脚", result["structured_prompt_json"])
        self.assertNotIn("隐私部位", result["structured_prompt_json"])
        self.assertNotIn("无可见性器官", result["structured_prompt_json"])
        self.assertEqual(_clean_negative_prompt_text("不要露出脸部/避免双腿交叉"), "脸部，双腿交叉")
        self.assertEqual(_clean_negative_prompt_text("不要写双脚"), "双脚")

    def test_extract_interrogate_result_preserves_explicit_adult_sexual_details(self):
        entry = {
            "outputs": {
                "6": {
                    "text": [
                        """{
                          "keyword_prompt": "成人女性，明确成人裸露，性器官可见，手部与性器官接触",
                          "english_prompt": "adult woman, explicit adult nudity, genitals visible, hand contacting genitals",
                          "structured_prompt": {
                            "subject": "成人女性",
                            "hand_details": "右手位于两腿之间，手指接触外阴区域",
                            "genital_details": "外阴和阴唇可见，局部发红",
                            "sexual_act_details": "手指插入阴道内，属于明确成人性行为细节",
                            "fluid_contact_details": "外阴和手指附近可见白色液体附着",
                            "intimate_body_details": "外阴、阴唇和阴道入口可见，无遮挡",
                            "nsfw_content_details": "NSFW，adult_nudity，explicit_sexual_content，成人裸露，性器官可见，手指插入阴道，可见白色液体",
                            "content_safety_labels": ["NSFW", "adult_nudity", "explicit_sexual_content", "visible_genitals", "sexual_fluid"]
                          },
                          "structured_prompt_en": {
                            "subject": "adult woman",
                            "hand_details": "right hand between the legs, fingers contacting the vulva area",
                            "genital_details": "vulva and labia visible, localized redness",
                            "sexual_act_details": "finger inserted into the vagina, explicit adult sexual act detail",
                            "fluid_contact_details": "white fluid visible near the vulva and fingers",
                            "intimate_body_details": "vulva, labia, and vaginal opening visible, unobstructed",
                            "nsfw_content_details": "NSFW, adult_nudity, explicit_sexual_content, adult nudity, visible genitals, finger inserted into vagina, white fluid visible",
                            "content_safety_labels": ["NSFW", "adult_nudity", "explicit_sexual_content", "visible_genitals", "sexual_fluid"]
                          }
                        }"""
                    ]
                }
            }
        }

        result = extract_interrogate_result(entry)

        self.assertIn("手指插入阴道内", result["prompt"])
        self.assertIn("白色液体", result["prompt"])
        self.assertIn("explicit_sexual_content", result["prompt"])
        self.assertIn('"genital_details": "外阴和阴唇可见', result["structured_prompt_json"])
        self.assertIn('"sexual_act_details": "手指插入阴道内', result["structured_prompt_json"])
        self.assertIn('"fluid_contact_details": "外阴和手指附近可见白色液体附着', result["structured_prompt_json"])
        self.assertIn('"sexual_fluid"', result["structured_prompt_json"])
        self.assertIn('"sexual_act_details": "finger inserted into the vagina', result["structured_prompt_json_en"])

    def test_extract_interrogate_result_splits_positive_and_negative_prompt(self):
        entry = {
            "outputs": {
                "6": {
                    "text": [
                        """{
                          "keyword_prompt": "东亚女性，粉色丝绸套装，抬腿构图",
                          "english_prompt": "East Asian woman, pink silk outfit, high leg composition",
                          "structured_prompt": {
                            "subject": "东亚女性",
                            "pose_details": "一条腿高抬靠近镜头，身体后仰，躯干被局部裁切",
                            "hand_details": "右手扶在抬起的大腿旁",
                            "exposed_body_details": "大腿和腹部皮肤大面积可见",
                            "scene": "室内门口，右侧有蓝色房间",
                            "constraints": ["不要裁成头像特写", "避免新增道具", "保持原有蓝色门框"],
                            "negative_prompt": ["不要多余人物", "不要改变粉色衣服"]
                          }
                        }"""
                    ]
                }
            }
        }

        result = extract_interrogate_result(entry)

        self.assertIn("一条腿高抬靠近镜头", result["prompt"])
        self.assertNotIn("不要裁成头像特写", result["prompt"])
        self.assertIn("头像特写", result["negative_prompt"])
        self.assertIn("道具", result["negative_prompt"])
        self.assertIn("多余人物", result["negative_prompt"])
        self.assertNotIn("不要", result["negative_prompt"])
        self.assertNotIn("避免", result["negative_prompt"])
        self.assertNotIn("保持原有蓝色门框", result["negative_prompt"])

    def test_extract_interrogate_result_repairs_missing_final_json_brace(self):
        entry = {
            "outputs": {
                "6": {
                    "text": [
                        """{
                          "keyword_prompt": "几何人物剪影，室内色块，背景分割",
                          "english_prompt": "geometric human silhouettes, indoor color blocks, divided background",
                          "structured_prompt": {
                            "subject": "几何人物剪影",
                            "foreground": "左侧矩形框和圆形物体",
                            "background": "蓝色与米色背景分割",
                            "important_details": ["深色连接线", "右上角有文字"]
                          },
                          "structured_prompt_en": {
                            "subject": "geometric human silhouettes",
                            "foreground": "left rectangular frame and circular object",
                            "background": "blue and beige divided background"
                          }"""
                    ]
                }
            }
        }

        result = extract_interrogate_result(entry)

        self.assertIn("几何人物剪影", result["prompt"])
        self.assertIn("左侧矩形框", result["prompt"])
        self.assertIn('"background": "blue and beige divided background"', result["structured_prompt_json_en"])

    def test_llm_interrogator_requests_long_detail_budget(self):
        calls = []

        def fake_chat(messages, **kwargs):
            calls.append({"messages": messages, **kwargs})
            return """{
              "keyword_prompt": "窗边少女，前景窗台，背景绿植，柔和晨光",
              "english_prompt": "girl beside a window, foreground windowsill, greenery background, soft morning light",
              "structured_prompt": {
                "subject": "窗边少女",
                "foreground": "浅色窗台",
                "background": "窗外绿植",
                "camera_lens": "中近景，浅景深",
                "important_details": ["发丝边缘被光照亮", "玻璃有柔和反光"]
              },
              "structured_prompt_en": {
                "subject": "girl beside a window",
                "foreground": "light windowsill",
                "background": "greenery outside the window",
                "camera_lens": "medium-close, shallow depth of field",
                "important_details": ["rim-lit hair edges"]
              }
            }"""

        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "sample.jpg"
            image.write_bytes(b"fake image bytes")
            result = run_llm_image_interrogator(str(image), chat_fn=fake_chat)

        self.assertEqual(calls[0]["max_tokens"], 3072)
        self.assertEqual(calls[0]["messages"][0]["role"], "system")
        self.assertIn("Do not reason", calls[0]["messages"][0]["content"])
        self.assertIn("foreground", calls[0]["messages"][1]["content"][0]["text"])
        self.assertIn("浅色窗台", result["prompt"])
        self.assertIn("medium-close", result["structured_prompt_json_en"])

    def test_llm_interrogator_repairs_phantom_array_close_strings(self):
        def fake_chat(_messages, **_kwargs):
            return """{
              "keyword_prompt": "年轻女性，正面站立，白色蕾丝上衣，格纹迷你裙，城市街道",
              "english_prompt": "young woman standing forward, white lace top, plaid mini skirt, city street",
              "structured_prompt": {
                "subject": "年轻女性",
                "action": "站立",
                "pose_details": "身体正面朝向镜头，双臂自然垂下，双手放松",
                "exposed_body_details": "肩颈、低胸区域、腰腹和大腿上部可见，白色蕾丝低胸上衣覆盖胸部，格纹迷你裙覆盖腰胯",
                "important_details": [
                  "双马尾发型",
                  "白色蕾丝镂空纹理",
                  "上衣低胸领口",
                  "红蓝格纹迷你裙",
                  "手臂自然下垂",
                  "整体画面色彩饱和度高，明亮","],"visible_text":["霓虹灯招牌"],
                "quality_notes": ["照片级画质"]
              },
              "structured_prompt_en": {
                "subject": "young woman",
                "important_details": [
                  "twin tails",
                  "white lace open-knit texture",
                  "low-cut neckline","],"visible_text":["neon signs"],
                "quality_notes": ["photo-realistic quality"]
              }
            }"""

        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "sample.jpg"
            image.write_bytes(b"fake image bytes")
            result = run_llm_image_interrogator(str(image), chat_fn=fake_chat)

        self.assertIn("身体正面朝向镜头", result["prompt"])
        self.assertIn("低胸区域", result["prompt"])
        self.assertIn('"pose_details": "身体正面朝向镜头', result["structured_prompt_json"])
        self.assertIn('"visible_text": [', result["structured_prompt_json_en"])

    def test_llm_interrogator_uses_keyword_prompt_when_near_json_is_malformed(self):
        def fake_chat(_messages, **_kwargs):
            return (
                '{"keyword_prompt":"年轻女性，正面站立，双臂自然下垂，白色蕾丝上衣，'
                '腹部和大腿可见","english_prompt":"young woman standing forward, arms relaxed, '
                'white lace top, abdomen and thighs visible","structured_prompt":{"subject":"年轻女性",'
                '"pose_details":"身体正面朝向镜头，双臂自然下垂",'
                '"exposed_body_details":"腹部和大腿可见",'
                '"nsfw_content_details":"成人局部裸露内容，未出现性行为",'
                '"important_details":["白色蕾丝","],"visible_text":["霓虹灯"],'
                '"structured_prompt_en":{"subject":"young woman",'
                '"pose_details":"body facing the camera, arms relaxed",'
                '"exposed_body_details":"abdomen and thighs visible",'
                '"nsfw_content_details":"adult partial nudity, no sexual act shown"}'
            )

        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "sample.jpg"
            image.write_bytes(b"fake image bytes")
            result = run_llm_image_interrogator(str(image), chat_fn=fake_chat)

        self.assertIn("身体正面朝向镜头", result["prompt"])
        self.assertIn("成人局部裸露内容", result["prompt"])
        self.assertIn('"nsfw_content_details": "成人局部裸露内容', result["structured_prompt_json"])
        self.assertIn("arms relaxed", result["prompt_en"])
        self.assertIn('"nsfw_content_details": "adult partial nudity', result["structured_prompt_json_en"])

    def test_prepare_interrogate_image_downscales_large_upload(self):
        try:
            from PIL import Image
        except Exception:
            self.skipTest("Pillow is not available")

        with tempfile.TemporaryDirectory() as td:
            input_dir = Path(td)
            src = input_dir / "u1" / "2026-05-21" / "large.png"
            src.parent.mkdir(parents=True)
            Image.new("RGB", (3200, 2400), (40, 80, 120)).save(src)

            result = prepare_interrogate_image("u1/2026-05-21/large.png", str(input_dir), max_side=1280)

            self.assertTrue(result["optimized"])
            self.assertEqual(result["original_width"], 3200)
            self.assertEqual(result["original_height"], 2400)
            self.assertLessEqual(max(result["width"], result["height"]), 1280)
            self.assertTrue((input_dir / result["filename"]).is_file())
            self.assertIn("/_interrogate/", result["filename"])

    def test_prepare_interrogate_image_keeps_small_upload(self):
        try:
            from PIL import Image
        except Exception:
            self.skipTest("Pillow is not available")

        with tempfile.TemporaryDirectory() as td:
            input_dir = Path(td)
            src = input_dir / "u1" / "2026-05-21" / "small.png"
            src.parent.mkdir(parents=True)
            Image.new("RGB", (512, 384), (40, 80, 120)).save(src)

            result = prepare_interrogate_image("u1/2026-05-21/small.png", str(input_dir), max_side=1280)

            self.assertFalse(result["optimized"])
            self.assertEqual(result["filename"], "u1/2026-05-21/small.png")
            self.assertEqual(result["width"], 512)
            self.assertEqual(result["height"], 384)

_RETIRED_IMAGE_REVERSE_INTERNAL_TEST_PATTERNS = (
    "run_llm_expert_image_interrogator",
    "staged_expert_interrogator",
    "single_pass_expert",
    "expert_team",
    "detailed_analysis",
    "single_expert_visual_spec",
    "llm_interrogator",
)

for _name in dir(PromptInterrogatorTests):
    if not _name.startswith("test_"):
        continue
    if any(_pattern in _name for _pattern in _RETIRED_IMAGE_REVERSE_INTERNAL_TEST_PATTERNS):
        setattr(
            PromptInterrogatorTests,
            _name,
            unittest.skip("retired by image_reverse three-pipeline rewrite; covered by tests.test_image_reverse_*")(
                getattr(PromptInterrogatorTests, _name)
            ),
        )


if __name__ == "__main__":
    unittest.main()
