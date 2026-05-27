import json
import unittest

import app
from modules.prompt_optimizer import (
    HIGH_SUCCESS_PROMPT_SPEC_GUIDE,
    IMAGE_PROMPT_OPTIMIZATION_GUIDE,
    STRUCTURED_PROMPT_JSON_SCHEMA,
    VIDEO_SCRIPT_OPTIMIZATION_GUIDE,
    _normalize_optimized_text,
    _video_script_timing_context_text,
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
    run_llm_prompt_optimizer,
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
        self.assertIn("High-success image prompt spec", workflow["1"]["inputs"]["text"])
        self.assertIn("任务目标、保真要求、主体、动作姿态、场景、构图镜头、光线色彩、材质细节、风格媒介、文字版式、负向限制", workflow["1"]["inputs"]["text"])
        self.assertIn("The positive prompt is the main control surface", workflow["1"]["inputs"]["text"])
        self.assertIn("negative prompts should be pure short phrases/tags", workflow["1"]["inputs"]["text"])
        self.assertIn("structured_prompt", workflow["1"]["inputs"]["text"])
        self.assertIn("valid JSON object", workflow["1"]["inputs"]["text"])
        self.assertIn('"intent":"..."', workflow["1"]["inputs"]["text"])
        self.assertIn('"identity_lock":"..."', workflow["1"]["inputs"]["text"])
        self.assertIn('"text_layout":"..."', workflow["1"]["inputs"]["text"])
        self.assertIn(STRUCTURED_PROMPT_JSON_SCHEMA, workflow["1"]["inputs"]["text"])
        self.assertEqual(workflow["2"]["class_type"], "ShowText|pysssss")
        self.assertEqual(workflow["2"]["inputs"]["text"], ["1", 0])

    def test_build_superprompt_workflow_includes_image_prompt_guide(self):
        workflow = build_superprompt_workflow("切成片的西瓜", max_new_tokens=96)

        self.assertIn(IMAGE_PROMPT_OPTIMIZATION_GUIDE, workflow["2"]["inputs"]["instruction_prompt"])
        self.assertIn(HIGH_SUCCESS_PROMPT_SPEC_GUIDE, workflow["2"]["inputs"]["instruction_prompt"])

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
        self.assertIn("Arrange the action as a beginning-to-end timeline", text)

    def test_video_script_timing_context_derives_seconds_and_frame_range(self):
        text = _video_script_timing_context_text({"frame_count": 121, "fps": 24})

        self.assertIn("5.04 seconds", text)
        self.assertIn("24 fps", text)
        self.assertIn("121 frames", text)
        self.assertIn("0-5.04 seconds", text)
        self.assertIn("frame 1-121", text)

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

    def test_parse_prompt_optimizer_output_normalizes_array_color_palette(self):
        text = json.dumps(
            {
                "keyword_prompt": "红色机甲少女",
                "structured_prompt": {
                    "subject": "红色机甲少女",
                    "scene": "棚拍背景",
                    "color_palette": ["红色", "黑色", "绿色"],
                },
            },
            ensure_ascii=False,
        )

        parsed = parse_prompt_optimizer_output(text, "红色机甲少女")

        self.assertEqual(parsed["structured_prompt"]["color_palette"], "红色，黑色，绿色")
        self.assertIn("黑色", parsed["optimized_prompt"])
        self.assertIn("绿色", parsed["optimized_prompt"])
        self.assertNotIn("[", parsed["optimized_prompt"])

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

    def test_structured_prompt_json_preserves_pose_and_exposed_body_details(self):
        text = """{
          "keyword_prompt": "女性泳装人像，海边站姿",
          "structured_prompt": {
            "subject": "成年女性海边人像",
            "action": "单腿承重站立，一只手扶住帽檐",
            "pose_details": "肩膀打开，腰部轻微扭转，髋部偏向画面右侧，膝盖微弯",
            "exposed_body_details": "肩颈、锁骨、手臂、腹部和大腿大面积可见，穿着比基尼泳装但未见完全裸露",
            "clothing_accessories": ["比基尼上衣", "高腰泳装下装"]
          }
        }"""

        parsed = parse_prompt_optimizer_output(text, "")
        structured_json = json.loads(parsed["structured_prompt_json"])

        self.assertEqual(structured_json["pose_details"], "肩膀打开，腰部轻微扭转，髋部偏向画面右侧，膝盖微弯")
        self.assertEqual(
            structured_json["exposed_body_details"],
            "肩颈、锁骨、手臂、腹部和大腿大面积可见，穿着比基尼泳装但未见完全裸露",
        )
        self.assertIn("腰部轻微扭转", parsed["optimized_prompt"])
        self.assertIn("腹部和大腿大面积可见", parsed["optimized_prompt"])

    def test_structured_prompt_json_preserves_nsfw_content_details(self):
        text = """{
          "keyword_prompt": "成人女性正面站立，棚拍背景，局部裸露",
          "structured_prompt": {
            "subject": "成人女性",
            "pose_details": "正面站立，双臂自然下垂",
            "exposed_body_details": "胸部、腹部和大腿可见，衣物覆盖范围有限",
            "nsfw_content_details": "成人裸露内容，乳头和外阴区域可见，未出现性行为"
          }
        }"""

        parsed = parse_prompt_optimizer_output(text, "")
        structured_json = json.loads(parsed["structured_prompt_json"])

        self.assertEqual(
            structured_json["nsfw_content_details"],
            "成人裸露内容，乳头和外阴区域可见，未出现性行为",
        )
        self.assertIn("乳头和外阴区域可见", parsed["optimized_prompt"])

    def test_structured_prompt_json_preserves_limb_face_intimate_details_and_labels(self):
        text = """{
          "keyword_prompt": "成人女性裸露站姿，正面棚拍",
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
          }
        }"""

        parsed = parse_prompt_optimizer_output(text, "")
        structured_json = json.loads(parsed["structured_prompt_json"])

        self.assertEqual(structured_json["hand_details"], "左手垂在左大腿外侧，右手手指弯曲贴近髋部")
        self.assertEqual(structured_json["foot_details"], "双脚可见，左脚承重，右脚脚尖略向外")
        self.assertEqual(structured_json["joint_body_mechanics"], "肘关节轻微弯曲，膝关节自然伸直，重心落在左腿")
        self.assertEqual(structured_json["facial_expression_details"], "嘴唇微张，眉毛放松，眼睛直视镜头")
        self.assertEqual(structured_json["intimate_body_details"], "乳头、外阴轮廓和臀沟可见，无遮挡")
        self.assertEqual(structured_json["content_safety_labels"], ["NSFW", "adult_nudity"])
        self.assertIn("右手手指弯曲贴近髋部", parsed["optimized_prompt"])
        self.assertIn("乳头、外阴轮廓和臀沟可见", parsed["optimized_prompt"])
        self.assertIn("NSFW", parsed["optimized_prompt"])

    def test_structured_prompt_json_preserves_occlusion_and_crop_details(self):
        text = """{
          "keyword_prompt": "粉色衣物人物，近距离低角度抬腿构图，室内门口",
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

        parsed = parse_prompt_optimizer_output(text, "")
        structured_json = json.loads(parsed["structured_prompt_json"])

        self.assertEqual(
            structured_json["occlusion_crop_details"],
            "头顶、眼睛和双脚被画幅裁切；胯部和内侧大腿被抬起的大腿及粉色衣物遮挡，隐私部位不可见",
        )
        self.assertIn("双脚均在画面外不可见", parsed["optimized_prompt"])
        self.assertIn("隐私部位不可见", parsed["optimized_prompt"])
        self.assertIn("手机近距离低角度仰拍", parsed["optimized_prompt"])

    def test_plain_prompt_drops_generic_absence_fragments_but_keeps_specific_crop(self):
        text = """{
          "keyword_prompt": "粉色衣物人物，低角度抬腿构图",
          "structured_prompt": {
            "subject": "粉色衣物人物",
            "hand_details": "不可见/画面外",
            "foot_details": "不可见",
            "facial_expression_details": "不可见/不可见",
            "occlusion_crop_details": "头顶、眼睛和双脚被画幅裁切；胯部被抬起的大腿遮挡",
            "camera_lens": "低角度近距离仰拍"
          }
        }"""

        parsed = parse_prompt_optimizer_output(text, "")
        structured_json = json.loads(parsed["structured_prompt_json"])

        self.assertIn("头顶、眼睛和双脚被画幅裁切", parsed["optimized_prompt"])
        self.assertIn("低角度近距离仰拍", parsed["optimized_prompt"])
        self.assertNotIn("不可见/画面外", parsed["optimized_prompt"])
        self.assertNotIn("不可见/不可见", parsed["optimized_prompt"])
        self.assertNotIn("hand_details", structured_json)
        self.assertNotIn("foot_details", structured_json)
        self.assertNotIn("facial_expression_details", structured_json)
        self.assertEqual(structured_json["occlusion_crop_details"], "头顶、眼睛和双脚被画幅裁切；胯部被抬起的大腿遮挡")

    def test_structured_prompt_json_preserves_explicit_adult_sexual_details(self):
        text = """{
          "keyword_prompt": "成人女性，明确成人裸露，性器官可见，手部与性器官接触",
          "structured_prompt": {
            "subject": "成人女性",
            "hand_details": "右手位于两腿之间，手指接触外阴区域",
            "genital_details": "外阴和阴唇可见，局部发红",
            "sexual_act_details": "手指插入阴道内，属于明确成人性行为细节",
            "fluid_contact_details": "外阴和手指附近可见白色液体附着",
            "intimate_body_details": "外阴、阴唇和阴道入口可见，无遮挡",
            "nsfw_content_details": "NSFW，adult_nudity，explicit_sexual_content，成人裸露，性器官可见，手指插入阴道，可见白色液体",
            "content_safety_labels": ["NSFW", "adult_nudity", "explicit_sexual_content", "visible_genitals", "sexual_fluid"]
          }
        }"""

        parsed = parse_prompt_optimizer_output(text, "")
        structured_json = json.loads(parsed["structured_prompt_json"])

        self.assertEqual(structured_json["genital_details"], "外阴和阴唇可见，局部发红")
        self.assertEqual(structured_json["sexual_act_details"], "手指插入阴道内，属于明确成人性行为细节")
        self.assertEqual(structured_json["fluid_contact_details"], "外阴和手指附近可见白色液体附着")
        self.assertEqual(
            structured_json["content_safety_labels"],
            ["NSFW", "adult_nudity", "explicit_sexual_content", "visible_genitals", "sexual_fluid"],
        )
        self.assertIn("手指插入阴道内", parsed["optimized_prompt"])
        self.assertIn("白色液体", parsed["optimized_prompt"])
        self.assertIn("explicit_sexual_content", parsed["optimized_prompt"])

    def test_plain_prompt_splits_positive_and_negative_constraints(self):
        text = """{
          "keyword_prompt": "东亚女性，粉色丝绸套装，抬腿构图",
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

        parsed = parse_prompt_optimizer_output(text, "")

        self.assertIn("一条腿高抬靠近镜头", parsed["optimized_prompt"])
        self.assertIn("右手扶在抬起的大腿旁", parsed["optimized_prompt"])
        self.assertNotIn("不要裁成头像特写", parsed["optimized_prompt"])
        self.assertNotIn("避免新增道具", parsed["optimized_prompt"])
        self.assertIn("头像特写", parsed["negative_prompt"])
        self.assertIn("道具", parsed["negative_prompt"])
        self.assertIn("多余人物", parsed["negative_prompt"])
        self.assertIn("粉色衣服", parsed["negative_prompt"])
        self.assertNotIn("不要", parsed["negative_prompt"])
        self.assertNotIn("避免", parsed["negative_prompt"])
        self.assertNotIn("保持原有蓝色门框", parsed["negative_prompt"])

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
        old_runner = getattr(app, "run_llm_prompt_optimizer", None)
        old_instances = app._get_enabled_instances
        try:
            app._get_enabled_instances = lambda: self.fail("prompt optimize should use the shared LLM, not ComfyUI instances")

            def fake_runner(prompt, **kwargs):
                calls.append((prompt, kwargs.get("prompt_mode")))
                return {
                    "ok": True,
                    "provider": "llm-gemma-4-e2b",
                    "original_prompt": prompt,
                    "cleaned_prompt": "切成片的西瓜",
                    "optimized_prompt": "fresh sliced watermelon, natural lighting",
                    "structured_prompt": {"subject": "watermelon"},
                    "structured_prompt_json": "{\"subject\":\"watermelon\"}",
                }

            app.run_llm_prompt_optimizer = fake_runner
            result = app.api_prompt_optimize(
                app.PromptOptimizeRequest(prompt="请帮我生成一张切成片的西瓜"),
                current_user={"sub": "u1", "role": "user"},
            )
        finally:
            if old_runner is None:
                delattr(app, "run_llm_prompt_optimizer")
            else:
                app.run_llm_prompt_optimizer = old_runner
            app._get_enabled_instances = old_instances

        self.assertEqual(calls, [("请帮我生成一张切成片的西瓜", "image")])
        self.assertEqual(result["cleaned_prompt"], "切成片的西瓜")
        self.assertEqual(result["optimized_prompt"], "fresh sliced watermelon, natural lighting")
        self.assertEqual(result["structured_prompt"]["subject"], "watermelon")
        self.assertIn("subject", result["structured_prompt_json"])
        self.assertEqual(result["instance"], "LLM")

    def test_api_prompt_optimize_passes_video_script_mode(self):
        calls = []
        old_runner = getattr(app, "run_llm_prompt_optimizer", None)
        old_instances = app._get_enabled_instances
        try:
            app._get_enabled_instances = lambda: self.fail("video script optimize should use the shared LLM, not ComfyUI instances")

            def fake_runner(prompt, **kwargs):
                calls.append((
                    prompt,
                    kwargs.get("prompt_mode"),
                    kwargs.get("max_new_tokens"),
                    kwargs.get("prompt_context"),
                ))
                return {
                    "ok": True,
                    "provider": "llm-gemma-4-e2b",
                    "original_prompt": prompt,
                    "cleaned_prompt": "雨夜黑猫",
                    "optimized_prompt": "10秒雨夜霓虹街道，一只黑猫从画面左侧穿过，镜头低机位跟随。",
                    "prompt_mode": "video_script",
                }

            app.run_llm_prompt_optimizer = fake_runner
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
            if old_runner is None:
                delattr(app, "run_llm_prompt_optimizer")
            else:
                app.run_llm_prompt_optimizer = old_runner
            app._get_enabled_instances = old_instances

        self.assertEqual(calls, [("雨夜黑猫", "video_script", 768, {"duration_seconds": 10, "fps": 24})])
        self.assertEqual(result["prompt_mode"], "video_script")
        self.assertIn("黑猫", result["optimized_prompt"])

    def test_llm_prompt_optimizer_requests_direct_final_answer(self):
        calls = []

        def fake_chat(messages, **kwargs):
            calls.append({"messages": messages, **kwargs})
            return '{"keyword_prompt":"白色杯子，木桌，自然窗光","structured_prompt":{"subject":"白色杯子","scene":"木桌","lighting":"自然窗光"}}'

        result = run_llm_prompt_optimizer("一只白色杯子放在木桌上，窗边自然光", chat_fn=fake_chat)

        self.assertEqual(calls[0]["messages"][0]["role"], "system")
        self.assertIn("Do not reason", calls[0]["messages"][0]["content"])
        self.assertEqual(calls[0]["messages"][1]["role"], "user")
        self.assertIn("白色杯子", result["optimized_prompt"])

    def test_api_prompt_translate_auto_targets_english_for_chinese_prompt(self):
        calls = []
        old_runner = getattr(app, "run_llm_prompt_language_switcher", None)
        old_instances = app._get_enabled_instances
        try:
            app._get_enabled_instances = lambda: self.fail("prompt translate should use the shared LLM, not ComfyUI instances")

            def fake_runner(prompt, target_language, **kwargs):
                calls.append((prompt, target_language))
                return {
                    "ok": True,
                    "provider": "llm-gemma-4-e2b",
                    "target_language": target_language,
                    "translated_prompt": "sliced watermelon, white ceramic plate",
                    "prompt_en": "sliced watermelon, white ceramic plate",
                }

            app.run_llm_prompt_language_switcher = fake_runner
            result = app.api_prompt_translate(
                app.PromptTranslateRequest(prompt="切成片的西瓜"),
                current_user={"sub": "u1", "role": "user"},
            )
        finally:
            if old_runner is None:
                delattr(app, "run_llm_prompt_language_switcher")
            else:
                app.run_llm_prompt_language_switcher = old_runner
            app._get_enabled_instances = old_instances

        self.assertEqual(calls, [("切成片的西瓜", "en")])
        self.assertEqual(result["translated_prompt"], "sliced watermelon, white ceramic plate")
        self.assertEqual(result["target_language"], "en")

    def test_api_prompt_translate_reuses_cached_pair_and_reverse(self):
        calls = []
        old_runner = getattr(app, "run_llm_prompt_language_switcher", None)
        old_instances = app._get_enabled_instances
        app._PROMPT_TRANSLATE_CACHE.clear()
        try:
            app._get_enabled_instances = lambda: self.fail("prompt translate cache should not require ComfyUI instances")

            def fake_runner(prompt, target_language, **kwargs):
                calls.append((prompt, target_language))
                return {
                    "ok": True,
                    "provider": "llm-gemma-4-e2b",
                    "target_language": target_language,
                    "translated_prompt": "sliced watermelon, white ceramic plate",
                    "prompt_en": "sliced watermelon, white ceramic plate",
                }

            app.run_llm_prompt_language_switcher = fake_runner
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
            if old_runner is None:
                delattr(app, "run_llm_prompt_language_switcher")
            else:
                app.run_llm_prompt_language_switcher = old_runner
            app._get_enabled_instances = old_instances
            app._PROMPT_TRANSLATE_CACHE.clear()

        self.assertEqual(calls, [("切成片的西瓜", "en")])
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(second["translated_prompt"], "sliced watermelon, white ceramic plate")
        self.assertTrue(reverse["cached"])
        self.assertEqual(reverse["target_language"], "zh")
        self.assertEqual(reverse["translated_prompt"], "切成片的西瓜")

    def test_api_prompt_translate_preserves_json_prompt_format(self):
        calls = []
        old_runner = getattr(app, "run_llm_prompt_language_switcher", None)
        old_instances = app._get_enabled_instances
        app._PROMPT_TRANSLATE_CACHE.clear()
        try:
            app._get_enabled_instances = lambda: self.fail("prompt translate JSON should not require ComfyUI instances")

            def fake_runner(prompt, target_language, **kwargs):
                calls.append((prompt, target_language))
                return {
                    "ok": True,
                    "provider": "llm-gemma-4-e2b",
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

            app.run_llm_prompt_language_switcher = fake_runner
            result = app.api_prompt_translate(
                app.PromptTranslateRequest(prompt='{"subject":"切成片的西瓜"}'),
                current_user={"sub": "u1", "role": "user"},
            )
        finally:
            if old_runner is None:
                delattr(app, "run_llm_prompt_language_switcher")
            else:
                app.run_llm_prompt_language_switcher = old_runner
            app._get_enabled_instances = old_instances
            app._PROMPT_TRANSLATE_CACHE.clear()

        self.assertEqual(calls, [('{"subject":"切成片的西瓜"}', "en")])
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
        old_translator = getattr(app, "run_llm_prompt_translator", None)
        old_optimizer = getattr(app, "run_llm_prompt_optimizer", None)
        old_llm_interrogator = getattr(app, "run_llm_image_interrogator", None)
        old_llm_vision_error = getattr(app, "LLMVisionUnsupportedError", None)
        old_mark = app._mark_aux_instance_active
        try:
            class FakeVisionUnsupported(Exception):
                pass

            app.LLMVisionUnsupportedError = FakeVisionUnsupported
            app.run_llm_image_interrogator = lambda *args, **kwargs: (_ for _ in ()).throw(FakeVisionUnsupported("mmproj missing"))
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
            app.run_llm_prompt_translator = lambda *args, **kwargs: {
                "provider": "llm-gemma-4-e2b",
                "prompt_zh": "一辆未来主义超跑在蜿蜒山路上。",
            }

            def fake_optimizer(prompt, **kwargs):
                optimize_calls.append(prompt)
                return {
                    "provider": "llm-gemma-4-e2b",
                    "optimized_prompt": "未来主义超跑，蜿蜒山路",
                    "structured_prompt": {"subject": "未来主义超跑"},
                    "structured_prompt_json": "{\"subject\":\"未来主义超跑\"}",
                }

            app.run_llm_prompt_optimizer = fake_optimizer
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
            if old_translator is None:
                delattr(app, "run_llm_prompt_translator")
            else:
                app.run_llm_prompt_translator = old_translator
            if old_optimizer is None:
                delattr(app, "run_llm_prompt_optimizer")
            else:
                app.run_llm_prompt_optimizer = old_optimizer
            if old_llm_interrogator is None:
                delattr(app, "run_llm_image_interrogator")
            else:
                app.run_llm_image_interrogator = old_llm_interrogator
            if old_llm_vision_error is None:
                delattr(app, "LLMVisionUnsupportedError")
            else:
                app.LLMVisionUnsupportedError = old_llm_vision_error
            app._mark_aux_instance_active = old_mark

        self.assertEqual(optimize_calls, ["一辆未来主义超跑在蜿蜒山路上。"])
        self.assertEqual(result["prompt"], "未来主义超跑，蜿蜒山路")
        self.assertEqual(result["prompt_zh"], "未来主义超跑，蜿蜒山路")
        self.assertEqual(result["structured_optimized_prompt"], "未来主义超跑，蜿蜒山路")
        self.assertEqual(result["structured_prompt"]["subject"], "未来主义超跑")
        self.assertIn("subject", result["structured_prompt_json"])
        self.assertEqual(result["structured_provider"], "llm-gemma-4-e2b")

    def test_api_prompt_interrogate_uses_llm_vision_without_comfyui_when_available(self):
        old_instances = app._get_enabled_instances
        old_resolve = app._resolve_input_image_path
        old_prepare = app.prepare_interrogate_image
        old_llm_interrogator = getattr(app, "run_llm_image_interrogator", None)
        try:
            app._get_enabled_instances = lambda: self.fail("LLM vision interrogation should not require ComfyUI instances")
            app._resolve_input_image_path = lambda image: "/tmp/input.png"
            app.prepare_interrogate_image = lambda image, input_dir: {"filename": "optimized.png", "optimized": False}

            def fake_llm_interrogator(image_path, **kwargs):
                self.assertEqual(image_path, "/tmp/input.png")
                self.assertEqual(kwargs.get("max_new_tokens"), 512)
                self.assertTrue(kwargs.get("compact"))
                self.assertTrue(kwargs.get("include_quality"))
                return {
                    "ok": True,
                    "provider": "llm-gemma-4-e2b-vision",
                    "prompt": "红色机甲少女，棚拍背景",
                    "prompt_zh": "红色机甲少女，棚拍背景",
                    "prompt_en": "red mecha girl, studio background",
                    "structured_prompt": {"subject": "红色机甲少女"},
                    "structured_prompt_json": "{\"subject\":\"红色机甲少女\"}",
                    "reverse_prompt_quality": {"score": 96, "target_score": 95, "passed": True, "issues": []},
                }

            app.run_llm_image_interrogator = fake_llm_interrogator
            result = app.api_prompt_interrogate(
                app.PromptInterrogateRequest(image="sample.png"),
                current_user={"sub": "u1", "role": "user"},
            )
        finally:
            app._get_enabled_instances = old_instances
            app._resolve_input_image_path = old_resolve
            app.prepare_interrogate_image = old_prepare
            if old_llm_interrogator is None:
                delattr(app, "run_llm_image_interrogator")
            else:
                app.run_llm_image_interrogator = old_llm_interrogator

        self.assertEqual(result["provider"], "llm-gemma-4-e2b-vision")
        self.assertEqual(result["instance"], "LLM")
        self.assertEqual(result["image_preprocess"]["filename"], "optimized.png")
        self.assertNotIn("reverse_prompt_quality", result)

    def test_api_prompt_interrogate_expert_mode_uses_expert_runner(self):
        old_instances = app._get_enabled_instances
        old_resolve = app._resolve_input_image_path
        old_prepare = app.prepare_interrogate_image
        old_expert = getattr(app, "run_llm_expert_image_interrogator", None)
        try:
            app._get_enabled_instances = lambda: self.fail("expert interrogation should use LLM experts, not ComfyUI instances")
            app._resolve_input_image_path = lambda image: "/tmp/input.png"
            app.prepare_interrogate_image = lambda image, input_dir: {"filename": "optimized.png", "optimized": False}

            def fake_expert(image_path, **kwargs):
                self.assertEqual(image_path, "/tmp/input.png")
                self.assertEqual(kwargs.get("max_new_tokens"), 1536)
                self.assertTrue(kwargs.get("single_pass"))
                self.assertTrue(kwargs.get("include_quality"))
                return {
                    "ok": True,
                    "provider": "llm-gemma-4-e2b-vision-expert",
                    "prompt": "专家合并提示词",
                    "prompt_zh": "专家合并提示词",
                    "structured_prompt_json": "{\"subject\":\"专家合并提示词\"}",
                    "expert_interrogate": {
                        "enabled": True,
                        "quality": {"score": 80, "target_score": 95, "passed": False},
                        "experts": [{"id": "composition", "label": "构图镜头专家", "summary": "低角度"}],
                    },
                    "reverse_prompt_quality": {"score": 80, "target_score": 95, "passed": False, "issues": []},
                }

            app.run_llm_expert_image_interrogator = fake_expert
            result = app.api_prompt_interrogate(
                app.PromptInterrogateRequest(image="sample.png", expert=True),
                current_user={"sub": "u1", "role": "user"},
            )
        finally:
            app._get_enabled_instances = old_instances
            app._resolve_input_image_path = old_resolve
            app.prepare_interrogate_image = old_prepare
            if old_expert is None:
                delattr(app, "run_llm_expert_image_interrogator")
            else:
                app.run_llm_expert_image_interrogator = old_expert

        self.assertEqual(result["provider"], "llm-gemma-4-e2b-vision-expert")
        self.assertEqual(result["instance"], "LLM")
        self.assertEqual(result["source_image"], "sample.png")
        self.assertTrue(result["expert_interrogate"]["enabled"])
        self.assertNotIn("reverse_prompt_quality", result)
        self.assertNotIn("quality", result["expert_interrogate"])

    def test_api_prompt_interrogate_can_return_timed_video_script(self):
        optimize_calls = []
        old_instances = app._get_enabled_instances
        old_resolve = app._resolve_input_image_path
        old_prepare = app.prepare_interrogate_image
        old_llm_interrogator = getattr(app, "run_llm_image_interrogator", None)
        old_optimizer = getattr(app, "run_llm_prompt_optimizer", None)
        try:
            app._get_enabled_instances = lambda: self.fail("LLM video-script interrogation should not require ComfyUI instances")
            app._resolve_input_image_path = lambda image: "/tmp/input.png"
            app.prepare_interrogate_image = lambda image, input_dir: {"filename": "optimized.png", "optimized": False}
            app.run_llm_image_interrogator = lambda *args, **kwargs: {
                "ok": True,
                "provider": "llm-gemma-4-e2b-vision",
                "prompt": "红色机甲少女，棚拍背景，轻微转头",
                "prompt_zh": "红色机甲少女，棚拍背景，轻微转头",
            }

            def fake_optimizer(prompt, **kwargs):
                optimize_calls.append((prompt, kwargs.get("prompt_mode"), kwargs.get("prompt_context")))
                return {
                    "ok": True,
                    "provider": "llm-gemma-4-e2b",
                    "optimized_prompt": "0-2秒：红色机甲少女看向镜头；2-5秒：轻微转头，棚拍光影稳定。",
                    "prompt_mode": "video_script",
                }

            app.run_llm_prompt_optimizer = fake_optimizer
            result = app.api_prompt_interrogate(
                app.PromptInterrogateRequest(
                    image="sample.png",
                    mode="video_script",
                    prompt_context={"frame_count": 121, "fps": 24, "duration_seconds": 5.04},
                ),
                current_user={"sub": "u1", "role": "user"},
            )
        finally:
            app._get_enabled_instances = old_instances
            app._resolve_input_image_path = old_resolve
            app.prepare_interrogate_image = old_prepare
            if old_llm_interrogator is None:
                delattr(app, "run_llm_image_interrogator")
            else:
                app.run_llm_image_interrogator = old_llm_interrogator
            if old_optimizer is None:
                delattr(app, "run_llm_prompt_optimizer")
            else:
                app.run_llm_prompt_optimizer = old_optimizer

        self.assertEqual(optimize_calls, [(
            "红色机甲少女，棚拍背景，轻微转头",
            "video_script",
            {"frame_count": 121, "fps": 24, "duration_seconds": 5.04},
        )])
        self.assertEqual(result["prompt"], "0-2秒：红色机甲少女看向镜头；2-5秒：轻微转头，棚拍光影稳定。")
        self.assertEqual(result["prompt_mode"], "video_script")
        self.assertEqual(result["video_script_provider"], "llm-gemma-4-e2b")

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
