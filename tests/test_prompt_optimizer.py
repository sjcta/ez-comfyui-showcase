import json
import unittest

import app
from modules.prompt_optimizer import (
    IMAGE_PROMPT_OPTIMIZATION_GUIDE,
    STRUCTURED_PROMPT_JSON_SCHEMA,
    _normalize_optimized_text,
    build_qwen_prompt_optimizer_workflow,
    build_qwen_prompt_translator_workflow,
    build_superprompt_workflow,
    clean_user_prompt,
    extract_show_text,
    normalize_interrogated_chinese_prompt,
    normalize_translated_prompt,
    parse_prompt_optimizer_output,
)


class PromptOptimizerTests(unittest.TestCase):
    def test_clean_user_prompt_removes_high_confidence_chinese_request_words(self):
        cleaned = clean_user_prompt("请帮我生成一张切成片的西瓜")

        self.assertEqual(cleaned, "切成片的西瓜")

    def test_build_superprompt_workflow_uses_text_node_and_show_text_output(self):
        workflow = build_superprompt_workflow("切成片的西瓜", max_new_tokens=96)

        self.assertEqual(workflow["1"]["class_type"], "Text Multiline")
        self.assertEqual(workflow["1"]["inputs"]["text"], "切成片的西瓜")
        self.assertEqual(workflow["2"]["class_type"], "Superprompt")
        self.assertEqual(workflow["2"]["inputs"]["prompt"], ["1", 0])
        self.assertEqual(workflow["2"]["inputs"]["max_new_tokens"], 96)
        self.assertEqual(workflow["3"]["class_type"], "ShowText|pysssss")
        self.assertEqual(workflow["3"]["inputs"]["text"], ["2", 0])

    def test_build_qwen_workflow_keeps_small_model_loaded(self):
        workflow = build_qwen_prompt_optimizer_workflow("切成片的西瓜", max_new_tokens=128)

        self.assertEqual(workflow["1"]["class_type"], "Qwen3_VQA")
        self.assertEqual(workflow["1"]["inputs"]["model"], "Qwen3-VL-4B-Instruct")
        self.assertEqual(workflow["1"]["inputs"]["quantization"], "4bit")
        self.assertTrue(workflow["1"]["inputs"]["keep_model_loaded"])
        self.assertIn("切成片的西瓜", workflow["1"]["inputs"]["text"])
        self.assertIn("Nano Banana / GPT Image", workflow["1"]["inputs"]["text"])
        self.assertIn("Scene / Subject / Important Details / Use Case / Constraints", workflow["1"]["inputs"]["text"])
        self.assertIn("structured_prompt", workflow["1"]["inputs"]["text"])
        self.assertIn("valid JSON object", workflow["1"]["inputs"]["text"])
        self.assertIn(STRUCTURED_PROMPT_JSON_SCHEMA, workflow["1"]["inputs"]["text"])
        self.assertEqual(workflow["2"]["class_type"], "ShowText|pysssss")
        self.assertEqual(workflow["2"]["inputs"]["text"], ["1", 0])

    def test_build_superprompt_workflow_includes_image_prompt_guide(self):
        workflow = build_superprompt_workflow("切成片的西瓜", max_new_tokens=96)

        self.assertIn(IMAGE_PROMPT_OPTIMIZATION_GUIDE, workflow["2"]["inputs"]["instruction_prompt"])

    def test_build_qwen_workflow_preserves_known_cultural_reference(self):
        workflow = build_qwen_prompt_optimizer_workflow("黑猫警长")

        text = workflow["1"]["inputs"]["text"]
        self.assertIn("Preserve proper nouns", text)
        self.assertIn("黑猫警长", text)
        self.assertIn("classic Chinese animated police cat character", text)

    def test_build_qwen_prompt_translator_workflow_outputs_chinese_prompt(self):
        workflow = build_qwen_prompt_translator_workflow("a sliced watermelon on a plate")

        self.assertEqual(workflow["1"]["class_type"], "Qwen3_VQA")
        self.assertIn("Translate the following image-generation prompt into concise, natural Chinese", workflow["1"]["inputs"]["text"])
        self.assertIn("Do not include the original English prompt", workflow["1"]["inputs"]["text"])
        self.assertEqual(workflow["2"]["inputs"]["text"], ["1", 0])

    def test_extract_show_text_prefers_output_text_from_target_node(self):
        history = {
            "outputs": {
                "3": {"text": ["fresh sliced watermelon, natural lighting"]},
                "9": {"text": ["wrong node"]},
            }
        }

        self.assertEqual(
            extract_show_text(history, "3"),
            "fresh sliced watermelon, natural lighting",
        )

    def test_normalize_optimized_text_unwraps_single_item_list_repr(self):
        text = _normalize_optimized_text("['fresh sliced watermelon, natural lighting']")

        self.assertEqual(text, "fresh sliced watermelon, natural lighting")

    def test_parse_prompt_optimizer_output_extracts_plain_and_json_variants(self):
        text = """```json
        {
          "keyword_prompt": "切成片的西瓜，白色瓷盘，夏日自然光",
          "structured_prompt": {
            "language": "zh",
            "intent": "切成片的西瓜",
            "prompt": "切成片的西瓜，白色瓷盘，夏日自然光",
            "subject": "西瓜",
            "action": "切成片",
            "scene": "餐桌",
            "composition": "俯拍",
            "lighting": "夏日自然光",
            "style": "清爽写实",
            "important_details": ["白色瓷盘"],
            "constraints": ["突出果肉纹理"]
          }
        }
        ```"""

        parsed = parse_prompt_optimizer_output(text, "切成片的西瓜")
        structured_json = json.loads(parsed["structured_prompt_json"])

        self.assertEqual(parsed["optimized_prompt"], "切成片的西瓜，白色瓷盘，夏日自然光")
        self.assertEqual(parsed["structured_prompt"]["version"], "ez-prompt-json-v1")
        self.assertEqual(parsed["structured_prompt"]["subject"], "西瓜")
        self.assertIn('"subject": "西瓜"', parsed["structured_prompt_json"])
        self.assertNotIn("version", structured_json)
        self.assertNotIn("language", structured_json)
        self.assertNotIn("intent", structured_json)
        self.assertNotIn("prompt", structured_json)
        self.assertNotIn("materials_textures", structured_json)
        self.assertNotIn("visible_text", structured_json)
        self.assertNotIn("negative_prompt", structured_json)
        self.assertEqual(structured_json["important_details"], ["白色瓷盘"])

    def test_structured_prompt_json_removes_prompt_duplicate_from_details(self):
        text = """{
          "keyword_prompt": "极简抽象海报，几何形状构成的人脸，黄灰粉渐变色调",
          "structured_prompt": {
            "version": "ez-prompt-json-v1",
            "language": "zh",
            "intent": "生成抽象几何人脸海报",
            "prompt": "极简抽象海报，几何形状构成的人脸，黄灰粉渐变色调",
            "subject": "抽象几何人脸",
            "important_details": [
              "极简抽象海报，几何形状构成的人脸，黄灰粉渐变色调。",
              "双眼硕大细长，直视观者",
              "面部两侧各一条垂直条纹"
            ],
            "constraints": [],
            "visible_text": []
          }
        }"""

        parsed = parse_prompt_optimizer_output(text, "抽象几何人脸海报")
        structured_json = json.loads(parsed["structured_prompt_json"])

        self.assertEqual(
            structured_json["important_details"],
            ["双眼硕大细长，直视观者", "面部两侧各一条垂直条纹"],
        )
        self.assertNotIn("version", structured_json)
        self.assertNotIn("language", structured_json)
        self.assertNotIn("intent", structured_json)
        self.assertNotIn("prompt", structured_json)
        self.assertNotIn("constraints", structured_json)

    def test_structured_prompt_json_uses_fields_instead_of_full_prompt_when_decomposed(self):
        text = """{
          "keyword_prompt": "年轻女子十七八岁，棕色长发，白色露肩连衣裙，坐在床前面对大窗户",
          "structured_prompt": {
            "intent": "写实肖像摄影，强调人物与环境的和谐与宁静氛围",
            "prompt": "年轻女子十七八岁，棕色长发，白皙肤色，佩戴精致项链，身穿白色露肩连衣裙，坐在床前面对大窗户，窗外绿意盎然，画面中央直视镜头，神情宁静，柔和梦幻棕褐色调，写实摄影，肖像角度",
            "subject": "年轻女子，十七八岁，棕色长发，白皙肤色，佩戴精致项链，身穿白色露肩连衣裙",
            "action": "坐在床前，面对大窗户，直视镜头，神情宁静",
            "scene": "室内，床前，大窗户透入自然光，窗外绿意盎然",
            "composition": "画面中央构图，人物居中，床与窗户形成对角线引导，突出人物面部与表情",
            "lighting": "柔和自然光，从窗户斜射，营造温暖朦胧感，阴影柔和",
            "style": "写实摄影，肖像风格，细腻真实质感，带梦幻氛围",
            "color_palette": "棕褐色主调，搭配白色连衣裙与绿色窗外景致，整体柔和"
          }
        }"""

        parsed = parse_prompt_optimizer_output(text, "写实肖像摄影")
        structured_json = json.loads(parsed["structured_prompt_json"])

        self.assertNotIn("intent", structured_json)
        self.assertNotIn("prompt", structured_json)
        self.assertEqual(
            structured_json["subject"],
            "年轻女子，十七八岁，棕色长发，白皙肤色，佩戴精致项链，身穿白色露肩连衣裙",
        )
        self.assertEqual(structured_json["action"], "坐在床前，面对大窗户，直视镜头，神情宁静")

    def test_parse_prompt_optimizer_output_falls_back_for_plain_text(self):
        parsed = parse_prompt_optimizer_output("黑猫警长，经典中国动画风格，正义警察猫角色", "黑猫警长")

        self.assertEqual(parsed["optimized_prompt"], "黑猫警长，经典中国动画风格，正义警察猫角色")
        self.assertEqual(parsed["structured_prompt"]["intent"], "黑猫警长")
        self.assertEqual(parsed["structured_prompt"]["subject"], "黑猫警长")

    def test_normalize_translated_prompt_removes_bilingual_english_tail(self):
        text = (
            "一位年轻女性坐在床上，手持棒棒糖置于脸前。柔和暖光，梦幻虚化质感。\n"
            "English: A young woman sits on a bed holding a lollipop in front of her face, "
            "soft warm lighting, dreamy blurred aesthetic."
        )

        self.assertEqual(
            normalize_translated_prompt(text),
            "一位年轻女性坐在床上，手持棒棒糖置于脸前。柔和暖光，梦幻虚化质感。",
        )

    def test_normalize_translated_prompt_keeps_short_technical_terms(self):
        text = "赛博朋克城市夜景，35mm lens，Unreal Engine，浅景深，高对比霓虹光。"

        self.assertEqual(normalize_translated_prompt(text), text)

    def test_normalize_interrogated_chinese_prompt_removes_english_tag_tail(self):
        text = (
            "一位年轻女性坐在床上，手持棒棒糖置于脸前。"
            "1girl, solo, black hair, white dress, looking at viewer"
        )

        self.assertEqual(
            normalize_interrogated_chinese_prompt(text),
            "一位年轻女性坐在床上，手持棒棒糖置于脸前。",
        )

    def test_normalize_interrogated_chinese_prompt_removes_inline_english_tags(self):
        text = "张勇，单人，short hair, black hair，白衬衫，necktie，formal，灰背景"

        self.assertEqual(
            normalize_interrogated_chinese_prompt(text),
            "张勇，单人，白衬衫，灰背景",
        )

    def test_api_prompt_optimize_returns_structured_result(self):
        calls = []
        old_runner = app.run_prompt_optimizer
        old_instances = app._get_enabled_instances
        old_picker = app._pick_ready_aux_instance
        try:
            app._get_enabled_instances = lambda: [{"name": "A", "url": "http://comfy-a"}]
            app._pick_ready_aux_instance = lambda instances, phase, timeout=180: instances[0]

            def fake_runner(prompt, base_url, post, get, **kwargs):
                calls.append((prompt, base_url))
                return {
                    "ok": True,
                    "provider": "comfyui-superprompt",
                    "prompt_id": "p1",
                    "original_prompt": prompt,
                    "cleaned_prompt": "切成片的西瓜",
                    "optimized_prompt": "fresh sliced watermelon, natural lighting",
                    "structured_prompt": {"subject": "watermelon"},
                    "structured_prompt_json": "{\"subject\":\"watermelon\"}",
                }

            app.run_prompt_optimizer = fake_runner
            result = app.api_prompt_optimize(
                app.PromptOptimizeRequest(prompt="请帮我生成一张切成片的西瓜"),
                current_user={"sub": "u1", "role": "user"},
            )
        finally:
            app.run_prompt_optimizer = old_runner
            app._get_enabled_instances = old_instances
            app._pick_ready_aux_instance = old_picker

        self.assertEqual(calls, [("请帮我生成一张切成片的西瓜", "http://comfy-a")])
        self.assertEqual(result["cleaned_prompt"], "切成片的西瓜")
        self.assertEqual(result["optimized_prompt"], "fresh sliced watermelon, natural lighting")
        self.assertEqual(result["structured_prompt"]["subject"], "watermelon")
        self.assertIn("subject", result["structured_prompt_json"])

    def test_prompt_aux_instances_are_split_from_generation_pool(self):
        instances = [
            {"name": "A", "url": "http://comfy-a", "roles": ["generation"]},
            {"name": "Prompt", "url": "http://comfy-prompt", "roles": ["prompt_aux"]},
            {"name": "Caption", "url": "http://comfy-caption", "prompt_aux": True},
        ]

        self.assertEqual(
            [inst["name"] for inst in app._get_generation_instances(instances)],
            ["A"],
        )
        self.assertEqual(
            [inst["name"] for inst in app._get_prompt_aux_instances(instances)],
            ["Prompt", "Caption"],
        )

    def test_pick_ready_aux_instance_only_uses_reserved_prompt_pool(self):
        old_ready = app._ensure_aux_instance_ready
        old_queue = app._get_instance_queue_size
        old_log = app.add_log
        try:
            app._ensure_aux_instance_ready = lambda inst, phase, timeout=180: inst
            app._get_instance_queue_size = lambda url: 8 if url.endswith("gen") else 0
            app.add_log = lambda *args, **kwargs: None

            picked = app._pick_ready_aux_instance(
                [
                    {"name": "Gen", "url": "http://comfy-gen", "roles": ["generation"]},
                    {"name": "Prompt", "url": "http://comfy-prompt", "roles": ["prompt_aux"]},
                ],
                phase="prompt_optimize",
            )
        finally:
            app._ensure_aux_instance_ready = old_ready
            app._get_instance_queue_size = old_queue
            app.add_log = old_log

        self.assertEqual(picked["name"], "Prompt")

    def test_pick_ready_aux_instance_requires_reserved_prompt_pool(self):
        with self.assertRaisesRegex(RuntimeError, "未配置提示词独立实例"):
            app._pick_ready_aux_instance(
                [{"name": "A", "url": "http://comfy-a", "roles": ["generation"]}],
                phase="prompt_optimize",
            )

    def test_aux_instance_ready_starts_stopped_instance_before_prompt_task(self):
        calls = []
        old_up = app.comfyui_up
        old_get_node = app._get_node_by_id
        old_action = app._run_instance_action
        old_log = app.add_log
        old_last_active = dict(app._instance_last_active)
        try:
            states = iter([False, True])
            app.comfyui_up = lambda url=None: next(states)
            app._get_node_by_id = lambda nid: {"id": nid, "name": "Node", "connection": "local"}

            def fake_action(node, inst, action):
                calls.append((node["id"], inst["name"], action))
                return True

            app._run_instance_action = fake_action
            app.add_log = lambda *args, **kwargs: None

            inst = app._ensure_aux_instance_ready(
                {"name": "A", "url": "http://comfy-a", "_node_id": "node-a"},
                phase="prompt_optimize",
                timeout=2,
                poll_interval=0.2,
            )
        finally:
            app.comfyui_up = old_up
            app._get_node_by_id = old_get_node
            app._run_instance_action = old_action
            app.add_log = old_log
            app._instance_last_active.clear()
            app._instance_last_active.update(old_last_active)

        self.assertEqual(inst["name"], "A")
        self.assertEqual(calls, [("node-a", "A", "start")])


if __name__ == "__main__":
    unittest.main()
