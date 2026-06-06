from __future__ import annotations

import unittest
from pathlib import Path
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
from agent_hub.config_reference import documented_config_keys, generate_config_reference
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
        self.assertEqual(cloud_agent_names(), ["codex", "codex-cli", "claude", "gemini", "chatgpt"])
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
        self.assertFalse(config.allow_shell_tools)
        self.assertEqual(config.shell_command_policy, "deny")
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
        self.assertTrue(is_free_agent(config.agents["codex-cli"]))
        self.assertTrue(is_free_agent(config.agents["claude"]))
        self.assertTrue(is_free_agent(config.agents["gemini"]))
        self.assertTrue(is_free_agent(config.agents["chatgpt"]))
        self.assertFalse(config.agents["codex"].enabled)
        self.assertFalse(config.agents["codex-cli"].enabled)
        self.assertFalse(config.agents["claude"].enabled)
        self.assertFalse(config.agents["gemini"].enabled)
        self.assertFalse(config.agents["chatgpt"].enabled)
        self.assertEqual(config.agents["codex"].provider, "openai")
        self.assertEqual(config.agents["codex-cli"].provider, "codex-cli")
        self.assertEqual(config.agents["claude"].provider, "anthropic")
        self.assertEqual(config.agents["gemini"].provider, "gemini")
        self.assertEqual(config.agents["chatgpt"].provider, "openai")
        self.assertEqual(config.agents["codex"].model, "gpt-4o-mini")
        self.assertEqual(config.agents["codex-cli"].model, "gpt-5.5")
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
        self.assertIsNone(config.agents["ollama-qwen-coder"].max_tokens)
        self.assertIsNone(config.agents["codex"].max_tokens)
        self.assertEqual(config.native_stream_failure_policy, "recover")
        self.assertTrue(config.compatibility_mode["universal_routing"])
        self.assertTrue(config.compatibility_mode["emulate_tools"])
        self.assertIsNone(config.compatibility_mode["max_context_tokens"])
        self.assertTrue(config.routing["unlimited_default"])
        self.assertEqual(config.routing["max_tokens_mode"], "auto")
        self.assertEqual(config.routing["context_budget_mode"], "auto")
        self.assertTrue(config.routing["auto_failover"])
        self.assertTrue(config.routing["failover_on_slow_stream"])
        self.assertTrue(config.routing["failover_on_quota_exhaustion"])
        self.assertTrue(config.routing["continue_after_output_limit"])
        self.assertEqual(config.routing["max_provider_attempts"], 5)
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

    def test_adaptive_learning_settings_round_trip(self) -> None:
        config = config_from_dict(
            {
                "adaptive_learning_enabled": False,
                "adaptive_routing_enabled": False,
                "adaptive_workflow_upgrades_enabled": False,
                "agents": [],
            }
        )

        self.assertFalse(config.adaptive_learning_enabled)
        self.assertFalse(config.adaptive_routing_enabled)
        self.assertFalse(config.adaptive_workflow_upgrades_enabled)

        data = config_to_dict(config)
        self.assertFalse(data["adaptive_learning_enabled"])
        self.assertFalse(data["adaptive_routing_enabled"])
        self.assertFalse(data["adaptive_workflow_upgrades_enabled"])

    def test_unlimited_routing_settings_round_trip(self) -> None:
        config = config_from_dict(
            {
                "routing": {
                    "unlimited_default": True,
                    "max_tokens_mode": "auto",
                    "context_budget_mode": "auto",
                    "auto_failover": True,
                    "auto_retry": True,
                    "free_first": False,
                    "prefer_available_quota": True,
                    "failover_on_slow_stream": False,
                    "failover_on_quota_exhaustion": True,
                    "continue_after_output_limit": True,
                    "max_provider_attempts": 7,
                    "slow_first_token_timeout_seconds": 3,
                    "stream_stall_timeout_seconds": 4,
                    "min_tokens_per_second": 1.5,
                    "cooldown_rate_limit_seconds": 9,
                    "cooldown_overload_seconds": 8,
                    "cooldown_quota_seconds": 99,
                },
                "agents": [],
            }
        )

        self.assertEqual(config.routing["max_provider_attempts"], 7)
        self.assertEqual(config.routing["max_tokens_mode"], "auto")
        self.assertFalse(config.routing["free_first"])
        self.assertFalse(config.routing["failover_on_slow_stream"])
        self.assertEqual(config.quota_cooldown_seconds, 99)
        self.assertEqual(config.rate_limit_cooldown_seconds, 9)
        data = config_to_dict(config)
        self.assertEqual(data["routing"]["stream_stall_timeout_seconds"], 4.0)
        self.assertEqual(data["routing"]["cooldown_quota_seconds"], 99.0)

    def test_phase5_hardening_settings_round_trip(self) -> None:
        config = config_from_dict(
            {
                "native_stream_failure_policy": "fallback_provider",
                "diagnostics_auth_token_env": "AGENT_HUB_DIAG_TOKEN",
                "trusted_plugins": ["provider.demo"],
                "plugin_trust_registry": ".agent-hub/plugin-trust.json",
                "plugin_signature_key_env": "AGENT_HUB_PLUGIN_SIGNATURE_KEY",
                "plugin_allow_unsigned": True,
                "plugin_execution_enabled": False,
                "plugin_capability_grants": {"provider.demo": ["provider.read"]},
                "mcp_execution_enabled": True,
                "mcp_timeout_seconds": 15,
                "enterprise_mode_enabled": True,
                "enterprise_default_workspace_id": "workspace-1",
                "enterprise_users": [{"id": "alice", "roles": ["developer"]}],
                "enterprise_roles": [{"name": "developer", "permissions": ["file_write"]}],
                "enterprise_permission_grants": [
                    {
                        "subject_id": "alice",
                        "workspace_id": "workspace-1",
                        "permission": "workspace_cloud",
                    }
                ],
                "enterprise_audit_retention_days": 30,
                "agents": [],
            }
        )

        data = config_to_dict(config)

        self.assertEqual(data["native_stream_failure_policy"], "fallback_provider")
        self.assertEqual(data["diagnostics_auth_token_env"], "AGENT_HUB_DIAG_TOKEN")
        self.assertEqual(data["trusted_plugins"], ["provider.demo"])
        self.assertEqual(data["plugin_trust_registry"].replace("\\", "/"), ".agent-hub/plugin-trust.json")
        self.assertEqual(data["plugin_signature_key_env"], "AGENT_HUB_PLUGIN_SIGNATURE_KEY")
        self.assertTrue(data["plugin_allow_unsigned"])
        self.assertFalse(data["plugin_execution_enabled"])
        self.assertEqual(data["plugin_capability_grants"], {"provider.demo": ["provider.read"]})
        self.assertTrue(data["mcp_execution_enabled"])
        self.assertEqual(data["mcp_timeout_seconds"], 15)
        self.assertTrue(data["enterprise_mode_enabled"])
        self.assertEqual(data["enterprise_users"][0]["id"], "alice")
        self.assertEqual(data["enterprise_audit_retention_days"], 30)

    def test_generated_config_reference_is_current(self) -> None:
        reference = Path("docs/config-reference.md").read_text(encoding="utf-8")

        self.assertEqual(reference, generate_config_reference())
        self.assertLessEqual(set(config_to_dict(free_local_config())), documented_config_keys())

    def test_cloud_agents_can_be_configured_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AGENT_HUB_CODEX_MODEL": "codex-cloud-model",
                "AGENT_HUB_CODEX_CLI_MODEL": "codex-cli-model",
                "AGENT_HUB_CLAUDE_MODEL": "claude-cloud-model",
                "AGENT_HUB_GEMINI_MODEL": "gemini-cloud-model",
                "AGENT_HUB_CHATGPT_MODEL": "chatgpt-cloud-model",
                "AGENT_HUB_CODEX_API_KEY_ENV": "CODEX_KEY",
            },
        ):
            config = free_local_config()

        self.assertEqual(config.agents["codex"].model, "codex-cloud-model")
        self.assertEqual(config.agents["codex-cli"].model, "codex-cli-model")
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
        self.assertEqual(normalize_provider("codex-cli"), "codex-cli")
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

    def test_config_from_dict_normalizes_string_booleans_and_routes(self) -> None:
        config = config_from_dict(
            {
                "port": "not-a-port",
                "state_dir": None,
                "agent_max_steps": "bad",
                "local_model_probe_timeout_seconds": "bad",
                "quota_cooldown_seconds": "bad",
                "rate_limit_cooldown_seconds": "bad",
                "validation_repair_attempts": "bad",
                "workspace_checkpoint_retention": "bad",
                "agents": [
                    {
                        "name": "local",
                        "provider": "echo",
                        "enabled": "false",
                        "free": "false",
                        "headers": "not-a-map",
                        "timeout_seconds": "not-a-number",
                    }
                ],
                "routes": [{"name": "solo", "agents": "local", "keywords": "debug"}],
                "default_route": "local",
                "validation_commands": "python -m pytest",
                "group_roles": "not-a-map",
                "mcp_servers": [{"name": "tools", "enabled": "false", "args": "serve", "env": "bad"}],
            }
        )

        agent = config.agents["local"]
        self.assertEqual(config.port, 8787)
        self.assertEqual(config.state_dir, Path(".agent-hub/state"))
        self.assertEqual(config.agent_max_steps, 8)
        self.assertEqual(config.local_model_probe_timeout_seconds, 0.35)
        self.assertEqual(config.quota_cooldown_seconds, config.routing["cooldown_quota_seconds"])
        self.assertEqual(config.rate_limit_cooldown_seconds, config.routing["cooldown_rate_limit_seconds"])
        self.assertEqual(config.validation_repair_attempts, 3)
        self.assertEqual(config.workspace_checkpoint_retention, 5)
        self.assertFalse(agent.enabled)
        self.assertFalse(is_free_agent(agent))
        self.assertEqual(agent.headers, {})
        self.assertEqual(agent.timeout_seconds, 120.0)
        self.assertEqual(config.default_route, ["local"])
        self.assertEqual(config.routes[0].agents, ["local"])
        self.assertEqual(config.routes[0].keywords, ["debug"])
        self.assertEqual(config.validation_commands, ["python -m pytest"])
        self.assertEqual(config.group_roles, {})
        self.assertFalse(config.mcp_servers[0].enabled)
        self.assertEqual(config.mcp_servers[0].args, ["serve"])
        self.assertEqual(config.mcp_servers[0].env, {})

    def test_config_from_dict_clamps_runtime_limits(self) -> None:
        config = config_from_dict(
            {
                "port": 999999,
                "agent_max_steps": 999,
                "routing_memory_retention_days": 999999,
                "validation_repair_attempts": 999,
                "workspace_checkpoint_retention": 999,
                "agents": [],
            }
        )

        self.assertEqual(config.port, 65535)
        self.assertEqual(config.agent_max_steps, 50)
        self.assertEqual(config.routing_memory_retention_days, 3650)
        self.assertEqual(config.validation_repair_attempts, 50)
        self.assertEqual(config.workspace_checkpoint_retention, 100)

        minimums = config_from_dict(
            {
                "port": -1,
                "agent_max_steps": -1,
                "routing_memory_retention_days": -1,
                "validation_repair_attempts": -1,
                "workspace_checkpoint_retention": -1,
                "agents": [],
            }
        )
        self.assertEqual(minimums.port, 1)
        self.assertEqual(minimums.agent_max_steps, 1)
        self.assertEqual(minimums.routing_memory_retention_days, 1)
        self.assertEqual(minimums.validation_repair_attempts, 0)
        self.assertEqual(minimums.workspace_checkpoint_retention, 0)


if __name__ == "__main__":
    unittest.main()
