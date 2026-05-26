import unittest

from modules.mobile_agent_llm import (
    OpenAICompatibleMobileAgentProvider,
    MobileAgentLlmProvider,
    _build_messages,
    build_default_model_path,
    build_mobile_agent_llm_provider,
    response_from_llm_decision,
    try_parse_llm_decision,
)


class MobileAgentLlmTests(unittest.TestCase):
    def test_parse_llm_decision_extracts_json_from_model_text(self):
        text = """
        好的，我来判断。
        {"action":"chat","reply":"可以先聊清楚需求。","ready":false}
        """

        decision = try_parse_llm_decision(text)

        self.assertEqual(decision["action"], "chat")
        self.assertEqual(decision["reply"], "可以先聊清楚需求。")
        self.assertFalse(decision["ready"])

    def test_parse_llm_decision_rejects_invalid_action(self):
        self.assertIsNone(try_parse_llm_decision('{"action":"delete_everything","reply":"no"}'))

    def test_parse_llm_decision_accepts_simple_key_value_fallback(self):
        decision = try_parse_llm_decision("ask_more, prompt=你想要什么姿势或背景细节？")

        self.assertEqual(decision["action"], "ask_more")
        self.assertEqual(decision["reply"], "你想要什么姿势或背景细节？")

    def test_parse_llm_decision_accepts_partial_json_action(self):
        decision = try_parse_llm_decision('{"action":"propose_generation","reply":"好的，我来')

        self.assertEqual(decision["action"], "propose_generation")
        self.assertTrue(decision["ready"])

    def test_chat_decision_keeps_generation_card_closed(self):
        provider = MobileAgentLlmProvider(lambda messages, timeout_ms=8000: '{"action":"chat","reply":"你好，可以聊。"}')

        response = response_from_llm_decision(
            provider.decide("你好", {"messages": []}, {"llm_timeout_ms": 5000}),
            "你好",
            {"default_text_to_image_workflow": "t2i.json"},
            workflow_available=True,
        )

        self.assertEqual(response["response_type"], "chat")
        self.assertEqual(response["intent"], "llm_chat")
        self.assertEqual(response["assistant_message"], "你好，可以聊。")
        self.assertEqual(response["resolved_workflow"], "")

    def test_generation_decision_builds_confirm_contract(self):
        provider = MobileAgentLlmProvider(lambda messages, timeout_ms=8000: """
            {"action":"propose_generation","reply":"我整理好了，确认后生成。","ready":true,
             "prompt":"雨夜里的赛博朋克猫咪，霓虹灯，电影感","style":"cinematic","aspect_ratio":"9:16"}
        """)

        response = response_from_llm_decision(
            provider.decide("做一张雨夜猫咪", {"messages": []}, {"llm_timeout_ms": 5000}),
            "做一张雨夜猫咪",
            {
                "default_text_to_image_workflow": "t2i.json",
                "allowed_styles": ["cinematic", "anime"],
                "allowed_ratios": ["1:1", "9:16"],
            },
            workflow_available=True,
        )

        self.assertEqual(response["response_type"], "confirm")
        self.assertEqual(response["intent"], "text_to_image")
        self.assertEqual(response["compiled_prompt"], "雨夜里的赛博朋克猫咪，霓虹灯，电影感")
        self.assertEqual(response["style"], "cinematic")
        self.assertEqual(response["aspect_ratio"], "9:16")
        self.assertEqual(response["resolved_workflow"], "t2i.json")

    def test_generation_decision_returns_structured_brief_and_clean_prompt(self):
        provider = MobileAgentLlmProvider(lambda messages, timeout_ms=8000: """
            {"action":"propose_generation","reply":"确认后生成。","ready":true,
             "prompt":"我想要帮我出一张漫画风格的小猫咪照片，雨夜，霓虹灯",
             "subject":"小猫咪","scene":"雨夜城市街道","style":"anime",
             "lighting":"霓虹灯","composition":"半身特写","mood":"可爱但有电影感",
             "negative":"低清晰度，文字水印","aspect_ratio":"1:1"}
        """)

        response = response_from_llm_decision(
            provider.decide("我想要帮我出一张漫画风格的小猫咪照片，雨夜，霓虹灯", {"messages": []}, {"llm_timeout_ms": 5000}),
            "我想要帮我出一张漫画风格的小猫咪照片，雨夜，霓虹灯",
            {
                "default_text_to_image_workflow": "t2i.json",
                "allowed_styles": ["cinematic", "anime"],
                "allowed_ratios": ["1:1", "9:16"],
            },
            workflow_available=True,
        )

        brief = response["creative_brief"]
        self.assertEqual(brief["task_type"], "text_to_image")
        self.assertEqual(brief["subject"], "小猫咪")
        self.assertEqual(brief["scene"], "雨夜城市街道")
        self.assertEqual(brief["lighting"], "霓虹灯")
        self.assertEqual(brief["negative"], "低清晰度，文字水印")
        self.assertNotIn("我想要", response["compiled_prompt"])
        self.assertNotIn("帮我", response["compiled_prompt"])
        self.assertEqual(brief["final_prompt"], response["compiled_prompt"])

    def test_followup_edit_uses_previous_brief_and_image_to_image_workflow(self):
        provider = MobileAgentLlmProvider(lambda messages, timeout_ms=8000: """
            {"action":"propose_generation","reply":"我会基于上一张调整。","ready":true,
             "prompt":"改成更明亮一些","style":"cinematic","aspect_ratio":"1:1"}
        """)

        response = response_from_llm_decision(
            provider.decide("改成更明亮一些", {"messages": []}, {"llm_timeout_ms": 5000}),
            "改成更明亮一些",
            {
                "default_text_to_image_workflow": "t2i.json",
                "default_image_to_image_workflow": "i2i.json",
                "allowed_styles": ["cinematic", "anime"],
                "allowed_ratios": ["1:1", "9:16"],
            },
            workflow_available=True,
            context={
                "active_brief": {
                    "compiled_prompt": "赛博朋克猫咪，雨夜，霓虹灯，电影感",
                    "style": "cinematic",
                    "aspect_ratio": "1:1",
                },
                "last_result": {"image": "user1/cat.png", "id": "job1"},
            },
        )

        self.assertEqual(response["intent"], "image_to_image")
        self.assertEqual(response["workflow"], "default_image_to_image")
        self.assertEqual(response["resolved_workflow"], "i2i.json")
        self.assertEqual(response["source_result"]["image"], "user1/cat.png")
        self.assertEqual(response["creative_brief"]["source_image"], "user1/cat.png")
        self.assertEqual(response["creative_brief"]["edit_instruction"], "更明亮一些")
        self.assertIn("赛博朋克猫咪，雨夜，霓虹灯，电影感", response["compiled_prompt"])
        self.assertIn("更明亮一些", response["compiled_prompt"])

    def test_build_messages_injects_memory_without_duplicating_current_turn(self):
        messages = _build_messages(
            "改成雨夜",
            {
                "memory_summary": "上一版创作方案：赛博朋克猫咪，霓虹灯",
                "active_brief": {
                    "compiled_prompt": "赛博朋克猫咪，霓虹灯，电影感",
                    "style": "cinematic",
                    "aspect_ratio": "1:1",
                    "workflow": "t2i.json",
                },
                "last_result": {"image": "user1/2026-05-26/cat.png", "id": "job1"},
                "messages": [
                    {"role": "user", "text": "帮我出一张猫咪"},
                    {"role": "assistant", "text": "我整理好了方案。"},
                    {"role": "user", "text": "改成雨夜"},
                ],
            },
        )

        joined = "\n".join(item["content"] for item in messages)
        self.assertIn("上下文记忆摘要", joined)
        self.assertIn("赛博朋克猫咪，霓虹灯，电影感", joined)
        self.assertIn("user1/2026-05-26/cat.png", joined)
        self.assertEqual([m for m in messages if m["role"] == "user" and m["content"] == "改成雨夜"], [{"role": "user", "content": "改成雨夜"}])

    def test_default_model_path_finds_parent_repo_model_dir(self):
        path = build_default_model_path("/Users/ai/projects/ez-comfyui-showcase/.worktrees/mobile-agent-creator")

        self.assertTrue(path.endswith("model/gemma-4-E2B-it-Q4_K_M.gguf"))

    def test_build_provider_prefers_admin_openai_compatible_settings(self):
        provider = build_mobile_agent_llm_provider(
            "/Users/ai/projects/ez-comfyui-showcase/.worktrees/mobile-agent-creator",
            {
                "llm_enabled": True,
                "llm_provider": "openai_compatible",
                "llm_base_url": "http://127.0.0.1:8080/v1",
                "llm_model": "gemma-4-e2b",
                "llm_api_key": "local-key",
            },
        )

        self.assertIsInstance(provider, OpenAICompatibleMobileAgentProvider)
        self.assertEqual(provider.base_url, "http://127.0.0.1:8080/v1")
        self.assertEqual(provider.model, "gemma-4-e2b")


if __name__ == "__main__":
    unittest.main()
