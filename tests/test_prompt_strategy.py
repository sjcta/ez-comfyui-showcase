import unittest
import json

import app


class PromptStrategyTests(unittest.TestCase):
    def test_xhs_cover_strategy_enhances_positive_and_negative_prompts(self):
        workflow = {
            "1": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "一只橘猫"},
                "_meta": {"title": "Positive"},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "bad quality"},
                "_meta": {"title": "Negative"},
            },
        }
        fields = {
            "1::text": "一只橘猫",
            "2::text": "bad quality",
            "__user_prompt": "一只橘猫",
        }

        out = app._apply_prompt_strategy_to_fields(workflow, fields, "t2i_flux.json", "xhs_cover")

        self.assertTrue(out["1::text"].startswith("一只橘猫"))
        self.assertIn("小红书封面构图", out["1::text"])
        self.assertNotIn("硬约束", out["1::text"])
        self.assertIn("tiny unreadable text", out["2::text"])
        self.assertEqual(out["__user_prompt_original"], "一只橘猫")
        self.assertIn("手机首屏识别度优先", out["__user_prompt"])
        self.assertEqual(out["__prompt_strategy_id"], "xhs_cover")
        self.assertEqual(out["__prompt_strategy_label"], "小红书封面")
        self.assertEqual(out["__prompt_strategy_engine"], "deterministic")

    def test_auto_strategy_uses_reference_edit_when_reference_image_exists(self):
        workflow = {
            "1": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "把衣服换成绿色"},
                "_meta": {"title": "Positive"},
            },
            "3": {
                "class_type": "LoadImage",
                "inputs": {"image": ""},
                "_meta": {"title": "Reference Image"},
            },
        }
        fields = {
            "1::text": "把衣服换成绿色",
            "3::image": "input/example.png",
            "__user_prompt": "把衣服换成绿色",
        }

        out = app._apply_prompt_strategy_to_fields(workflow, fields, "i2i_qwen_edit.json", "auto")

        self.assertEqual(out["__prompt_strategy_requested"], "auto")
        self.assertEqual(out["__prompt_strategy_id"], "reference_edit")
        self.assertIn("以参考图为主", out["1::text"])
        self.assertNotIn("硬约束", out["1::text"])
        self.assertIn("只执行用户指定修改：把衣服换成绿色", out["1::text"])

    def test_auto_strategy_leaves_upscale_prompt_unchanged(self):
        workflow = {
            "1": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "修复细节"},
                "_meta": {"title": "Positive"},
            }
        }
        fields = {"1::text": "修复细节", "__user_prompt": "修复细节"}

        out = app._apply_prompt_strategy_to_fields(workflow, fields, "seedvr_upscale.json", "auto")

        self.assertEqual(out["1::text"], "修复细节")
        self.assertNotIn("__prompt_strategy_id", out)

    def test_strategy_preserves_json_prompt_payloads(self):
        workflow = {
            "1": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": ""},
                "_meta": {"title": "Positive"},
            }
        }
        prompt = '一只"橘猫"'
        fields = {
            "1::text": json.dumps({"prompt": prompt, "style": {"label": "写实"}}, ensure_ascii=False),
            "__user_prompt": prompt,
        }

        out = app._apply_prompt_strategy_to_fields(workflow, fields, "t2i_flux.json", "realistic_scene")
        parsed = json.loads(out["1::text"])

        self.assertEqual(parsed["style"]["label"], "写实")
        self.assertIn('一只"橘猫"', parsed["prompt"])
        self.assertIn("写实摄影质感", parsed["prompt"])

    def test_strategy_updates_final_workflow_prompt_field(self):
        workflow = {
            "1": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "一只橘猫"},
                "_meta": {"title": "Positive"},
            }
        }
        fields = {
            "1::text": "一只橘猫",
            "__user_prompt": "一只橘猫",
        }

        strategy_fields = app._apply_prompt_strategy_to_fields(workflow, fields, "t2i_flux.json", "xhs_cover")
        normalized = app._normalize_workflow_field_values(workflow, strategy_fields, "t2i_flux.json", allow_llm=False)
        for key, val in normalized.items():
            if "::" not in key:
                continue
            nid, field = key.split("::", 1)
            if field.startswith("__"):
                continue
            if nid in workflow and "inputs" in workflow[nid]:
                workflow[nid]["inputs"][field] = val

        self.assertTrue(workflow["1"]["inputs"]["text"].startswith("一只橘猫"))
        self.assertNotIn("硬约束", workflow["1"]["inputs"]["text"])
        self.assertIn("手机首屏识别度优先", workflow["1"]["inputs"]["text"])
        self.assertEqual(normalized["__prompt_strategy_enhanced_prompt"], workflow["1"]["inputs"]["text"])

    def test_portrait_strategy_removes_conflicting_comic_terms(self):
        workflow = {
            "1": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "二次元漫画女孩，日漫风格，大眼睛"},
                "_meta": {"title": "Positive"},
            }
        }
        fields = {
            "1::text": "二次元漫画女孩，日漫风格，大眼睛",
            "__user_prompt": "二次元漫画女孩，日漫风格，大眼睛",
        }

        out = app._apply_prompt_strategy_to_fields(workflow, fields, "t2i_flux.json", "portrait")

        self.assertIn("女孩", out["1::text"])
        self.assertIn("真实人物写真质感", out["1::text"])
        self.assertNotRegex(out["1::text"], r"二次元|漫画|日漫|动漫|卡通|anime|manga|comic|cartoon")
        self.assertNotRegex(out["__prompt_strategy_enhanced_prompt"], r"二次元|漫画|日漫|动漫|卡通")

    def test_strategy_can_use_llm_lingzao_visual_brief(self):
        workflow = {
            "1": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "一只橘猫"},
                "_meta": {"title": "Positive"},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "bad quality"},
                "_meta": {"title": "Negative"},
            },
        }
        fields = {
            "1::text": "一只橘猫",
            "2::text": "bad quality",
            "__user_prompt": "一只橘猫",
        }

        def fake_chat(messages, **kwargs):
            self.assertEqual(kwargs.get("response_format"), {"type": "json_object"})
            self.assertIn("If the user_prompt is Chinese", messages[0]["content"])
            self.assertIn("one-pass hard generation instruction", messages[0]["content"])
            self.assertIn("Do not add titles", messages[0]["content"])
            self.assertIn("resolve style conflicts", messages[0]["content"])
            payload = json.loads(messages[-1]["content"])
            self.assertEqual(payload["selected_strategy"]["id"], "xhs_cover")
            self.assertEqual(payload["lingzao_visual_contract"]["platform"], "小红书")
            return json.dumps(
                {
                    "visual_brief": {
                        "platform": "小红书",
                        "format": "手机竖屏封面",
                        "style_group": "Lingzao XHS cover",
                        "image_purpose": "让橘猫成为首屏点击理由",
                        "audience": "喜欢宠物内容的用户",
                        "main_visual_subject": "一只橘猫",
                        "on_image_text": "",
                        "text_hierarchy": "预留标题安全区，不生成随机字",
                        "layout_structure": "橘猫大主体居中，背景干净",
                        "color_typography": "明亮暖色，清爽对比",
                        "materials_or_reference_role": "无参考图，按文本生成",
                        "negative_constraints": "random text, watermark",
                        "success_criteria": ["一秒看懂橘猫", "背景不乱"],
                    },
                    "final_prompt": "小红书封面成片硬约束：一只橘猫作为大主体居中，明亮干净背景，预留标题安全区但不要生成随机文字。",
                    "negative_prompt": "random text, watermark, deformed animal",
                },
                ensure_ascii=False,
            )

        app._PROMPT_STRATEGY_LLM_CACHE.clear()
        out = app._apply_prompt_strategy_to_fields(
            workflow,
            fields,
            "t2i_flux.json",
            "xhs_cover",
            allow_llm=True,
            chat_fn=fake_chat,
        )

        self.assertTrue(out["1::text"].startswith("一只橘猫作为大主体居中"))
        self.assertNotIn("硬约束", out["1::text"])
        self.assertIn("手机首屏一秒识别主题", out["1::text"])
        self.assertIn("random text", out["2::text"])
        self.assertEqual(out["__prompt_strategy_engine"], "llm")
        self.assertEqual(out["__prompt_strategy_analysis_version"], app.PROMPT_STRATEGY_ANALYSIS_VERSION)
        brief = json.loads(out["__prompt_strategy_brief"])
        self.assertEqual(brief["style_group"], "Lingzao XHS cover")
        self.assertEqual(brief["main_visual_subject"], "一只橘猫")

    def test_strategy_falls_back_when_llm_compile_fails(self):
        workflow = {
            "1": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "一只橘猫"},
                "_meta": {"title": "Positive"},
            }
        }
        fields = {"1::text": "一只橘猫", "__user_prompt": "一只橘猫"}

        def failing_chat(messages, **kwargs):
            raise RuntimeError("llm offline")

        app._PROMPT_STRATEGY_LLM_CACHE.clear()
        out = app._apply_prompt_strategy_to_fields(
            workflow,
            fields,
            "t2i_flux.json",
            "xhs_cover",
            allow_llm=True,
            chat_fn=failing_chat,
        )

        self.assertEqual(out["__prompt_strategy_engine"], "deterministic")
        self.assertIn("小红书封面构图", out["1::text"])
        self.assertIn("llm offline", out["__prompt_strategy_llm_error"])

    def test_strategy_optimizer_returns_visible_prompt_result(self):
        workflow = {
            "1": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "一只橘猫"},
                "_meta": {"title": "Positive"},
            }
        }
        fields = {"1::text": "一只橘猫"}

        result = app._prompt_strategy_optimize_result(
            "一只橘猫",
            "xhs_cover",
            "t2i_flux.json",
            workflow,
            fields,
            allow_llm=False,
        )

        self.assertTrue(result["changed"])
        self.assertEqual(result["prompt_strategy"], "xhs_cover")
        self.assertEqual(result["prompt_strategy_label"], "小红书封面")
        self.assertEqual(result["prompt_strategy_engine"], "deterministic")
        self.assertTrue(result["optimized_prompt"].startswith("一只橘猫"))
        self.assertIn("小红书封面构图", result["optimized_prompt"])
        self.assertNotIn("硬约束", result["optimized_prompt"])
        self.assertIn("手机首屏识别度优先", result["prompt"])
        self.assertIn("tiny unreadable text", result["negative_prompt"])


if __name__ == "__main__":
    unittest.main()
