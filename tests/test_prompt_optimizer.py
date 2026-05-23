import json
import unittest

import app
from modules.prompt_optimizer import (
    IMAGE_PROMPT_OPTIMIZATION_GUIDE,
    STRUCTURED_PROMPT_JSON_SCHEMA,
    VIDEO_SCRIPT_OPTIMIZATION_GUIDE,
    _normalize_optimized_text,
    build_qwen_prompt_optimizer_workflow,
    build_qwen_prompt_language_switch_workflow,
    build_qwen_prompt_translator_workflow,
    build_superprompt_workflow,
    clean_user_prompt,
    extract_show_text,
    normalize_interrogated_chinese_prompt,
    normalize_language_switch_prompt,
    normalize_translated_prompt,
    parse_prompt_optimizer_output,
    parse_video_script_optimizer_output,
    run_prompt_language_switcher,
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

    def test_build_qwen_video_script_workflow_uses_video_guidance(self):
        workflow = build_qwen_prompt_optimizer_workflow("一只猫穿过雨夜霓虹街道", prompt_mode="video_script")

        text = workflow["1"]["inputs"]["text"]
        self.assertIn("video script prompt optimizer", text)
        self.assertIn("LTX / Sulphur and Seedance 2.0", text)
        self.assertIn(VIDEO_SCRIPT_OPTIMIZATION_GUIDE, text)
        self.assertIn("一只猫穿过雨夜霓虹街道", text)
        self.assertNotIn(STRUCTURED_PROMPT_JSON_SCHEMA, text)
        self.assertEqual(workflow["1"]["_meta"]["title"], "Qwen Video Script Optimizer")
        self.assertEqual(workflow["2"]["_meta"]["title"], "Optimized Video Script")

    def test_build_qwen_video_script_workflow_defaults_to_single_image_reference(self):
        workflow = build_qwen_prompt_optimizer_workflow("吃棒棒糖的少女，特写镜头", prompt_mode="video_script")

        text = workflow["1"]["inputs"]["text"]
        self.assertIn("single uploaded image", text)
        self.assertIn("Do not invent @图片, @视频, or @音频 reference placeholders", text)
        self.assertIn("Do not include duration or aspect-ratio settings", text)
        self.assertIn("Preserve user-provided second or frame timeline labels", text)
        self.assertIn("人物、场景、氛围、动作、表情、镜头、光影", text)
        self.assertNotIn("@图片1-@图片9", text)
        self.assertNotIn("@视频1-@视频3", text)
        self.assertNotIn("aspect ratio, duration", text)

    def test_build_qwen_video_script_workflow_uses_current_timing_context(self):
        workflow = build_qwen_prompt_optimizer_workflow(
            "吃棒棒糖的少女，0-3秒含糖微动",
            prompt_mode="video_script",
            prompt_context={"duration_seconds": 10, "fps": 24},
        )

        text = workflow["1"]["inputs"]["text"]
        self.assertIn("Current workflow timing: 10 seconds", text)
        self.assertIn("24 fps", text)
        self.assertIn("Keep timeline segments within this duration", text)

    def test_parse_video_script_optimizer_output_skips_image_json_variant(self):
        parsed = parse_video_script_optimizer_output(
            "10秒雨夜霓虹街道，一只黑猫从画面左侧穿过，镜头低机位跟随，雨水反光，环境音为雨声。",
            "雨夜黑猫",
        )

        self.assertEqual(parsed["prompt_mode"], "video_script")
        self.assertEqual(parsed["cleaned_prompt"], "雨夜黑猫")
        self.assertIn("镜头低机位跟随", parsed["optimized_prompt"])
        self.assertNotIn("structured_prompt_json", parsed)

    def test_parse_video_script_optimizer_output_removes_unsupported_reference_and_parameter_clauses(self):
        parsed = parse_video_script_optimizer_output(
            "吃棒棒糖的少女，特写镜头，糖身微晃，@视频1-@视频3 作为动作参考，"
            "@图片1-@图片3 作为场景与光影参考，@音频1 作为环境音参考，"
            "禁止文字、字幕、LOGO、水印、风格漂移、角色变脸，时长10秒，16:9，镜头保持柔焦与微晃。",
            "吃棒棒糖的少女",
        )

        optimized = parsed["optimized_prompt"]
        self.assertIn("吃棒棒糖的少女", optimized)
        self.assertIn("镜头保持柔焦与微晃", optimized)
        self.assertNotIn("@视频", optimized)
        self.assertNotIn("@图片", optimized)
        self.assertNotIn("@音频", optimized)
        self.assertNotIn("禁止文字", optimized)
        self.assertNotIn("LOGO", optimized)
        self.assertNotIn("时长10秒", optimized)
        self.assertNotIn("16:9", optimized)

    def test_parse_video_script_optimizer_output_preserves_timeline_segments(self):
        parsed = parse_video_script_optimizer_output(
            "人物：吃棒棒糖的少女，0-3秒：含糖微动，3-6秒：轻抿糖身，"
            "第24帧：眼神转向镜头，时长10秒，16:9。",
            "吃棒棒糖的少女",
        )

        optimized = parsed["optimized_prompt"]
        self.assertIn("0-3秒：含糖微动", optimized)
        self.assertIn("3-6秒：轻抿糖身", optimized)
        self.assertIn("第24帧：眼神转向镜头", optimized)
        self.assertNotIn("时长10秒", optimized)
        self.assertNotIn("16:9", optimized)

    def test_build_qwen_prompt_translator_workflow_outputs_chinese_prompt(self):
        workflow = build_qwen_prompt_translator_workflow("a sliced watermelon on a plate")

        self.assertEqual(workflow["1"]["class_type"], "Qwen3_VQA")
        self.assertIn("Translate the following image-generation prompt into concise, natural Chinese", workflow["1"]["inputs"]["text"])
        self.assertIn("Do not include the original English prompt", workflow["1"]["inputs"]["text"])
        self.assertEqual(workflow["2"]["inputs"]["text"], ["1", 0])

    def test_build_qwen_prompt_language_switch_workflow_targets_english(self):
        workflow = build_qwen_prompt_language_switch_workflow("切成片的西瓜", "en")

        self.assertEqual(workflow["1"]["class_type"], "Qwen3_VQA")
        self.assertIn("Translate the following image-generation prompt into English", workflow["1"]["inputs"]["text"])
        self.assertIn("keep a valid JSON object with the same keys and structure", workflow["1"]["inputs"]["text"])
        self.assertIn("切成片的西瓜", workflow["1"]["inputs"]["text"])
        self.assertEqual(workflow["1"]["inputs"]["model"], "Qwen3-VL-4B-Instruct")
        self.assertEqual(workflow["1"]["inputs"]["quantization"], "4bit")
        self.assertTrue(workflow["1"]["inputs"]["keep_model_loaded"])
        self.assertEqual(workflow["2"]["inputs"]["text"], ["1", 0])

    def test_build_qwen_prompt_language_switch_workflow_raises_json_token_budget(self):
        prompt = json.dumps(
            {
                "subject": "切成片的西瓜",
                "important_details": ["白色瓷盘", "夏日自然光", "突出果肉纹理"],
                "constraints": ["不要文字", "不要手部"],
            },
            ensure_ascii=False,
        )
        workflow = build_qwen_prompt_language_switch_workflow(prompt, "en", max_new_tokens=256)

        self.assertGreaterEqual(workflow["1"]["inputs"]["max_new_tokens"], 1024)

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

        self.assertIn("西瓜", parsed["optimized_prompt"])
        self.assertIn("白色瓷盘", parsed["optimized_prompt"])
        self.assertIn("突出果肉纹理", parsed["optimized_prompt"])
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

    def test_plain_prompt_uses_richer_structured_fields_when_keyword_is_sparse(self):
        text = """{
          "keyword_prompt": "低角度仰拍，展现广阔峡谷，前景风化岩石，背景无垠沙漠，浅蓝天空，棕米色调",
          "structured_prompt": {
            "subject": "峡谷岩壁，风化岩石前景，无垠沙漠背景",
            "action": "静止展现自然地貌，低角度仰拍增强纵深",
            "scene": "广阔峡谷，浅蓝天空，地平线远处，荒芜植被稀疏",
            "composition": "低角度仰拍，岩石前景，岩壁占据画面主体，沙漠延伸至远方",
            "lighting": "自然日光，柔和阴影，强调纹理与轮廓",
            "style": "写实风景，自然主义摄影风格，强调地质细节与空间感",
            "color_palette": "棕色与米色为主，浅蓝天空，低饱和度，强调荒芜与宁静",
            "materials_textures": ["砂岩表面风化纹理，深邃裂隙，粗粝质感"],
            "important_details": [
              "低角度仰拍，增强纵深与透视感",
              "地平线清晰可见",
              "植被稀疏，强调荒芜感"
            ]
          }
        }"""

        parsed = parse_prompt_optimizer_output(text, "峡谷风景")

        self.assertIn("自然日光", parsed["optimized_prompt"])
        self.assertIn("砂岩表面风化纹理", parsed["optimized_prompt"])
        self.assertIn("地平线清晰可见", parsed["optimized_prompt"])
        self.assertGreater(len(parsed["optimized_prompt"]), len("低角度仰拍，展现广阔峡谷，前景风化岩石，背景无垠沙漠，浅蓝天空，棕米色调"))

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

    def test_normalize_language_switch_prompt_removes_english_label(self):
        self.assertEqual(
            normalize_language_switch_prompt("English: sliced watermelon, white ceramic plate", "en"),
            "sliced watermelon, white ceramic plate",
        )

    def test_normalize_language_switch_prompt_preserves_json_shape(self):
        text = """```json
        {
          "subject": "sliced watermelon",
          "important_details": ["white ceramic plate", "natural light"]
        }
        ```"""

        normalized = normalize_language_switch_prompt(text, "en")
        parsed = json.loads(normalized)

        self.assertEqual(parsed["subject"], "sliced watermelon")
        self.assertEqual(parsed["important_details"], ["white ceramic plate", "natural light"])
        self.assertIn('\n  "subject"', normalized)

    def test_normalize_language_switch_prompt_fills_missing_json_fields_from_source(self):
        source = json.dumps(
            {
                "subject": "切成片的西瓜",
                "important_details": ["白色瓷盘", "夏日自然光", "突出果肉纹理"],
                "constraints": ["不要文字", "不要手部"],
            },
            ensure_ascii=False,
        )
        translated = json.dumps(
            {
                "subject": "sliced watermelon",
                "important_details": ["white ceramic plate"],
            },
            ensure_ascii=False,
        )

        normalized = normalize_language_switch_prompt(translated, "en", source_prompt=source)
        parsed = json.loads(normalized)

        self.assertEqual(parsed["subject"], "sliced watermelon")
        self.assertEqual(parsed["important_details"], ["white ceramic plate", "夏日自然光", "突出果肉纹理"])
        self.assertEqual(parsed["constraints"], ["不要文字", "不要手部"])

    def test_run_prompt_language_switcher_translates_json_leaves_when_group_output_is_not_json(self):
        source = {
            "intent": "写实肖像摄影，强调人物与环境的和谐与宁静氛围",
            "subject": "年轻女子，十七八岁，棕色长发，白皙肤色",
            "important_details": ["佩戴精致项链", "身穿白色露肩连衣裙"],
        }
        responses = {
            "p1": "portrait photography, calm bedroom atmosphere",
            "p2": "realistic portrait photography, emphasizing harmony between the person and environment",
            "p3": "young woman, seventeen or eighteen years old, brown long hair, fair skin",
            "p4": "wearing a delicate necklace",
            "p5": "wearing a white off-shoulder dress",
        }
        prompt_ids = []

        def fake_post(path, payload, base_url):
            prompt_id = "p" + str(len(prompt_ids) + 1)
            prompt_ids.append(prompt_id)
            return {"prompt_id": prompt_id}

        def fake_get(path, base_url):
            prompt_id = path.rsplit("/", 1)[-1]
            return {
                prompt_id: {
                    "status": {"completed": True},
                    "outputs": {"2": {"text": [responses[prompt_id]]}},
                }
            }

        result = run_prompt_language_switcher(
            json.dumps(source, ensure_ascii=False),
            "en",
            "http://prompt",
            fake_post,
            fake_get,
            poll_interval=0,
        )
        parsed = json.loads(result["translated_prompt"])

        self.assertEqual(result["format"], "json")
        self.assertEqual(prompt_ids, ["p1", "p2", "p3", "p4", "p5"])
        self.assertEqual(
            list(parsed.keys()),
            ["intent", "subject", "important_details"],
        )
        self.assertEqual(
            parsed["subject"],
            "young woman, seventeen or eighteen years old, brown long hair, fair skin",
        )
        self.assertEqual(
            parsed["important_details"],
            ["wearing a delicate necklace", "wearing a white off-shoulder dress"],
        )

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

    def test_api_prompt_optimize_passes_video_script_mode(self):
        calls = []
        old_runner = app.run_prompt_optimizer
        old_instances = app._get_enabled_instances
        old_picker = app._pick_ready_aux_instance
        try:
            app._get_enabled_instances = lambda: [{"name": "Prompt", "url": "http://prompt"}]
            app._pick_ready_aux_instance = lambda instances, phase, timeout=180: instances[0]

            def fake_runner(prompt, base_url, post, get, **kwargs):
                calls.append((
                    prompt,
                    base_url,
                    kwargs.get("prompt_mode"),
                    kwargs.get("max_new_tokens"),
                    kwargs.get("prompt_context"),
                ))
                return {
                    "ok": True,
                    "provider": "comfyui-qwen3-vl-4b-4bit",
                    "prompt_id": "p-video",
                    "original_prompt": prompt,
                    "cleaned_prompt": "雨夜黑猫",
                    "optimized_prompt": "10秒雨夜霓虹街道，一只黑猫从画面左侧穿过，镜头低机位跟随。",
                    "prompt_mode": "video_script",
                }

            app.run_prompt_optimizer = fake_runner
            result = app.api_prompt_optimize(
                app.PromptOptimizeRequest(
                    prompt="雨夜黑猫",
                    mode="video_script",
                    max_new_tokens=768,
                    prompt_context={"duration_seconds": 10, "fps": 24},
                ),
                current_user={"sub": "u1", "role": "user"},
            )
        finally:
            app.run_prompt_optimizer = old_runner
            app._get_enabled_instances = old_instances
            app._pick_ready_aux_instance = old_picker

        self.assertEqual(calls, [("雨夜黑猫", "http://prompt", "video_script", 768, {"duration_seconds": 10, "fps": 24})])
        self.assertEqual(result["prompt_mode"], "video_script")
        self.assertIn("黑猫", result["optimized_prompt"])

    def test_api_prompt_translate_auto_targets_english_for_chinese_prompt(self):
        calls = []
        old_runner = app.run_prompt_language_switcher
        old_instances = app._get_enabled_instances
        old_picker = app._pick_ready_aux_instance
        try:
            app._get_enabled_instances = lambda: [{"name": "Prompt", "url": "http://prompt"}]
            app._pick_ready_aux_instance = lambda instances, phase, timeout=180: instances[0]

            def fake_runner(prompt, target_language, base_url, post, get, **kwargs):
                calls.append((prompt, target_language, base_url))
                return {
                    "ok": True,
                    "provider": "qwen",
                    "target_language": target_language,
                    "translated_prompt": "sliced watermelon, white ceramic plate",
                    "prompt_en": "sliced watermelon, white ceramic plate",
                }

            app.run_prompt_language_switcher = fake_runner
            result = app.api_prompt_translate(
                app.PromptTranslateRequest(prompt="切成片的西瓜"),
                current_user={"sub": "u1", "role": "user"},
            )
        finally:
            app.run_prompt_language_switcher = old_runner
            app._get_enabled_instances = old_instances
            app._pick_ready_aux_instance = old_picker

        self.assertEqual(calls, [("切成片的西瓜", "en", "http://prompt")])
        self.assertEqual(result["translated_prompt"], "sliced watermelon, white ceramic plate")
        self.assertEqual(result["target_language"], "en")

    def test_api_prompt_translate_reuses_cached_pair_and_reverse(self):
        calls = []
        old_runner = app.run_prompt_language_switcher
        old_instances = app._get_enabled_instances
        old_picker = app._pick_ready_aux_instance
        app._PROMPT_TRANSLATE_CACHE.clear()
        try:
            app._get_enabled_instances = lambda: [{"name": "Prompt", "url": "http://prompt"}]
            app._pick_ready_aux_instance = lambda instances, phase, timeout=180: instances[0]

            def fake_runner(prompt, target_language, base_url, post, get, **kwargs):
                calls.append((prompt, target_language, base_url))
                return {
                    "ok": True,
                    "provider": "qwen",
                    "target_language": target_language,
                    "translated_prompt": "sliced watermelon, white ceramic plate",
                    "prompt_en": "sliced watermelon, white ceramic plate",
                }

            app.run_prompt_language_switcher = fake_runner
            first = app.api_prompt_translate(
                app.PromptTranslateRequest(prompt="切成片的西瓜"),
                current_user={"sub": "u1", "role": "user"},
            )
            second = app.api_prompt_translate(
                app.PromptTranslateRequest(prompt="切成片的西瓜"),
                current_user={"sub": "u1", "role": "user"},
            )
            reverse = app.api_prompt_translate(
                app.PromptTranslateRequest(prompt="sliced watermelon, white ceramic plate"),
                current_user={"sub": "u1", "role": "user"},
            )
        finally:
            app.run_prompt_language_switcher = old_runner
            app._get_enabled_instances = old_instances
            app._pick_ready_aux_instance = old_picker
            app._PROMPT_TRANSLATE_CACHE.clear()

        self.assertEqual(calls, [("切成片的西瓜", "en", "http://prompt")])
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(second["translated_prompt"], "sliced watermelon, white ceramic plate")
        self.assertTrue(reverse["cached"])
        self.assertEqual(reverse["target_language"], "zh")
        self.assertEqual(reverse["translated_prompt"], "切成片的西瓜")

    def test_api_prompt_translate_preserves_json_prompt_format(self):
        calls = []
        old_runner = app.run_prompt_language_switcher
        old_instances = app._get_enabled_instances
        old_picker = app._pick_ready_aux_instance
        app._PROMPT_TRANSLATE_CACHE.clear()
        try:
            app._get_enabled_instances = lambda: [{"name": "Prompt", "url": "http://prompt"}]
            app._pick_ready_aux_instance = lambda instances, phase, timeout=180: instances[0]

            def fake_runner(prompt, target_language, base_url, post, get, **kwargs):
                calls.append((prompt, target_language, base_url))
                return {
                    "ok": True,
                    "provider": "qwen",
                    "target_language": target_language,
                    "translated_prompt": json.dumps(
                        {
                            "subject": "sliced watermelon",
                            "important_details": ["white ceramic plate"],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "prompt_en": "",
                }

            app.run_prompt_language_switcher = fake_runner
            result = app.api_prompt_translate(
                app.PromptTranslateRequest(prompt='{"subject":"切成片的西瓜"}'),
                current_user={"sub": "u1", "role": "user"},
            )
        finally:
            app.run_prompt_language_switcher = old_runner
            app._get_enabled_instances = old_instances
            app._pick_ready_aux_instance = old_picker
            app._PROMPT_TRANSLATE_CACHE.clear()

        self.assertEqual(calls, [('{"subject":"切成片的西瓜"}', "en", "http://prompt")])
        self.assertEqual(result["format"], "json")
        parsed = json.loads(result["translated_prompt"])
        self.assertEqual(parsed["subject"], "sliced watermelon")
        self.assertEqual(parsed["important_details"], ["white ceramic plate"])

    def test_api_prompt_interrogate_adds_structured_json_when_available(self):
        optimize_calls = []
        old_instances = app._get_enabled_instances
        old_picker = app._pick_ready_aux_instance
        old_resolve = app._resolve_input_image_path
        old_prepare = app.prepare_interrogate_image
        old_build = app.build_image_interrogate_workflow
        old_ensure = app.ensure_workflow_images_available
        old_interrogator = app.run_image_interrogator
        old_translator = app.run_prompt_translator
        old_optimizer = app.run_prompt_optimizer
        old_mark = app._mark_aux_instance_active
        try:
            app._get_enabled_instances = lambda: [{"name": "Prompt", "url": "http://prompt"}]
            app._pick_ready_aux_instance = lambda instances, phase, timeout=180: instances[0]
            app._resolve_input_image_path = lambda image: "/tmp/input.png"
            app.prepare_interrogate_image = lambda image, input_dir: {"filename": "optimized.png", "optimized": False}
            app.build_image_interrogate_workflow = lambda image: {"1": {"class_type": "LoadImage"}}
            app.ensure_workflow_images_available = lambda workflow, input_dir, inst_url: None
            app.run_image_interrogator = lambda *args, **kwargs: {
                "ok": True,
                "provider": "comfyui-wd14-florence",
                "prompt": "A futuristic sports car on a winding mountain road.",
            }
            app.run_prompt_translator = lambda *args, **kwargs: {
                "provider": "qwen",
                "prompt_zh": "一辆未来主义超跑在蜿蜒山路上。",
            }

            def fake_optimizer(prompt, base_url, post, get, **kwargs):
                optimize_calls.append((prompt, base_url))
                return {
                    "provider": "qwen-json",
                    "optimized_prompt": "未来主义超跑，蜿蜒山路",
                    "structured_prompt": {"subject": "未来主义超跑"},
                    "structured_prompt_json": "{\"subject\":\"未来主义超跑\"}",
                }

            app.run_prompt_optimizer = fake_optimizer
            app._mark_aux_instance_active = lambda inst: None
            result = app.api_prompt_interrogate(
                app.PromptInterrogateRequest(image="sample.png"),
                current_user={"sub": "u1", "role": "user"},
            )
        finally:
            app._get_enabled_instances = old_instances
            app._pick_ready_aux_instance = old_picker
            app._resolve_input_image_path = old_resolve
            app.prepare_interrogate_image = old_prepare
            app.build_image_interrogate_workflow = old_build
            app.ensure_workflow_images_available = old_ensure
            app.run_image_interrogator = old_interrogator
            app.run_prompt_translator = old_translator
            app.run_prompt_optimizer = old_optimizer
            app._mark_aux_instance_active = old_mark

        self.assertEqual(optimize_calls, [("一辆未来主义超跑在蜿蜒山路上。", "http://prompt")])
        self.assertEqual(result["prompt_zh"], "一辆未来主义超跑在蜿蜒山路上。")
        self.assertEqual(result["structured_prompt"]["subject"], "未来主义超跑")
        self.assertIn("subject", result["structured_prompt_json"])
        self.assertEqual(result["structured_provider"], "qwen-json")

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

    def test_prompt_aux_instances_are_hidden_from_regular_user_instance_list(self):
        old_load_nodes = app._load_nodes
        old_connected = app._is_node_connected
        try:
            app._load_nodes = lambda: [
                {
                    "id": "n1",
                    "name": "Node",
                    "host": "127.0.0.1",
                    "enabled": True,
                    "shared": True,
                    "instances": [
                        {"name": "A", "port": 8190, "roles": ["generation"]},
                        {"name": "Prompt", "port": 8191, "roles": ["prompt_aux"]},
                    ],
                }
            ]
            app._is_node_connected = lambda node_id: True

            regular = app._get_enabled_instances_for_user({"id": "u1", "sub": "u1", "role": "user"})
            admin = app._get_enabled_instances_for_user({"id": "admin", "sub": "admin", "role": "admin"})
        finally:
            app._load_nodes = old_load_nodes
            app._is_node_connected = old_connected

        self.assertEqual([inst["name"] for inst in regular], ["A"])
        self.assertEqual([inst["name"] for inst in admin], ["A", "Prompt"])

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
