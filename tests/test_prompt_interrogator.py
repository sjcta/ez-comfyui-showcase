import json
import unittest
import tempfile
from pathlib import Path

from modules.prompt_optimizer import HIGH_SUCCESS_PROMPT_SPEC_GUIDE
from modules.image_reverse_skill import REPLICATION_TARGET_SCORE, validate_reverse_prompt_quality
from modules.prompt_interrogator import (
    CAR_FRONT_SEAT_POSE_STANDARD,
    BEDROOM_SEATED_POSE_STANDARD,
    FAST_IMAGE_INTERROGATE_TEMPLATE,
    EXPERT_IMAGE_INTERROGATE_TEMPLATE,
    EXPERT_IMAGE_REVIEW_TEMPLATE,
    FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE,
    RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE,
    IMAGE_INTERROGATE_EXPERTS,
    _clean_positive_prompt_text,
    _clean_negative_prompt_text,
    build_image_interrogate_workflow,
    extract_interrogate_result,
    _extract_json_object,
    prepare_interrogate_image,
    run_llm_expert_image_interrogator,
    run_llm_image_interrogator,
    _normalize_visual_evidence,
    _backfill_expert_results_from_visual_evidence,
    _clamp_expert_result_text,
    _select_experts_from_global_overview,
    _expert_observation_from_markdown,
)


class PromptInterrogatorTests(unittest.TestCase):
    def test_run_llm_expert_image_interrogator_calls_each_expert_and_merges_json(self):
        calls = []

        def fake_chat(messages, **kwargs):
            text = messages[1]["content"][0]["text"]
            calls.append(text)
            if "全局概览调度器" in text:
                return json.dumps(
                    {
                        "has_person": True,
                        "image_type": "人像",
                        "visible_elements": ["人物", "粉色衣物", "近距离低角度构图"],
                        "recommended_experts": [spec["id"] for spec in IMAGE_INTERROGATE_EXPERTS],
                        "reason": "图中有人物主体，需要完整人物专家组",
                    },
                    ensure_ascii=False,
                )
            if "评审专家" in text:
                return json.dumps(
                    {
                        "summary": "各专家结论足够细腻且基本属实",
                        "retry_expert_ids": [],
                        "reviews": [
                            {
                                "id": spec["id"],
                                "label": spec["label"],
                                "passed": True,
                                "detail_score": 0.86,
                                "factual_score": 0.88,
                                "boundary_score": 0.9,
                                "missing": [],
                                "unsupported": [],
                                "retry_instruction": "",
                            }
                            for spec in IMAGE_INTERROGATE_EXPERTS
                        ],
                    },
                    ensure_ascii=False,
                )
            if "最终合并器" in text:
                self.assertIn("构图镜头专家", text)
                self.assertIn("摄影参数专家", text)
                self.assertIn("性内容边界专家", text)
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
                      "性内容边界": ["不要写可见性器官"]
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
            if "专家代号: composition" in text:
                return '{"id":"composition","label":"构图镜头专家","summary":"低角度近距离构图","fields":{"camera_lens":"手机近距离低角度仰拍"},"observations":["前景腿部占比很大"],"uncertain":[],"negative_constraints":["不要误写成平视"],"confidence":0.9}'
            if "专家代号: photography_parameters" in text:
                return '{"id":"photography_parameters","label":"摄影参数专家","summary":"手机近距离拍摄，大光圈浅景深倾向","fields":{"aperture_depth":"背景轻微虚化，大光圈浅景深倾向","exposure":"高调曝光，采光度充足"},"observations":["背景轻微虚化","采光度充足"],"uncertain":[],"negative_constraints":["过暗曝光"],"confidence":0.78}'
            if "专家代号: sexual_boundary" in text:
                return '{"id":"sexual_boundary","label":"性内容边界专家","summary":"无可见性器官","fields":{"occlusion_crop_details":"胯部被抬起的大腿和衣物遮挡"},"observations":["无可见性器官"],"uncertain":["年龄不可确认"],"negative_constraints":["不要写可见性器官"],"confidence":0.82}'
            return '{"id":"other","label":"其他专家","summary":"可见事实","fields":{},"observations":["可见事实"],"uncertain":[],"negative_constraints":[],"confidence":0.7}'

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (32, 32), (245, 210, 220)).save(image_path)
            result = run_llm_expert_image_interrogator(str(image_path), chat_fn=fake_chat, include_quality=True)

        self.assertEqual(len(calls), len(IMAGE_INTERROGATE_EXPERTS) + 3)
        self.assertEqual(len(result["expert_interrogate"]["experts"]), len(IMAGE_INTERROGATE_EXPERTS))
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
        self.assertIn("平视", result["negative_prompt"])
        self.assertNotIn("不要", result["negative_prompt"])
        self.assertIn('"画面描述": {', result["structured_prompt_json"])
        self.assertIn('"构图镜头": {', result["structured_prompt_json"])
        self.assertIn('"负面提示词": {', result["structured_prompt_json"])
        self.assertNotIn("双脚", result["structured_prompt_json"])
        self.assertIn("胯部被抬起的大腿和衣物遮挡", result["structured_prompt_json"])

    def test_run_llm_expert_image_interrogator_retries_failed_reviewed_expert_once(self):
        calls = []

        def fake_chat(messages, **kwargs):
            text = messages[1]["content"][0]["text"]
            calls.append(text)
            if "全局概览调度器" in text:
                return '{"has_person":false,"image_type":"产品","visible_elements":["产品"],"recommended_experts":["composition"],"reason":"只测构图专家"}'
            if "评审专家" in text and "模糊构图" in text:
                return """{
                  "summary": "构图专家不够细且有平视误判",
                  "retry_expert_ids": ["composition"],
                  "reviews": [{
                    "id": "composition",
                    "label": "构图镜头专家",
                    "passed": false,
                    "detail_score": 0.42,
                    "factual_score": 0.4,
                    "boundary_score": 0.8,
                    "missing": ["缺少画面边界和镜头距离"],
                    "unsupported": ["平视"],
                    "retry_instruction": "必须写清近距离低角度和主体占比，删除平视"
                  }]
                }"""
            if "评审专家" in text:
                return """{
                  "summary": "重写后通过",
                  "retry_expert_ids": [],
                  "reviews": [{
                    "id": "composition",
                    "label": "构图镜头专家",
                    "passed": true,
                    "detail_score": 0.9,
                    "factual_score": 0.88,
                    "boundary_score": 0.92,
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
            if "复审专家已打回" in text:
                self.assertIn("必须写清近距离低角度", text)
                return '{"id":"composition","label":"构图镜头专家","summary":"近距离低角度构图","fields":{"镜头":"近距离低角度构图，主体占据画面大部分"},"observations":["主体占据画面大部分"],"uncertain":[],"negative_constraints":["平视"],"confidence":0.91}'
            if "专家代号: composition" in text:
                return '{"id":"composition","label":"构图镜头专家","summary":"模糊构图","fields":{"镜头":"平视"},"observations":["构图"],"uncertain":[],"negative_constraints":[],"confidence":0.4}'
            return "{}"

        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "sample.png"
            from PIL import Image

            Image.new("RGB", (32, 32), (245, 210, 220)).save(image_path)
            result = run_llm_expert_image_interrogator(str(image_path), chat_fn=fake_chat)

        self.assertEqual(len(calls), 6)
        self.assertEqual(result["expert_interrogate"]["review_retry_count"], 1)
        self.assertEqual(result["expert_interrogate"]["review_retry_expert_ids"], ["composition"])
        self.assertEqual(result["expert_interrogate"]["final_review"]["summary"], "重写后通过")
        self.assertTrue(result["expert_interrogate"]["experts"][0]["review_retry"]["from_review"])
        self.assertIn("近距离低角度构图", result["prompt"])

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
        self.assertIn("content_safety_labels", workflow["5"]["inputs"]["text"])
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
        self.assertIn("content_safety_labels 至少包含 NSFW 和 adult_nudity", workflow["5"]["inputs"]["text"])
        self.assertIn("成人/NSFW/裸露/性化", workflow["5"]["inputs"]["text"])
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
            expert_id = ""
            for item in selected:
                if f"专家代号: {item}" in text:
                    expert_id = item
                    break
            return json.dumps(
                {
                    "id": expert_id,
                    "label": expert_id,
                    "summary": "可见事实",
                    "fields": {"观察": "可见事实"},
                    "observations": ["可见事实"],
                    "uncertain": [],
                    "negative_constraints": [],
                    "confidence": 0.8,
                },
                ensure_ascii=False,
            )

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
        self.assertIn("detail_score", EXPERT_IMAGE_REVIEW_TEMPLATE)
        self.assertIn("标准反推定位：快速、准确、可用", FAST_IMAGE_INTERROGATE_TEMPLATE)
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
        self.assertIn("复刻约束用于锁定身份、构图、姿态、颜色、材质、文字版式", FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
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

    def test_runtime_expert_prompt_is_compact_for_4k_context_models(self):
        self.assertLess(len(RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE), 2600)
        self.assertIn("visual_evidence 是内部证据简表", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("foot_or_shoe_contact", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("每个专家最多 100 字", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("所有内容统一使用中文", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("每个专家只能输出自己边界内的观点", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不要输出 structured_prompt", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("车内有方向盘不能自动写手搭方向盘", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("黑色过膝丝袜", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("不写推断/估计", RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertNotIn(HIGH_SUCCESS_PROMPT_SPEC_GUIDE, RUNTIME_FAST_EXPERT_IMAGE_INTERROGATE_TEMPLATE)

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

        clamped = _clamp_expert_result_text(item, max_chars=100)
        total = len(clamped["summary"])
        total += sum(len(str(value)) for value in clamped["fields"].values())
        total += sum(len(str(value)) for value in clamped["observations"])

        self.assertLessEqual(total, 100)
        self.assertIn("…", json.dumps(clamped, ensure_ascii=False))

    def test_expert_prompt_uses_chinese_and_boundary_limited_opinions(self):
        self.assertIn("必须统一使用中文输出", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("只能输出自己专业边界内的观点", EXPERT_IMAGE_INTERROGATE_TEMPLATE)
        self.assertIn("约 100 个汉字", EXPERT_IMAGE_INTERROGATE_TEMPLATE)

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

    def test_markdown_expert_observation_is_parsed_and_clamped(self):
        spec = {"id": "body_pose", "label": "肢体动作专家"}
        markdown = """
        ## 肢体动作专家
        姿势：人物蹲在碎石海岸，鞋底踩地承重，膝盖弯曲靠近身体，躯干向镜头轻微前倾。
        手部：画面右侧手靠近头发，画面左侧手臂贴近身体。
        腿部：黑色过膝丝袜覆盖膝上到鞋口区域，黑色厚底运动鞋接触碎石。
        负面：膝盖支撑地面、1:1正方形
        """

        result = _expert_observation_from_markdown(markdown, spec)
        total = len(result["summary"])
        total += sum(len(str(value)) for value in result["fields"].values())
        total += sum(len(str(value)) for value in result["observations"])

        self.assertEqual(result["id"], "body_pose")
        self.assertIn("姿势", result["fields"])
        self.assertIn("膝盖支撑地面", result["negative_constraints"])
        self.assertLessEqual(total, 100)

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
        self.assertIn('"摄影参数": {', result["structured_prompt_json"])
        self.assertIn("f/2.8", result["structured_prompt_json"])
        self.assertIn("过暗曝光", result["structured_prompt_json"])
        self.assertNotIn("推断", result["structured_prompt_json"])
        self.assertNotIn("模型未返回该专家维度", result["structured_prompt_json"])

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
                {"id":"body_pose","label":"肢体动作专家","summary":"床上正坐，画面左侧手靠近镜头","fields":{"姿势":"坐在床面，躯干正对镜头略微前倾","手部":"画面左侧手部靠近镜头形成模糊"},"observations":["腿部裁切到膝部"],"negative_constraints":["全身入镜"],"confidence":0.9},
                {"id":"clothing_makeup","label":"服装妆容专家","summary":"白色蕾丝吊带和浅色抽绳短裤","fields":{"服装":"白色蕾丝吊带，浅色抽绳短裤"},"observations":["领口蕾丝边可见"],"negative_constraints":["普通T恤"],"confidence":0.88},
                {"id":"composition","label":"构图镜头专家","summary":"竖幅床上中近景","fields":{"构图":"9:16 竖幅，头部到膝部入镜"},"observations":["前景手部模糊"],"negative_constraints":["1:1正方形"],"confidence":0.86}
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
        self.assertIn("姿势", structured["画面描述"]["肢体动作"])
        self.assertIn("服装", structured["画面描述"]["服装妆容"])
        self.assertIn("构图", structured["画面描述"]["构图镜头"])
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
        self.assertIn("姿势", description["肢体动作"])
        self.assertIn("服装", description["服装妆容"])
        self.assertIn("构图", description["构图镜头"])
        self.assertNotIn("sparse_fallback_structured_prompt", {issue["code"] for issue in result["reverse_prompt_quality"]["issues"]})

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


if __name__ == "__main__":
    unittest.main()
