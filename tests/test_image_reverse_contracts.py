import unittest

from modules.image_reverse.contracts import (
    REVERSE_MODE_ADVANCED,
    REVERSE_MODE_EXPERT,
    REVERSE_MODE_EXPERT_TEAM,
    REVERSE_MODE_STANDARD,
    ReverseOutput,
    mode_level,
    mode_token_budget,
)
from modules.image_reverse.prompts import (
    build_expert_prompt,
    build_expert_team_global_prompt,
    build_expert_team_review_prompt,
    build_expert_team_subject_prompt,
    build_standard_prompt,
)


class ImageReverseContractTests(unittest.TestCase):
    def test_modes_have_distinct_token_budgets(self):
        self.assertLess(mode_token_budget(REVERSE_MODE_STANDARD), mode_token_budget(REVERSE_MODE_EXPERT))
        self.assertLess(mode_token_budget(REVERSE_MODE_EXPERT), mode_token_budget(REVERSE_MODE_EXPERT_TEAM))
        self.assertEqual(REVERSE_MODE_EXPERT, REVERSE_MODE_ADVANCED)
        self.assertEqual(mode_level(REVERSE_MODE_STANDARD), 0)
        self.assertEqual(mode_level(REVERSE_MODE_ADVANCED), 1)
        self.assertEqual(mode_level(REVERSE_MODE_EXPERT_TEAM), 2)

    def test_reverse_output_exports_compatible_payload(self):
        output = ReverseOutput(
            mode=REVERSE_MODE_EXPERT,
            provider="test-vision",
            prompt="主体位于画面中心，红色上衣，灰色背景",
            negative_prompt=["文字", "水印"],
            visual_spec={"画面描述": {"基本概述": "红色主题人物图"}},
            raw={"基本概述": "红色主题人物图"},
            expert_interrogate={"enabled": True, "mode": "expert", "experts": []},
        )

        payload = output.to_api_payload()

        self.assertEqual(payload["prompt"], "主体位于画面中心，红色上衣，灰色背景")
        self.assertEqual(payload["reverse_mode"], "advanced")
        self.assertEqual(payload["reverse_level"], 1)
        self.assertEqual(payload["reverse_mode_label"], "加强")
        self.assertEqual(payload["promptgen"], payload["prompt"])
        self.assertEqual(payload["prompt_zh"], payload["prompt"])
        self.assertEqual(payload["negative_prompt"], "文字, 水印")
        self.assertIn('"画面描述"', payload["structured_prompt_json"])
        self.assertTrue(payload["expert_interrogate"]["enabled"])

    def test_standard_prompt_is_compact_and_not_expert_team(self):
        prompt = build_standard_prompt()

        self.assertIn("标准：", prompt)
        self.assertIn("必须只输出图中直接看见的事实", prompt)
        self.assertIn("不得猜想", prompt)
        self.assertIn("整体描述", prompt)
        self.assertIn("肢体左右参照规则", prompt)
        self.assertIn("画面左侧手臂", prompt)
        self.assertIn("禁止单独使用“左手、右手", prompt)
        self.assertIn("背景", prompt)
        self.assertIn("前景", prompt)
        self.assertIn("最终提示词", prompt)
        self.assertNotIn("专家团第", prompt)
        self.assertNotIn("aa" + "、ab" + "、ac", prompt)
        self.assertNotIn("b" + "c", prompt)
        self.assertLess(len(prompt), 4200)

    def test_expert_prompt_requires_structured_subject_detail(self):
        prompt = build_expert_prompt()

        self.assertIn("请不要生成图片", prompt)
        self.assertIn("最高规则", prompt)
        self.assertIn("必须只输出图中直接看见的事实", prompt)
        self.assertIn("不得猜想", prompt)
        self.assertIn("禁止使用猜测词", prompt)
        self.assertIn("看不见的属性直接省略", prompt)
        self.assertIn('"结构化视觉规格书"', prompt)
        self.assertIn('"最终提示词"', prompt)
        self.assertIn('"负面约束"', prompt)
        self.assertIn('"整体描述"', prompt)
        self.assertIn('"背景"', prompt)
        self.assertIn('"前景"', prompt)
        self.assertIn('"主体"', prompt)
        self.assertIn('"细节"', prompt)
        self.assertIn("主体人物", prompt)
        self.assertIn("红色易拉罐", prompt)
        self.assertIn("灰色金属墙面", prompt)
        self.assertIn("不得输出角色1", prompt)
        self.assertIn("物体用具体可见名称", prompt)
        self.assertIn("整体描述只写最抽象的画面类型和主旨", prompt)
        self.assertIn("结构化描述顺序必须先整体描述，再背景，再前景，再主体，最后细节", prompt)
        self.assertNotIn('"主体1"', prompt)
        self.assertNotIn('"物体1"', prompt)
        self.assertNotIn("构图镜头：", prompt)
        self.assertNotIn("人物姿态：", prompt)
        self.assertNotIn("服装材质：", prompt)
        self.assertNotIn("光线颜色风格：", prompt)
        self.assertNotIn('"关键保留点"', prompt)
        self.assertNotIn('"不确定项"', prompt)
        self.assertIn("不要输出任何带下划线的内部字段名", prompt)
        self.assertIn("章节标题、字段名、JSON key", prompt)
        self.assertIn("关键保留点、易错点与禁止项、不确定项不得写入最终提示词或结构化视觉规格书", prompt)
        self.assertIn("易错点与禁止项只写入负面约束", prompt)
        self.assertIn("所有字段都是候选字段", prompt)
        self.assertIn("没有可见事实的字段必须整项省略", prompt)
        self.assertIn("不要输出空字符串", prompt)
        self.assertIn("禁止依赖后期清洗", prompt)
        self.assertIn("量化规则", prompt)
        self.assertIn("画面比例与主体占比规则", prompt)
        self.assertIn("近似宽高比", prompt)
        self.assertIn("主体外接框占整个画面的比例", prompt)
        self.assertIn("主体占画面宽度和高度比例", prompt)
        self.assertIn("年龄倾向", prompt)
        self.assertIn("可见族裔/人种外貌倾向", prompt)
        self.assertIn("肤色", prompt)
        self.assertIn("表情与表情依据", prompt)
        self.assertIn("暴露到什么程度", prompt)
        self.assertIn("性暗示", prompt)
        self.assertIn("衣物遮挡边界", prompt)
        self.assertIn("躯干", prompt)
        self.assertIn("左", prompt)
        self.assertIn("右", prompt)
        self.assertIn("构图与镜头", prompt)
        self.assertIn("摄影设备", prompt)
        self.assertIn("拍摄角度", prompt)
        self.assertIn("机位高度", prompt)
        self.assertIn("焦距感", prompt)
        self.assertIn("透视畸变", prompt)
        self.assertIn("入射", prompt)
        self.assertNotIn("aa" + "、ab" + "、ac", prompt)
        self.assertNotIn("b" + "c", prompt)
        self.assertLess(len(prompt), 12000)

    def test_expert_team_prompts_are_separate_stages(self):
        global_prompt = build_expert_team_global_prompt()
        subject_prompt = build_expert_team_subject_prompt({"主体判定": "人物主体", "主体类型": "person"})
        review_prompt = build_expert_team_review_prompt({"主体细节": "人物主体细节"})
        combined_prompt = global_prompt + subject_prompt + review_prompt

        self.assertIn("专家第1轮", global_prompt)
        self.assertIn("专家第2轮", subject_prompt)
        self.assertIn("专家第3轮", review_prompt)
        self.assertIn("必须只输出图中直接看见的事实", combined_prompt)
        self.assertIn("不得猜想", combined_prompt)
        self.assertIn("禁止使用猜测词", combined_prompt)
        self.assertNotIn("专家团第", combined_prompt)
        self.assertIn("专家计划", global_prompt)
        self.assertIn("专家观点", subject_prompt)
        self.assertIn("复核", review_prompt)
        self.assertIn("量化规则", global_prompt)
        self.assertIn("画面比例与主体占比规则", combined_prompt)
        self.assertIn('"画面比例与主体占比"', subject_prompt)
        self.assertIn("近似宽高比", combined_prompt)
        self.assertIn("主体外接框占整个画面的比例", combined_prompt)
        self.assertIn("主体占画面宽度和高度比例", combined_prompt)
        self.assertIn("至少包含两类量化信息", subject_prompt)
        self.assertIn("专家观点只能补充主体细节未覆盖的事实", subject_prompt)
        self.assertIn("整体描述", combined_prompt)
        self.assertIn("背景", subject_prompt)
        self.assertIn("前景", subject_prompt)
        self.assertIn("不得输出角色1", combined_prompt)
        self.assertIn("物体用具体可见名称", combined_prompt)
        self.assertNotIn("构图镜头：", combined_prompt)
        self.assertNotIn("人物姿态：", combined_prompt)
        self.assertNotIn("服装材质：", combined_prompt)
        self.assertNotIn("光线颜色风格：", combined_prompt)
        self.assertIn("摄影设备", combined_prompt)
        self.assertIn("拍摄角度", combined_prompt)
        self.assertIn("机位高度", combined_prompt)
        self.assertIn("焦距感", combined_prompt)
        self.assertIn("透视畸变", combined_prompt)
        self.assertIn("专家模式强制补齐三项", subject_prompt)
        self.assertIn('"人物外貌"', subject_prompt)
        self.assertIn('"关节角度"', subject_prompt)
        self.assertIn('"镜头倾斜角度"', subject_prompt)
        self.assertIn("肢体左右参照规则", combined_prompt)
        self.assertIn("画面左侧肩肘腕", combined_prompt)
        self.assertIn("画面右侧髋膝踝", combined_prompt)
        self.assertIn("禁止单独使用“左手、右手", combined_prompt)
        self.assertIn("相机俯仰角", combined_prompt)
        self.assertIn("画面roll顺/逆时针倾斜角", combined_prompt)
        self.assertIn("年龄倾向", review_prompt)
        self.assertIn("肤色", review_prompt)
        self.assertIn("表情与表情依据", review_prompt)
        self.assertIn("暴露到什么程度", combined_prompt)
        self.assertIn("性暗示", combined_prompt)
        self.assertIn("缺少则补充近似比例", review_prompt)
        self.assertIn("没有可见事实的字段必须整项省略", combined_prompt)
        self.assertIn("禁止依赖后期清洗", combined_prompt)
        self.assertNotIn("aa" + "、ab" + "、ac", combined_prompt)
        self.assertNotIn("b" + "c", combined_prompt)
        self.assertLess(len(global_prompt), 4800)
        self.assertLess(len(subject_prompt), 8200)
        self.assertLess(len(review_prompt), 8400)


if __name__ == "__main__":
    unittest.main()
