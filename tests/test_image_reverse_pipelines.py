import json
import tempfile
import unittest
from pathlib import Path

from modules.image_reverse.contracts import REVERSE_MODE_EXPERT
from modules.image_reverse.parser import parse_reverse_json
from modules.image_reverse.pipelines import run_expert_reverse, run_expert_team_reverse, run_standard_reverse


def _write_jpeg_stub(path: Path) -> None:
    path.write_bytes(b"\xff\xd8\xff\xd9")


class ImageReverseParserTests(unittest.TestCase):
    def test_parse_clean_abc_visual_spec_without_internal_key_names(self):
        raw = json.dumps(
            {
                "结构化视觉规格书": {
                    "画面总体概述": "写实摄影，主体为人物，场景为车内。",
                    "构图与镜头": {
                        "画幅": "竖图",
                        "主体占比": "约60%",
                        "九宫格位置": "主体从画面中心延伸到右下区域。",
                    },
                    "主体拆解": {
                        "主体1": "人物位于画面中心偏右，遮挡部分座椅。"
                    },
                    "人物高精度分析": {
                        "人物1": "头部yaw约35度，胸腔朝向画面左侧，左肘弯曲约90度。"
                    },
                },
                "最终提示词": "竖图写实摄影，人物位于画面中心偏右，占画面约60%，头部yaw约35度，左肘弯曲约90度。",
                "负面约束": ["字段名文字", "额外人物"],
            },
            ensure_ascii=False,
        )

        output = parse_reverse_json(raw, mode=REVERSE_MODE_EXPERT, provider="test")
        structured = json.dumps(output.visual_spec, ensure_ascii=False)

        self.assertIn("人物位于画面中心偏右", structured)
        self.assertIn("头部yaw约35度", output.prompt)
        self.assertEqual(output.negative_prompt, ["字段名文字", "额外人物"])
        self.assertNotIn("A_结构化视觉规格书", structured)
        self.assertNotIn("B_最终提示词", structured)

    def test_parser_preserves_model_prompt_without_semantic_cleanup(self):
        raw = json.dumps(
            {
                "结构化视觉规格书": {
                    "画面总体概述": "写实摄影，主体为人物。",
                    "重要物体细节": {"物体1": "红色易拉罐位于画面左上区域，罐口朝下。"},
                    "人物高精度分析": {
                        "人物1": "基础特征：年轻东亚女性；年龄倾向：20岁左右；可见族裔/人种外貌倾向：东亚外貌倾向；肤色：暖白肤色；表情与表情依据：眼睛睁大直视镜头，嘴唇闭合。"
                    },
                },
                "最终提示词": (
                    "人物高精度分析：基础特征：年轻东亚女性；年龄倾向：20岁左右；"
                    "可见族裔/人种外貌倾向：东亚外貌倾向；肤色：暖白肤色；"
                    "重要物体细节：红色易拉罐位于画面左上区域，罐口朝下。"
                ),
                "负面约束": [],
            },
            ensure_ascii=False,
        )

        output = parse_reverse_json(raw, mode=REVERSE_MODE_EXPERT, provider="test")

        self.assertIn("人物高精度分析", output.prompt)
        self.assertIn("基础特征：年轻东亚女性", output.prompt)
        self.assertIn("年龄倾向：20岁左右", output.prompt)
        self.assertIn("重要物体细节：红色易拉罐位于画面左上区域", output.prompt)

    def test_parser_does_not_hide_model_metadata_mistakes(self):
        raw = json.dumps(
            {
                "结构化视觉规格书": {
                    "画面总体概述": "写实摄影，主体为人物。",
                    "关键保留点": {"高优先级": ["主体位置保持中心偏右"]},
                    "易错点与禁止项": ["不要添加额外人物", "不要改变主要光源方向"],
                    "不确定项": ["远处背景文字不可读"],
                },
                "最终提示词": (
                    "写实摄影，主体位于画面中心偏右。"
                    "关键保留点：主体位置保持中心偏右。"
                    "不确定项：远处背景文字不可读。"
                    "易错点与禁止项：不要添加额外人物。"
                ),
                "负面约束": ["不要出现水印"],
            },
            ensure_ascii=False,
        )

        output = parse_reverse_json(raw, mode=REVERSE_MODE_EXPERT, provider="test")

        self.assertIn("关键保留点", output.prompt)
        self.assertIn("不确定项", output.prompt)
        self.assertIn("易错点与禁止项", output.prompt)
        self.assertIn("不要出现水印", output.negative_prompt)
        self.assertNotIn("不要添加额外人物", output.negative_prompt)
        self.assertNotIn("不要改变主要光源方向", output.negative_prompt)
        structured = json.dumps(output.visual_spec, ensure_ascii=False)
        self.assertIn("关键保留点", structured)
        self.assertIn("高优先级", structured)
        self.assertIn("易错点与禁止项", structured)
        self.assertIn("不确定项", structured)
        payload = output.to_api_payload()
        self.assertIn("关键保留点", payload["structured_raw"])
        self.assertIn("易错点与禁止项", payload["structured_raw"])
        self.assertIn("不确定项", payload["structured_raw"])
        self.assertIn("关键保留点", json.dumps(payload.get("expert_interrogate") or {}, ensure_ascii=False))

    def test_parser_does_not_hide_speculative_model_output(self):
        raw = json.dumps(
            {
                "结构化视觉规格书": {
                    "画面总体概述": "写实摄影，可能是校园场景；主体为年轻女性。",
                    "主体拆解": {
                        "主体1": "人物穿红色上衣。似乎是学生身份。"
                    },
                },
                "最终提示词": "写实摄影，可能是校园场景。人物穿红色上衣。疑似学生身份。",
                "负面约束": [],
            },
            ensure_ascii=False,
        )

        output = parse_reverse_json(raw, mode=REVERSE_MODE_EXPERT, provider="test")
        structured = json.dumps(output.visual_spec, ensure_ascii=False)

        self.assertIn("可能是校园场景", output.prompt)
        self.assertIn("疑似学生身份", output.prompt)
        self.assertIn("似乎是学生身份", structured)

    def test_parse_expert_json_to_compatible_output(self):
        raw = json.dumps(
            {
                "基本概述": "红色主题人物图",
                "主体类型": "person",
                "主体细节": "人物骨盆位于画面下中区域，胸腔向画面左上旋转，脊柱形成斜向C型趋势；画面左侧手臂从肩部向左上区域抬起，肘部弯曲约90度，手指握住红色易拉罐。",
                "构图镜头": "高机位俯拍，镜头向下约35度，画面轻微顺时针倾斜。",
                "final_prompt": "红色主题人物图，人物骨盆位于画面下中区域，胸腔向画面左上旋转。",
                "negative_prompt": ["文字", "水印"],
            },
            ensure_ascii=False,
        )

        output = parse_reverse_json(raw, mode=REVERSE_MODE_EXPERT, provider="test")

        self.assertIn("胸腔向画面左上旋转", output.prompt)
        self.assertIn("画面描述", output.visual_spec)
        self.assertIn("主体", output.visual_spec["画面描述"])
        self.assertIn("胸腔", output.visual_spec["画面描述"]["主体"])
        self.assertEqual(output.negative_prompt, ["文字", "水印"])

    def test_parser_keeps_expert_required_detail_fields(self):
        raw = json.dumps(
            {
                "基本概述": "高机位人物坐姿照片。",
                "主体类型": "person",
                "画面比例与主体占比": "竖图近似3:4，主体人物外接框占画面约70%，占画面宽度约65%，占画面高度约85%，头部接近上边缘，脚部被下边缘轻微裁切。",
                "主体细节": "主体人物位于中心偏右区域，身体向画面左侧折转。",
                "人物外貌": "主体人物呈年轻成人倾向，东亚外貌倾向，暖白肤色，黑色齐肩短发带空气刘海。",
                "关节角度": "头部yaw向画面右侧约35度，pitch下俯约10度，roll向画面左侧约8度；画面左侧手臂肘部弯曲约90度，画面右下腿部膝盖弯曲约60度，脚尖指向画面右下。",
                "镜头倾斜角度": "高机位俯拍，镜头向下约35度，画面逆时针roll倾斜约4度，近端腿部有广角透视放大。",
                "final_prompt": "",
                "negative_prompt": [],
            },
            ensure_ascii=False,
        )

        output = parse_reverse_json(raw, mode=REVERSE_MODE_EXPERT, provider="test")
        description = output.visual_spec["画面描述"]

        self.assertIn("主体人物外接框占画面约70%", description["画面比例与主体占比"])
        self.assertIn("东亚外貌倾向", description["人物外貌"])
        self.assertIn("画面左侧手臂肘部弯曲约90度", description["关节角度"])
        self.assertIn("逆时针roll倾斜约4度", description["镜头倾斜角度"])
        self.assertIn("东亚外貌倾向", output.prompt)
        self.assertIn("主体人物外接框占画面约70%", output.prompt)
        self.assertIn("画面左侧手臂肘部弯曲约90度", output.prompt)
        self.assertIn("镜头向下约35度", output.prompt)

    def test_expert_team_visual_json_preserves_model_expert_text(self):
        raw = json.dumps(
            {
                "基本概述": "人物位于画面中右至右下区域，头部位于右上区域。",
                "主体类型": "person",
                "专家观点": [
                    "姿态专家：人物骨盆位于画面下中区域，胸腔向画面中左区域折转约35度，画面左侧手臂肘部弯曲约90度。",
                    "光影专家：光源来自画面右上约45度，红色服装接近#CC2233，灰色背景接近#8A8A8A。",
                ],
                "主体细节": "头部位于画面右上区域，手臂从画面中右延伸到左上区域。",
                "复核结论": "修正后通过。",
                "final_prompt": "",
            },
            ensure_ascii=False,
        )

        output = parse_reverse_json(raw, mode="expert", provider="test")
        structured = json.dumps(output.visual_spec, ensure_ascii=False)
        prompt = output.prompt

        self.assertIn("姿态专家", structured)
        self.assertIn("光影专家", structured)
        self.assertIn("人物骨盆位于画面下中区域", structured)
        self.assertIn("右上", structured)
        self.assertIn("中右至右下", structured)
        self.assertIn("中左区域折转约35度", structured)
        self.assertIn("肘部弯曲约90度", prompt)

    def test_parser_does_not_suppress_coarse_model_observations(self):
        rich_subject = (
            "人物呈年轻成人倾向，东亚外貌倾向，暖白肤色，眼睛睁大直视镜头，嘴唇闭合表情专注；"
            "头部位于画面右上区域，yaw向画面左侧约35度，pitch轻微下俯约10度，roll向画面右侧约8度；"
            "胸腔朝向画面左侧约30度，骨盆朝向画面下方，肩线左高右低，脊柱从下中向右上形成弧线；"
            "画面左侧手臂从肩部向左上抬起，肘部弯曲约90度，手指握住红色易拉罐。"
        )
        raw = json.dumps(
            {
                "基本概述": "高机位人物坐姿照片。",
                "主体类型": "person",
                "主体细节": rich_subject,
                "专家观点": [
                    "姿态结构：人物坐在地面上，身体前倾，手臂抬起。"
                ],
            },
            ensure_ascii=False,
        )

        output = parse_reverse_json(raw, mode="expert", provider="test")
        description = output.visual_spec["画面描述"]
        prompt = output.prompt

        self.assertIn("年轻成人倾向", description["主体"])
        self.assertIn("东亚外貌倾向", description["主体"])
        self.assertIn("暖白肤色", description["主体"])
        self.assertIn("表情专注", description["主体"])
        self.assertIn("身体前倾，手臂抬起", prompt)


class ImageReversePipelineTests(unittest.TestCase):
    def test_standard_pipeline_calls_single_prompt(self):
        calls = []

        def fake_chat(messages, **kwargs):
            calls.append((messages, kwargs))
            return json.dumps(
                {
                    "mode": "standard",
                    "画面主题": "一张红色主题人物照片。",
                    "构图镜头": "竖构图，主体位于画面中心到右下区域。",
                    "final_prompt": "竖构图红色主题人物照片，主体位于画面中心到右下区域。",
                },
                ensure_ascii=False,
            )

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "a.jpg"
            _write_jpeg_stub(image)
            result = run_standard_reverse(str(image), chat_fn=fake_chat, model="test-vl")

        self.assertEqual(len(calls), 1)
        self.assertIn("标准：", calls[0][0][1]["content"][0]["text"])
        self.assertIn("主体位于画面中心到右下区域", result["prompt"])
        self.assertIn("structured_prompt_json", result)

    def test_expert_pipeline_requires_person_chain_rules(self):
        prompts = []

        def fake_chat(messages, **kwargs):
            prompt_text = messages[1]["content"][0]["text"]
            prompts.append(prompt_text)
            return json.dumps(
                {
                    "mode": "expert",
                    "基本概述": "人物坐姿照片。",
                    "主体类型": "person",
                    "主体细节": "人物头部位于上中到右上区域，头部向画面右侧旋转约35度，胸腔向画面左上扭转，肩线左高右低，左手肘部弯曲约90度并握住红色罐体。",
                    "final_prompt": "人物坐姿照片，头部位于上中到右上区域，胸腔向画面左上扭转，左手肘部弯曲约90度并握住红色罐体。",
                },
                ensure_ascii=False,
            )

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "a.jpg"
            _write_jpeg_stub(image)
            result = run_expert_reverse(str(image), chat_fn=fake_chat)

        self.assertIn("躯干", prompts[0])
        self.assertIn("肘部", prompts[0])
        self.assertIn("胸腔向画面左上扭转", result["prompt"])
        self.assertTrue(result["expert_interrogate"]["enabled"])

    def test_expert_team_pipeline_runs_global_subject_review(self):
        prompts = []

        def fake_chat(messages, **kwargs):
            prompt_text = messages[1]["content"][0]["text"]
            prompts.append(prompt_text)
            if "第3轮" in prompt_text:
                return json.dumps(
                    {
                        "mode": "expert_review",
                        "复核结论": "修正后通过。",
                        "最终规格": "高机位人物坐姿照片，主体人物呈年轻成人倾向和东亚外貌倾向，骨盆位于画面下中区域，胸腔向画面中左区域折转，画面左侧手臂肘部弯曲约90度，手指握住红色罐体，镜头向下约35度，画面逆时针roll倾斜约4度。",
                        "final_prompt": "高机位人物坐姿照片，主体人物呈年轻成人倾向和东亚外貌倾向，骨盆位于画面下中区域，胸腔向画面中左区域折转，画面左侧手臂肘部弯曲约90度，手指握住红色罐体，镜头向下约35度，画面逆时针roll倾斜约4度。",
                    },
                    ensure_ascii=False,
                )
            if "第2轮" in prompt_text:
                return json.dumps(
                    {
                        "mode": "expert_subject",
                        "基本概述": "高机位人物坐姿照片。",
                        "主体类型": "person",
                        "专家观点": ["人体姿态：头部位于上中区域，胸腔向画面中左区域折转，画面左侧手臂肘部弯曲约90度，手指握住红色罐体。"],
                        "主体细节": "人物骨盆位于画面下中区域，胸腔向画面中左区域折转，肩线左高右低，画面左侧手臂与画面右侧手臂位置分明。",
                        "人物外貌": "主体人物呈年轻成人倾向，东亚外貌倾向，暖白肤色。",
                        "关节角度": "头部yaw向画面右侧约35度，左肘弯曲约90度，右膝弯曲约60度。",
                        "镜头倾斜角度": "高机位俯拍，镜头向下约35度，画面逆时针roll倾斜约4度。",
                        "final_prompt": "高机位人物坐姿照片，骨盆位于画面下中区域，胸腔向画面中左区域折转，画面左侧手臂肘部弯曲约90度。",
                    },
                    ensure_ascii=False,
                )
            if "第1轮" in prompt_text:
                return json.dumps(
                    {
                        "mode": "expert_global",
                        "主体判定": "主体为人物，位于画面上中到右下区域。",
                        "专家计划": ["人体姿态专家：深挖躯干和四肢链。"],
                        "整体结构": "高机位俯拍，灰色背景和红色主体对比。",
                    },
                    ensure_ascii=False,
                )
            return "{}"

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "a.jpg"
            _write_jpeg_stub(image)
            result = run_expert_team_reverse(str(image), chat_fn=fake_chat)

        self.assertEqual(len(prompts), 3)
        self.assertIn("第1轮", prompts[0])
        self.assertIn("第2轮", prompts[1])
        self.assertIn("第3轮", prompts[2])
        self.assertIn("专家模式强制补齐三项", prompts[1])
        self.assertIn("专家模式强制补齐三项", prompts[2])
        self.assertIn("肘部弯曲约90度", result["prompt"])
        self.assertIn("东亚外貌倾向", result["prompt"])
        self.assertIn("画面逆时针roll倾斜约4度", result["prompt"])
        self.assertEqual(result["expert_interrogate"]["mode"], "multi_pass_team")

    def test_expert_team_review_without_final_spec_does_not_replace_subject_output(self):
        def fake_chat(messages, **kwargs):
            prompt_text = messages[1]["content"][0]["text"]
            if "第3轮" in prompt_text:
                return json.dumps(
                    {
                        "mode": "expert_review",
                        "复核结论": "修正后通过。只输出了复核摘要，没有最终规格。",
                        "问题修正": ["确认画面左侧手臂肘部弯曲约90度。"],
                    },
                    ensure_ascii=False,
                )
            if "第2轮" in prompt_text:
                return json.dumps(
                    {
                        "mode": "expert_subject",
                        "基本概述": "高机位人物坐姿照片。",
                        "主体类型": "person",
                        "主体细节": "人物骨盆位于画面下中，胸腔向画面左上折转，画面左侧手臂肘部弯曲约90度。",
                        "final_prompt": "高机位人物坐姿照片，骨盆位于画面下中，胸腔向画面左上折转，画面左侧手臂肘部弯曲约90度。",
                    },
                    ensure_ascii=False,
                )
            if "第1轮" in prompt_text:
                return json.dumps(
                    {
                        "mode": "expert_global",
                        "主体判定": "主体为人物，位于画面中心。",
                        "专家计划": ["人体姿态专家：深挖躯干和四肢链。"],
                    },
                    ensure_ascii=False,
                )
            return "{}"

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "a.jpg"
            _write_jpeg_stub(image)
            result = run_expert_team_reverse(str(image), chat_fn=fake_chat)

        self.assertIn("胸腔向画面左上折转", result["prompt"])
        self.assertIn("胸腔向画面左上折转", result["structured_prompt_json"])
        self.assertNotIn('"反推模式"', result["structured_prompt_json"])
        self.assertNotEqual(result["structured_prompt"]["画面描述"], {"复核": "修正后通过。只输出了复核摘要，没有最终规格。"})
        self.assertIn("修正后通过", json.dumps(result["expert_interrogate"]["review"], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
