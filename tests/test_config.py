from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_hub.config import AgentConfig, free_local_config, is_free_agent, normalize_provider


class ConfigTests(unittest.TestCase):
    def test_free_local_config_uses_custom_local_agent(self) -> None:
        config = free_local_config()

        self.assertEqual(config.default_route, ["custom-local", "echo"])
        self.assertIn("custom-local", config.agents)
        self.assertEqual(set(config.agents), {"custom-local", "echo"})
        self.assertTrue(config.free_only)
        self.assertTrue(is_free_agent(config.agents["custom-local"]))

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
