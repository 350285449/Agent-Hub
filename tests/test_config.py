from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_hub.config import (
    AgentConfig,
    cloud_agent_names,
    config_from_dict,
    config_to_dict,
    default_agent_names,
    free_local_agent_names,
    free_local_config,
    is_free_agent,
    load_config,
    normalize_provider,
    ollama_cloud_agent_names,
)
from agent_hub.discovery import auto_configure_config


class ConfigTests(unittest.TestCase):
    def test_free_local_config_uses_custom_local_agent(self) -> None:
        config = free_local_config()

        self.assertEqual(config.default_route, default_agent_names())
        self.assertEqual(free_local_agent_names()[0], "ollama-qwen-coder")
        self.assertEqual(default_agent_names()[0], "ollama-kimi-cloud")
        self.assertEqual(default_agent_names()[1], "ollama-glm-cloud")
        self.assertNotIn("codex", default_agent_names())
        self.assertLess(
            free_local_agent_names().index("ollama-qwen3"),
            free_local_agent_names().index("custom-local"),
        )
        self.assertEqual(cloud_agent_names(), ["codex", "claude", "gemini", "chatgpt"])
        self.assertIn("custom-local", config.agents)
        self.assertEqual(
            set(config.agents),
            {
                "local-research",
                *ollama_cloud_agent_names(),
                *cloud_agent_names(),
                *free_local_agent_names(),
                "echo",
            },
        )
        self.assertTrue(config.free_only)
        self.assertTrue(config.allow_shell_tools)
        self.assertFalse(config.fast_write_finalize)
        self.assertEqual(config.validation_mode, "basic")
        self.assertTrue(config.auto_validate_after_edits)
        self.assertTrue(config.rollback_on_validation_failure)
        self.assertEqual(config.workspace_checkpoint_retention, 5)
        self.assertTrue(config.prefer_multi_file_patches)
        self.assertTrue(config.context_change_bar_enabled)
        self.assertEqual(config.context_change_bar_threshold, 3)
        self.assertEqual(config.context_change_bar_mode, "light")
        self.assertTrue(config.agent_context_compaction_enabled)
        self.assertEqual(config.agent_context_budget_tokens, 32_000)
        self.assertTrue(is_free_agent(config.agents["local-research"]))
        self.assertTrue(is_free_agent(config.agents["codex"]))
        self.assertTrue(is_free_agent(config.agents["claude"]))
        self.assertTrue(is_free_agent(config.agents["gemini"]))
        self.assertTrue(is_free_agent(config.agents["chatgpt"]))
        self.assertFalse(config.agents["codex"].enabled)
        self.assertFalse(config.agents["claude"].enabled)
        self.assertFalse(config.agents["gemini"].enabled)
        self.assertFalse(config.agents["chatgpt"].enabled)
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
        self.assertEqual(cloud_route.agents, [*ollama_cloud_agent_names(), "echo"])
        research_route = next(route for route in config.routes if route.name == "research")
        self.assertEqual(research_route.agents, ["local-research", *ollama_cloud_agent_names(), "echo"])
        local_route = next(route for route in config.routes if route.name == "local-agent")
        self.assertEqual(local_route.agents, free_local_agent_names())
        self.assertEqual(config.agents["ollama-kimi-cloud"].model, "kimi-k2.6:cloud")
        self.assertEqual(config.agents["ollama-qwen-coder"].timeout_seconds, 300.0)
        self.assertTrue(is_free_agent(config.agents["custom-local"]))
        self.assertTrue(is_free_agent(config.agents["ollama-qwen-coder"]))

    def test_context_change_bar_settings_round_trip(self) -> None:
        config = config_from_dict(
            {
                "context_change_bar_enabled": False,
                "context_change_bar_threshold": 7,
                "context_change_bar_mode": "strict",
                "agent_context_budget_tokens": 12345,
                "agent_context_compaction_enabled": False,
                "prefer_multi_file_patches": False,
                "agents": [],
            }
        )

        self.assertFalse(config.context_change_bar_enabled)
        self.assertEqual(config.context_change_bar_threshold, 7)
        self.assertEqual(config.context_change_bar_mode, "strict")
        self.assertEqual(config.agent_context_budget_tokens, 12345)
        self.assertFalse(config.agent_context_compaction_enabled)
        self.assertFalse(config.prefer_multi_file_patches)

        data = config_to_dict(config)
        self.assertFalse(data["context_change_bar_enabled"])
        self.assertEqual(data["context_change_bar_threshold"], 7)
        self.assertEqual(data["context_change_bar_mode"], "strict")
        self.assertEqual(data["agent_context_budget_tokens"], 12345)
        self.assertFalse(data["agent_context_compaction_enabled"])
        self.assertFalse(data["prefer_multi_file_patches"])

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

    def test_missing_config_is_created_automatically(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"

            config = load_config(path, auto_detect=False)

            self.assertTrue(path.exists())
            self.assertTrue((Path(tmp) / ".agent-hub" / "state").exists())
            self.assertTrue(config.initialization_report["created_default_config"])
            self.assertIn("echo", config.agents)

    def test_available_keyed_providers_are_enabled_at_runtime(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True):
            config = free_local_config()
            config.auto_detect_local_models = False
            report = auto_configure_config(config)

        self.assertTrue(config.agents["codex"].enabled)
        self.assertTrue(config.agents["chatgpt"].enabled)
        enabled_names = {item["agent"] for item in report["enabled_from_environment"]}
        self.assertIn("codex", enabled_names)
        cloud_route = next(route for route in config.routes if route.name == "cloud-agent")
        self.assertIn("codex", cloud_route.agents)
        self.assertIn("chatgpt", config.default_route)

    def test_free_provider_presets_are_added_when_key_is_available(self) -> None:
        with patch.dict("os.environ", {"GROQ_API_KEY": "groq-key"}, clear=True):
            config = free_local_config()
            config.auto_detect_local_models = False
            report = auto_configure_config(config)

        self.assertIn("groq-qwen3-32b", config.agents)
        self.assertTrue(config.agents["groq-qwen3-32b"].enabled)
        self.assertEqual(config.agents["groq-qwen3-32b"].provider_type, "groq")
        cloud_route = next(route for route in config.routes if route.name == "cloud-agent")
        self.assertIn("groq-qwen3-32b", cloud_route.agents)
        added_names = {item["agent"] for item in report["added_provider_presets"]}
        self.assertIn("groq-qwen3-32b", added_names)

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

    def test_provider_metadata_fields_parse_from_config(self) -> None:
        config = config_from_dict(
            {
                "agents": [
                    {
                        "name": "groq-qwen",
                        "provider": "openai-compatible",
                        "provider_type": "groq",
                        "model": "qwen/qwen3-32b",
                        "base_url": "https://api.groq.com/openai/v1",
                        "api_key_env": "GROQ_API_KEY",
                        "free": True,
                        "coding_score": 0.9,
                        "reasoning_score": 0.8,
                        "speed_score": 0.95,
                        "supports_tools": True,
                        "supports_json": True,
                        "supports_streaming": True,
                        "supports_vision": False,
                        "supports_function_calling": True,
                        "priority": 75,
                        "context_window": 128000,
                    }
                ],
                "routes": [{"name": "cloud-agent", "agents": ["groq-qwen"]}],
                "default_route": ["groq-qwen"],
                "group_roles": {"coder": "groq-qwen"},
            }
        )

        agent = config.agents["groq-qwen"]
        self.assertEqual(agent.provider_type, "groq")
        self.assertEqual(normalize_provider("groq"), "openai-compatible")
        self.assertTrue(agent.supports_tools)
        self.assertTrue(agent.supports_function_calling)
        self.assertEqual(agent.priority, 75)
        self.assertEqual(config.group_roles["coder"], "groq-qwen")


if __name__ == "__main__":
    unittest.main()
