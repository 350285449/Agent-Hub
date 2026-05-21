from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_hub.config import (
    AgentConfig,
    cloud_agent_names,
    default_agent_names,
    free_local_agent_names,
    free_local_config,
    is_free_agent,
    normalize_provider,
)


class ConfigTests(unittest.TestCase):
    def test_free_local_config_uses_custom_local_agent(self) -> None:
        config = free_local_config()

        self.assertEqual(config.default_route, default_agent_names())
        self.assertEqual(free_local_agent_names()[0], "ollama-qwen-coder")
        self.assertEqual(default_agent_names()[0], "codex")
        self.assertEqual(default_agent_names()[1], "claude")
        self.assertLess(
            free_local_agent_names().index("ollama-qwen3"),
            free_local_agent_names().index("custom-local"),
        )
        self.assertEqual(cloud_agent_names(), ["codex", "claude", "gemini", "chatgpt"])
        self.assertIn("custom-local", config.agents)
        self.assertEqual(
            set(config.agents),
            {"local-research", *cloud_agent_names(), *free_local_agent_names(), "echo"},
        )
        self.assertTrue(config.free_only)
        self.assertTrue(config.allow_shell_tools)
        self.assertTrue(is_free_agent(config.agents["local-research"]))
        self.assertTrue(is_free_agent(config.agents["codex"]))
        self.assertTrue(is_free_agent(config.agents["claude"]))
        self.assertTrue(is_free_agent(config.agents["gemini"]))
        self.assertTrue(is_free_agent(config.agents["chatgpt"]))
        self.assertEqual(config.agents["codex"].provider, "openai")
        self.assertEqual(config.agents["claude"].provider, "anthropic")
        self.assertEqual(config.agents["gemini"].provider, "gemini")
        self.assertEqual(config.agents["chatgpt"].provider, "openai")
        self.assertEqual(config.agents["codex"].model, "gpt-4o-mini")
        self.assertEqual(config.agents["claude"].model, "claude-3-5-haiku-latest")
        self.assertEqual(config.agents["gemini"].model, "gemini-2.0-flash")
        self.assertEqual(config.agents["chatgpt"].model, "gpt-4o-mini")
        self.assertIsNone(config.agents["codex"].base_url)
        cloud_route = next(route for route in config.routes if route.name == "cloud-agent")
        self.assertEqual(cloud_route.agents, [*cloud_agent_names(), "echo"])
        local_route = next(route for route in config.routes if route.name == "local-agent")
        self.assertEqual(local_route.agents, free_local_agent_names())
        self.assertEqual(config.agents["ollama-qwen-coder"].timeout_seconds, 300.0)
        self.assertTrue(is_free_agent(config.agents["custom-local"]))
        self.assertTrue(is_free_agent(config.agents["ollama-qwen-coder"]))

    def test_cloud_agents_can_be_configured_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AGENT_HUB_CODEX_MODEL": "codex-cloud-model",
                "AGENT_HUB_CLAUDE_MODEL": "claude-cloud-model",
                "AGENT_HUB_GEMINI_MODEL": "gemini-cloud-model",
                "AGENT_HUB_CHATGPT_MODEL": "chatgpt-cloud-model",
                "AGENT_HUB_CODEX_API_KEY_ENV": "CODEX_KEY",
            },
        ):
            config = free_local_config()

        self.assertEqual(config.agents["codex"].model, "codex-cloud-model")
        self.assertEqual(config.agents["claude"].model, "claude-cloud-model")
        self.assertEqual(config.agents["gemini"].model, "gemini-cloud-model")
        self.assertEqual(config.agents["chatgpt"].model, "chatgpt-cloud-model")
        self.assertEqual(config.agents["codex"].api_key_env, "CODEX_KEY")

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
        self.assertEqual(normalize_provider("codex"), "openai")
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
