from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_hub.config import (
    AgentConfig,
    cloud_agent_names,
    free_local_agent_names,
    free_local_config,
    is_free_agent,
    normalize_provider,
)


class ConfigTests(unittest.TestCase):
    def test_free_local_config_uses_custom_local_agent(self) -> None:
        config = free_local_config()

        self.assertEqual(config.default_route, [*cloud_agent_names(), *free_local_agent_names(), "echo"])
        self.assertEqual(free_local_agent_names()[0], "ollama-qwen-coder")
        self.assertLess(
            free_local_agent_names().index("ollama-qwen3"),
            free_local_agent_names().index("custom-local"),
        )
        self.assertEqual(cloud_agent_names(), ["claude", "gemini", "chatgpt"])
        self.assertIn("custom-local", config.agents)
        self.assertEqual(
            set(config.agents),
            {"local-research", *cloud_agent_names(), *free_local_agent_names(), "echo"},
        )
        self.assertTrue(config.free_only)
        self.assertTrue(config.allow_shell_tools)
        self.assertTrue(is_free_agent(config.agents["local-research"]))
        self.assertTrue(is_free_agent(config.agents["claude"]))
        self.assertTrue(is_free_agent(config.agents["gemini"]))
        self.assertTrue(is_free_agent(config.agents["chatgpt"]))
        self.assertEqual(config.agents["claude"].provider, "openai-compatible")
        self.assertEqual(config.agents["gemini"].provider, "openai-compatible")
        self.assertEqual(config.agents["chatgpt"].provider, "openai-compatible")
        self.assertEqual(config.agents["claude"].model, "qwen2.5-coder:7b")
        self.assertEqual(config.agents["gemini"].model, "gemma3:4b")
        self.assertEqual(config.agents["chatgpt"].model, "llama3.2")
        self.assertTrue(is_free_agent(config.agents["custom-local"]))
        self.assertTrue(is_free_agent(config.agents["ollama-qwen-coder"]))

    def test_cloud_style_aliases_can_be_configured_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AGENT_HUB_CLOUD_ALIAS_BASE_URL": "http://127.0.0.1:1234",
                "AGENT_HUB_CLAUDE_LOCAL_MODEL": "lmstudio-loaded-model",
                "AGENT_HUB_GEMINI_LOCAL_MODEL": "gemma-custom",
                "AGENT_HUB_CHATGPT_LOCAL_MODEL": "llama-custom",
            },
        ):
            config = free_local_config()

        self.assertEqual(config.agents["claude"].base_url, "http://127.0.0.1:1234")
        self.assertEqual(config.agents["gemini"].base_url, "http://127.0.0.1:1234")
        self.assertEqual(config.agents["chatgpt"].base_url, "http://127.0.0.1:1234")
        self.assertEqual(config.agents["claude"].model, "lmstudio-loaded-model")
        self.assertEqual(config.agents["gemini"].model, "gemma-custom")
        self.assertEqual(config.agents["chatgpt"].model, "llama-custom")

    def test_custom_local_agent_can_be_configured_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AGENT_HUB_LOCAL_BASE_URL": "http://127.0.0.1:9010",
                "AGENT_HUB_LOCAL_MODEL": "my-model",
                "AGENT_HUB_LOCAL_CONTEXT_WINDOW": "12345",
                "AGENT_HUB_LOCAL_MAX_TOKENS": "678",
            },
        ):
            agent = free_local_config().agents["custom-local"]

        self.assertEqual(agent.base_url, "http://127.0.0.1:9010")
        self.assertEqual(agent.model, "my-model")
        self.assertEqual(agent.context_window, 12345)
        self.assertEqual(agent.max_tokens, 678)

    def test_provider_names_are_normalized_for_friendly_aliases(self) -> None:
        self.assertEqual(normalize_provider("chatgpt"), "openai")
        self.assertEqual(normalize_provider("claude"), "anthropic")
        self.assertEqual(normalize_provider("google"), "gemini")
        self.assertEqual(normalize_provider("local-research"), "local-research")
        self.assertEqual(normalize_provider("local-web"), "local-research")
        self.assertEqual(normalize_provider("gemma"), "openai-compatible")
        self.assertEqual(normalize_provider("gema"), "openai-compatible")

    def test_explicit_free_flag_overrides_provider_guess(self) -> None:
        self.assertTrue(
            is_free_agent(
                AgentConfig(
                    name="gemini-free-tier",
                    provider="gemini",
                    model="gemini-model",
                    free=True,
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
