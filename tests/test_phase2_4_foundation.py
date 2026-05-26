from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen

from agent_hub.config import AgentConfig, HubConfig, RouteRule, config_from_dict, config_to_dict
from agent_hub.core.router import AgentRouter
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.observability import record_event
from agent_hub.plugins import discover_plugins
from agent_hub.security.secrets import masked_agent_config
from agent_hub.server import AgentHubHTTPServer
from agent_hub.streaming import normalize_stream_chunk
from agent_hub.token_optimizer import ContextCache, TokenOptimizer, safe_truncate_messages


class PhaseTwoFourFoundationTests(unittest.TestCase):
    def test_config_round_trips_plugin_token_and_cost_options(self) -> None:
        config = config_from_dict(
            {
                "state_dir": ".agent-hub/state",
                "workspace_dir": ".",
                "context_cache_enabled": False,
                "context_cache_max_entries": 42,
                "context_summarization_enabled": True,
                "plugin_dirs": [".agent-hub/custom-plugins"],
                "plugins_enabled": True,
                "enabled_plugins": ["provider.demo"],
                "disabled_plugins": ["tool.old"],
                "agents": [
                    {
                        "name": "cheap",
                        "provider": "openai-compatible",
                        "model": "cheap-model",
                        "cost_per_million_input": 0.1,
                        "cost_per_million_output": 0.2,
                    }
                ],
            }
        )

        data = config_to_dict(config)

        self.assertFalse(data["context_cache_enabled"])
        self.assertEqual(data["context_cache_max_entries"], 42)
        self.assertEqual(data["enabled_plugins"], ["provider.demo"])
        self.assertEqual(data["agents"][0]["cost_per_million_input"], 0.1)

    def test_cost_aware_routing_prefers_cheaper_provider_when_other_scores_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                workspace_dir=Path(tmp),
                approval_mode="auto",
                free_only=False,
                default_route=["expensive", "cheap"],
                routes=[RouteRule(name="coding", agents=["expensive", "cheap"])],
                agents={
                    "expensive": AgentConfig(
                        name="expensive",
                        provider="openai-compatible",
                        model="expensive-model",
                        base_url="http://127.0.0.1:9999",
                        cost_per_million_input=20,
                        cost_per_million_output=80,
                    ),
                    "cheap": AgentConfig(
                        name="cheap",
                        provider="openai-compatible",
                        model="cheap-model",
                        base_url="http://127.0.0.1:9999",
                        cost_per_million_input=0.1,
                        cost_per_million_output=0.2,
                    ),
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(self.agent.name)
                    return ProviderResult(text=self.agent.name, model=self.agent.model, finish_reason="stop")

            response = AgentRouter(config, provider_factory=Provider).route(
                HubRequest(session_id="s", route="coding", messages=[{"role": "user", "content": "hello"}])
            )

            self.assertEqual(response.agent, "cheap")
            self.assertEqual(calls, ["cheap"])

    def test_fastest_adaptive_routing_uses_observed_latency_in_real_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                workspace_dir=Path(tmp),
                approval_mode="auto",
                free_only=False,
                default_route=["slow", "fast"],
                agents={
                    "slow": AgentConfig(
                        name="slow",
                        provider="openai-compatible",
                        model="slow-model",
                        base_url="http://127.0.0.1:9999",
                    ),
                    "fast": AgentConfig(
                        name="fast",
                        provider="openai-compatible",
                        model="fast-model",
                        base_url="http://127.0.0.1:9999",
                    ),
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(self.agent.name)
                    if self.agent.name == "slow":
                        time.sleep(0.02)
                    return ProviderResult(text=self.agent.name, model=self.agent.model, finish_reason="stop")

            router = AgentRouter(config, provider_factory=Provider)
            router.route(
                HubRequest(
                    session_id="slow",
                    preferred_agent="slow",
                    messages=[{"role": "user", "content": "hello"}],
                )
            )
            router.route(
                HubRequest(
                    session_id="fast",
                    preferred_agent="fast",
                    messages=[{"role": "user", "content": "hello"}],
                )
            )
            response = router.route(
                HubRequest(
                    session_id="adaptive",
                    messages=[{"role": "user", "content": "hello"}],
                    raw={"routing_mode": "fastest"},
                )
            )

            self.assertEqual(response.agent, "fast")
            self.assertEqual(calls[-1], "fast")

    def test_token_optimizer_cache_summarization_and_safe_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = ContextCache(Path(tmp) / "cache.json", enabled=True, max_entries=4)
            messages = [{"role": "user", "content": "x" * 2000} for _ in range(8)]

            def summarize(items: list[dict], budget: int) -> list[dict]:
                return [{"role": "user", "content": "summary " + str(len(items))}]

            optimizer = TokenOptimizer(
                cache=cache,
                summarization_enabled=True,
                summarization_hook=summarize,
            )
            first = optimizer.optimize(messages, max_context_tokens=1000)
            second = optimizer.optimize(messages, max_context_tokens=1000)

            self.assertTrue(first.summarized)
            self.assertFalse(first.cache_hit)
            self.assertTrue(second.cache_hit)
            self.assertLess(first.final_tokens, first.original_tokens)

            truncated = safe_truncate_messages(messages, 500)
            self.assertLessEqual(len(truncated), len(messages))

    def test_stream_normalization_ignores_empty_and_repairs_common_shapes(self) -> None:
        self.assertIsNone(normalize_stream_chunk("", default_model="model"))
        self.assertIsNone(normalize_stream_chunk({}, default_model="model"))

        chunk = normalize_stream_chunk(
            {"choices": [{"delta": {"content": "hello"}, "finish_reason": None}], "model": "m"},
            default_model="model",
        )

        self.assertIsNotNone(chunk)
        self.assertEqual(chunk.text, "hello")
        self.assertEqual(chunk.model, "m")

    def test_plugin_discovery_manifest_enable_disable_and_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "demo"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "provider.demo",
                        "name": "Demo Provider",
                        "type": "provider",
                        "version": "1.0.0",
                        "entrypoint": "provider.py",
                        "enabled_by_default": False,
                        "permissions": ["network"],
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
                enabled_plugins=["provider.demo"],
            )

            result = discover_plugins(config)

            self.assertEqual(len(result.plugins), 1)
            self.assertTrue(result.plugins[0].enabled)
            self.assertFalse(result.plugins[0].sandbox["code_execution"])
            self.assertTrue(result.plugins[0].sandbox["entrypoint_allowed"])
            self.assertFalse(result.plugins[0].trusted)
            self.assertFalse(result.plugins[0].registerable)

    def test_plugin_discovery_does_not_execute_or_allow_escaping_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "demo"
            plugin_dir.mkdir(parents=True)
            (root / "boom.py").write_text("raise RuntimeError('should not import')", encoding="utf-8")
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "tool.demo",
                        "name": "Demo Tool",
                        "type": "tool",
                        "entrypoint": "../../boom.py",
                        "enabled_by_default": True,
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
            )

            result = discover_plugins(config)

            self.assertEqual(len(result.plugins), 1)
            self.assertTrue(result.plugins[0].enabled)
            self.assertFalse(result.plugins[0].sandbox["code_execution"])
            self.assertFalse(result.plugins[0].sandbox["entrypoint_allowed"])

    def test_trusted_plugins_register_metadata_only_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "demo"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "provider.demo",
                        "name": "Demo Provider",
                        "type": "provider",
                        "enabled_by_default": True,
                        "metadata": {"models": ["demo-model"], "supports_streaming": True},
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
                trusted_plugins=["provider.demo"],
            )

            body = discover_plugins(config).to_dict()

            self.assertEqual(body["registered_count"], 1)
            provider = body["registered_capabilities"]["providers"][0]
            self.assertEqual(provider["id"], "provider.demo")
            self.assertEqual(provider["metadata"]["models"], ["demo-model"])

    def test_untrusted_plugins_do_not_register_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "demo"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "tool.demo",
                        "name": "Demo Tool",
                        "type": "tool",
                        "enabled_by_default": True,
                        "metadata": {"tool": "demo"},
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
            )

            body = discover_plugins(config).to_dict()

            self.assertEqual(body["registered_count"], 0)
            self.assertEqual(body["plugins"][0]["registration_reason"], "plugin_untrusted")

    def test_plugin_manifest_schema_rejects_unknown_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "bad"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "bad.demo",
                        "type": "tool",
                        "exec": "bad.py",
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(state_dir=root / "state", workspace_dir=root, plugin_dirs=[root / "plugins"])

            result = discover_plugins(config)

            self.assertEqual(result.plugins, [])
            self.assertIn("Unknown manifest keys", result.errors[0].message)

    def test_secret_masking_for_provider_configs(self) -> None:
        agent = AgentConfig(
            name="cloud",
            provider="openai",
            model="model",
            api_key="sk-secret-value-1234567890",
            headers={"Authorization": "Bearer secret-token-123456"},
        )

        masked = masked_agent_config(agent)

        self.assertNotIn("secret-value", masked["api_key"])
        self.assertNotIn("secret-token", masked["headers"]["Authorization"])

    def test_visibility_endpoints_expose_foundation_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                approval_mode="auto",
                agents={
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="echo",
                        free=True,
                    )
                },
                default_route=["echo"],
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                provider_health = _get_json(f"{base}/v1/provider-health")
                tools = _get_json(f"{base}/v1/tools")
                plugins = _get_json(f"{base}/v1/plugins")
                events = _get_json(f"{base}/v1/events")
                workflows = _get_json(f"{base}/v1/workflows/status")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(provider_health["object"], "agent_hub.provider_health")
            self.assertEqual(tools["object"], "agent_hub.tools")
            self.assertEqual(plugins["object"], "agent_hub.plugins")
            self.assertEqual(events["object"], "agent_hub.events")
            self.assertEqual(workflows["object"], "agent_hub.workflow_status")

    def test_public_bind_diagnostics_require_auth_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                host="0.0.0.0",
                state_dir=root / "state",
                workspace_dir=root,
                diagnostics_auth_token="diagnostic-secret",
                agents={
                    "echo": AgentConfig(name="echo", provider="echo", model="echo", free=True)
                },
                default_route=["echo"],
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with self.assertRaises(HTTPError) as error:
                    _get_json(f"{base}/v1/provider-health")
                body = json.loads(error.exception.read().decode("utf-8"))
                error.exception.close()
                authed = _get_json(
                    f"{base}/v1/provider-health",
                    headers={"X-Agent-Hub-Diagnostics-Token": "diagnostic-secret"},
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(error.exception.code, 401)
            self.assertEqual(body["error"]["type"], "diagnostics_auth_required")
            self.assertEqual(authed["object"], "agent_hub.provider_health")

    def test_localhost_diagnostics_remain_backward_compatible_without_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                host="127.0.0.1",
                state_dir=root / "state",
                workspace_dir=root,
                agents={
                    "echo": AgentConfig(name="echo", provider="echo", model="echo", free=True)
                },
                default_route=["echo"],
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                body = _get_json(f"http://127.0.0.1:{server.server_address[1]}/v1/plugins")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(body["object"], "agent_hub.plugins")

    def test_observability_endpoints_do_not_expose_provider_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                approval_mode="auto",
                free_only=False,
                agents={
                    "cloud": AgentConfig(
                        name="cloud",
                        provider="openai-compatible",
                        model="cloud-model",
                        base_url="https://example.invalid/v1",
                        api_key="super-secret-key",
                        headers={"Authorization": "Bearer hidden-token"},
                    )
                },
                default_route=["cloud"],
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            record_event(
                config.state_dir,
                "events",
                {
                    "type": "provider.failed",
                    "message": "provider leaked Authorization: Bearer hidden-token and sk-secretsecretsecret",
                    "api_key": "super-secret-key",
                },
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                health = json.dumps(_get_json(f"{base}/health"))
                status = json.dumps(_get_json(f"{base}/v1/status"))
                metrics = json.dumps(_get_json(f"{base}/metrics"))
                events = json.dumps(_get_json(f"{base}/v1/events"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            combined = "\n".join([health, status, metrics, events])
            self.assertNotIn("super-secret-key", combined)
            self.assertNotIn("hidden-token", combined)
            self.assertNotIn("sk-secretsecretsecret", combined)


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
