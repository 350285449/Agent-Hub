from __future__ import annotations

import json
import threading
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.core.router import AgentRouter
from agent_hub.server import (
    BACKEND_FEATURES,
    BACKEND_VERSION,
    _CLINE_PERMISSION_GUIDANCE_CACHE,
    AgentHubHTTPServer,
    _apply_model_routing,
    _cline_permission_guidance_repeated,
    _model_rows,
)


class ServerCompatibilityTests(unittest.TestCase):
    def test_backend_version_and_features_include_checkpoint_runtime(self) -> None:
        self.assertNotEqual(BACKEND_VERSION, "0.3.2")
        self.assertTrue(BACKEND_FEATURES["workspace_checkpoints"])
        self.assertTrue(BACKEND_FEATURES["validation_repair_loops"])
        self.assertTrue(BACKEND_FEATURES["strict_repository_context"])
        self.assertTrue(BACKEND_FEATURES["grouped_patch_enforcement"])
        self.assertTrue(BACKEND_FEATURES["repository_context_scoring"])
        self.assertTrue(BACKEND_FEATURES["agent_context_compaction"])
        self.assertTrue(BACKEND_FEATURES["context_usage_bar"])
        self.assertTrue(BACKEND_FEATURES["anthropic_messages_compatibility"])
        self.assertTrue(BACKEND_FEATURES["anthropic_tool_use_passthrough"])
        self.assertTrue(BACKEND_FEATURES["universal_provider_compatibility"])
        self.assertTrue(BACKEND_FEATURES["emulated_tool_call_bridge"])
        self.assertTrue(BACKEND_FEATURES["local_dummy_auth_compatibility"])
        self.assertTrue(BACKEND_FEATURES["readiness_scorecard"])
        self.assertTrue(BACKEND_FEATURES["feature_maturity_status"])
        self.assertTrue(BACKEND_FEATURES["runtime_kernel_control_plane"])
        self.assertTrue(BACKEND_FEATURES["runtime_kernel_dashboard"])

    def test_health_includes_context_enforcement_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="strict",
                context_change_bar_threshold=5,
                agent_context_budget_tokens=16000,
                agent_context_compaction_enabled=True,
                prefer_multi_file_patches=True,
                default_route=["echo"],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_address[1]}/health", timeout=5) as response:
                    data = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(data["context_change_bar"]["mode"], "strict")
            self.assertEqual(data["context_change_bar"]["threshold"], 5)
            self.assertTrue(data["agent_context_compaction"]["enabled"])
            self.assertEqual(data["agent_context_compaction"]["budget_tokens"], 16000)
            self.assertTrue(data["token_budget"]["cline_compatibility_mode"])
            self.assertIn("context_diagnostics", data)
            self.assertTrue(data["grouped_patch_enforcement"]["enabled"])
            self.assertEqual(data["repository_context_scoring"]["strict_minimum"], 6)
            self.assertTrue(data["features"]["repository_context_scoring"])

    def test_health_includes_actionable_setup_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=[],
                agents={},
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                data = _get_json(f"http://127.0.0.1:{server.server_address[1]}/health")
            finally:
                _stop(server, thread)

            guidance = data["setup_guidance"]
            self.assertEqual(guidance["object"], "agent_hub.setup_guidance")
            self.assertFalse(guidance["ready"])
            self.assertGreaterEqual(guidance["action_count"], 1)
            self.assertEqual(guidance["next_step"]["id"], "configure_agents")
            self.assertIn("python -m agent_hub init", guidance["next_step"]["command"])
            readiness = data["readiness"]
            self.assertEqual(readiness["object"], "agent_hub.readiness")
            self.assertEqual(readiness["state"], "needs_setup")
            self.assertEqual(readiness["next_step"]["id"], "providers_configured")
            experience = data["experience_summary"]
            self.assertEqual(experience["object"], "agent_hub.experience_summary")
            self.assertEqual(experience["state"], "needs_setup")
            self.assertEqual(experience["primary_action"]["id"], "configure_agents")
            self.assertEqual(experience["coding_tool"]["provider"], "openai-compatible")
            self.assertEqual(experience["coding_tool"]["model"], "agent-hub-coding")
            self.assertEqual(data["runtime_usability"]["object"], "agent_hub.runtime_usability")
            self.assertEqual(data["runtime_usability"]["state"], "needs_local_model")
            self.assertEqual(data["feature_status"]["provider_routing"]["state"], "needs_setup")

    def test_system_health_endpoint_hides_sensitive_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                data = _get_json(f"http://127.0.0.1:{server.server_address[1]}/v1/system-health")
            finally:
                _stop(server, thread)

            self.assertEqual(data["object"], "agent_hub.system_health")
            components = {row["component"]: row["status"] for row in data["components"]}
            self.assertIn("Workspace", components)
            self.assertNotIn(str(root), json.dumps(data))
            self.assertNotIn("api_key", json.dumps(data).lower())

    def test_cors_allows_localhost_origin_without_wildcard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                workspace_dir=Path(tmp),
                default_route=["echo"],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                port = server.server_address[1]
                request = Request(
                    f"http://127.0.0.1:{port}/health",
                    headers={"Origin": f"http://localhost:{port}"},
                )
                with urlopen(request, timeout=5) as response:
                    origin = response.headers.get("Access-Control-Allow-Origin")
            finally:
                _stop(server, thread)

            self.assertEqual(origin, f"http://localhost:{port}")

    def test_health_uses_short_lived_diagnostics_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["echo"],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            calls = 0

            def fake_health_body(router, *, context_diagnostics):
                nonlocal calls
                calls += 1
                return {
                    "status": "ok",
                    "running": True,
                    "calls": calls,
                    "context_diagnostics": context_diagnostics,
                }

            server.diagnostics_service.backend_health_body = fake_health_body
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                first, first_headers = _get_json_with_headers(f"{base}/health")
                second, second_headers = _get_json_with_headers(f"{base}/health")
            finally:
                _stop(server, thread)

            self.assertEqual(first["calls"], 1)
            self.assertEqual(second["calls"], 1)
            self.assertEqual(calls, 1)
            self.assertEqual(first_headers.get("X-Agent-Hub-Cache"), "miss")
            self.assertEqual(second_headers.get("X-Agent-Hub-Cache"), "hit")
            self.assertIn("backend_efficiency", second)
            self.assertGreaterEqual(second["backend_efficiency"]["diagnostics_cache"]["hits"], 1)
            self.assertEqual(
                second["backend_efficiency"]["runtime_kernel"]["object"],
                "agent_hub.runtime_kernel.efficiency",
            )
            self.assertGreaterEqual(second["backend_efficiency"]["runtime_kernel"]["total_requests"], 1)

    def test_diagnostics_cache_invalidates_after_post(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["echo"],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            calls = 0

            def fake_health_body(router, *, context_diagnostics):
                nonlocal calls
                calls += 1
                return {"status": "ok", "running": True, "calls": calls}

            server.diagnostics_service.backend_health_body = fake_health_body
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                first, first_headers = _get_json_with_headers(f"{base}/health")
                cached, cached_headers = _get_json_with_headers(f"{base}/health")
                _post_json(
                    f"{base}/debug/request",
                    {
                        "session_id": "debug",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
                refreshed, refreshed_headers = _get_json_with_headers(f"{base}/health")
            finally:
                _stop(server, thread)

            self.assertEqual(first["calls"], 1)
            self.assertEqual(cached["calls"], 1)
            self.assertEqual(refreshed["calls"], 2)
            self.assertEqual(first_headers.get("X-Agent-Hub-Cache"), "miss")
            self.assertEqual(cached_headers.get("X-Agent-Hub-Cache"), "hit")
            self.assertEqual(refreshed_headers.get("X-Agent-Hub-Cache"), "miss")

    def test_boost_mode_endpoint_updates_context_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["echo"],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                data = _post_json(f"{base}/v1/boost-mode", {"boost_mode": "save_tokens"})
            finally:
                _stop(server, thread)

            self.assertEqual(data["mode"], "save_tokens")
            self.assertEqual(data["context_mode"], "minimal")
            self.assertEqual(config.boost_mode, "save_tokens")
            self.assertEqual(config.context_mode, "minimal")

    def test_boost_mode_endpoint_rejects_unknown_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["echo"],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with self.assertRaises(HTTPError) as error:
                    _post_json(f"{base}/v1/boost-mode", {"boost_mode": "save_toknes"})
            finally:
                _stop(server, thread)

            self.assertEqual(error.exception.code, 400)
            self.assertEqual(config.boost_mode, "balanced")
            self.assertEqual(config.context_mode, "balanced")

    def test_runtime_kernel_endpoint_and_dashboard_report_live_server_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["echo"],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
                debug_echo_enabled=True,
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                _get_json(f"{base}/health")
                kernel = _get_json(f"{base}/v1/kernel")
                dashboard = _get_text(f"{base}/dashboard/kernel")
            finally:
                _stop(server, thread)

            self.assertEqual(kernel["object"], "agent_hub.runtime_kernel")
            self.assertGreaterEqual(kernel["request_telemetry"]["total_requests"], 1)
            self.assertGreaterEqual(kernel["uptime_seconds"], 0)
            self.assertEqual(kernel["pressure"]["object"], "agent_hub.runtime_kernel.pressure")
            self.assertEqual(kernel["service_map"]["object"], "agent_hub.runtime_kernel.service_map")
            self.assertTrue(kernel["timeline"])
            self.assertTrue(kernel["next_actions"])
            self.assertEqual(kernel["primary_next_action"], kernel["next_actions"][0])
            self.assertIn(
                kernel["state"],
                {"production_ready", "ready", "degraded", "needs_attention", "critical"},
            )
            subsystem_ids = {row["id"] for row in kernel["subsystems"]}
            self.assertTrue({"http_server", "router", "provider_pool", "diagnostics_cache"}.issubset(subsystem_ids))
            route_paths = {row["path"] for row in kernel["request_telemetry"]["routes"]}
            self.assertIn("/health", route_paths)
            self.assertIn("Agent Hub Runtime Kernel", dashboard)
            self.assertIn("Subsystems", dashboard)
            self.assertIn("Recommended Actions", dashboard)
            self.assertIn("Active Alerts", dashboard)
            self.assertIn("Process Health", dashboard)
            self.assertIn("Trends And Durability", dashboard)

    def test_runtime_kernel_tracks_error_status_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["echo"],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with self.assertRaises(HTTPError):
                    _get_json(f"{base}/missing-route")
                kernel = _get_json(f"{base}/v1/kernel")
            finally:
                _stop(server, thread)

            self.assertEqual(kernel["request_telemetry"]["status_codes"]["404"], 1)
            route_paths = {row["path"] for row in kernel["request_telemetry"]["routes"]}
            self.assertIn("/missing-route", route_paths)

    def test_model_rows_include_router_aliases_and_agent_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["tooly"],
                routes=[RouteRule(name="coding", agents=["tooly"])],
                agents={
                    "tooly": AgentConfig(
                        name="tooly",
                        provider="openai-compatible",
                        model="tool-model",
                        base_url="https://example.invalid/v1",
                        free=True,
                        enabled=True,
                        supports_tools=True,
                        coding_score=0.9,
                    )
                },
            )

            rows = _model_rows(config, AgentRouter(config))
            ids = {row["id"] for row in rows}

            self.assertIn("agent-hub-coding", ids)
            self.assertIn("coding", ids)
            self.assertIn("agent:tooly", ids)
            self.assertIn("tooly", ids)
            self.assertIn("tool-model", ids)

    def test_openai_model_name_can_select_agent_with_route_fallback(self) -> None:
        config = HubConfig(
            routes=[RouteRule(name="coding", agents=["fallback"])],
            agents={
                "chosen": AgentConfig(name="chosen", provider="echo", model="chosen-model"),
                "fallback": AgentConfig(name="fallback", provider="echo", model="fallback-model"),
            },
        )
        request = HubRequest(
            session_id="s",
            route="coding",
            messages=[{"role": "user", "content": "hello"}],
            raw={"model": "chosen-model"},
        )

        _apply_model_routing(config, request)

        self.assertEqual(request.preferred_agent, "chosen")
        self.assertEqual(request.route, "coding")

    def test_openai_chat_completions_accepts_cline_style_request_and_streams(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[HubRequest] = []
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)

            class CaptureProvider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(request)
                    return ProviderResult(
                        text="",
                        model=self.agent.model,
                        raw={
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "call_1",
                                    "name": "read_file",
                                    "input": {"path": "README.md"},
                                }
                            ]
                        },
                        finish_reason="tool_use",
                    )

            server.router.provider_factory = CaptureProvider
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                payload = {
                    "model": "agent-hub-coding",
                    "metadata": {"session_id": "cline-session"},
                    "messages": [{"role": "user", "content": "Read README"}],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "parameters": {"type": "object"},
                            },
                        }
                    ],
                }
                data = _post_json(
                    f"{base}/v1/chat/completions",
                    payload,
                    headers={"Authorization": "Bearer anything-local"},
                )
                stream, stream_headers = _post_text_with_headers(
                    f"{base}/v1/chat/completions",
                    {**payload, "stream": True},
                    headers={"Authorization": "Bearer anything-local"},
                )
            finally:
                _stop(server, thread)

            self.assertEqual(data["model"], "agent-hub-coding")
            self.assertNotIn("agent_hub", data)
            message = data["choices"][0]["message"]
            self.assertEqual(message["tool_calls"][0]["function"]["name"], "read_file")
            self.assertEqual(calls[0].route, "coding")
            self.assertEqual(calls[0].session_id, "cline-session")
            self.assertIn("chat.completion.chunk", stream)
            self.assertIn("data: [DONE]", stream)
            self.assertEqual(stream_headers.get("X-Agent-Hub-Stream-Mode"), "compatibility")

    def test_anthropic_messages_accepts_claude_code_style_request_and_streams(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[HubRequest] = []
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)

            class CaptureProvider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(request)
                    return ProviderResult(
                        text="",
                        model=self.agent.model,
                        raw={
                            "choices": [
                                {
                                    "message": {
                                        "role": "assistant",
                                        "content": None,
                                        "tool_calls": [
                                            {
                                                "id": "call_1",
                                                "type": "function",
                                                "function": {
                                                    "name": "read_file",
                                                    "arguments": "{\"path\":\"README.md\"}",
                                                },
                                            }
                                        ],
                                    },
                                    "finish_reason": "tool_calls",
                                }
                            ]
                        },
                        finish_reason="tool_calls",
                    )

            server.router.provider_factory = CaptureProvider
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                payload = {
                    "model": "agent-hub-coding",
                    "system": "Be concise",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": "Read README"}],
                    "tools": [
                        {
                            "name": "read_file",
                            "input_schema": {"type": "object"},
                        }
                    ],
                }
                headers = {
                    "x-api-key": "local-agent-hub-token",
                    "anthropic-version": "2023-06-01",
                    "x-session-id": "claude-session",
                }
                data = _post_json(f"{base}/v1/messages", payload, headers=headers)
                stream = _post_text(f"{base}/v1/messages", {**payload, "stream": True}, headers=headers)
            finally:
                _stop(server, thread)

            self.assertEqual(data["model"], "agent-hub-coding")
            self.assertEqual(data["content"][0]["type"], "tool_use")
            self.assertEqual(data["content"][0]["name"], "read_file")
            self.assertEqual(calls[0].route, "coding")
            self.assertEqual(calls[0].session_id, "claude-session")
            self.assertEqual(calls[0].messages[0]["role"], "system")
            self.assertIn("event: message_start", stream)
            self.assertIn("event: message_stop", stream)

    def test_models_endpoint_includes_agent_hub_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                with urlopen(
                    f"http://127.0.0.1:{server.server_address[1]}/v1/models",
                    timeout=5,
                ) as response:
                    data = json.loads(response.read().decode("utf-8"))
            finally:
                _stop(server, thread)

            ids = {item["id"] for item in data["data"]}
            self.assertIn("agent-hub", ids)
            self.assertIn("agent-hub-coding", ids)
            self.assertIn("agent-hub-cloud", ids)
            self.assertIn("agent-hub-local", ids)
            self.assertIn("agent:tooly", ids)
            for item in data["data"]:
                self.assertEqual(item["object"], "model")
                self.assertEqual(item["created"], 0)
                self.assertIn("owned_by", item)
                self.assertNotIn("agent_hub", item)

    def test_models_endpoint_does_not_expose_echo_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                compatibility_mode={"emulate_tools": False},
                default_route=["echo"],
                routes=[RouteRule(name="coding", agents=["echo"])],
                agents={
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="local-echo",
                    )
                },
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                data = _get_json(f"http://127.0.0.1:{server.server_address[1]}/v1/models")
            finally:
                _stop(server, thread)

            ids = {item["id"] for item in data["data"]}
            self.assertNotIn("echo", ids)
            self.assertNotIn("local-echo", ids)
            self.assertNotIn("agent:echo", ids)

    def test_cline_tool_request_with_only_echo_returns_tool_model_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                default_route=["echo"],
                routes=[RouteRule(name="coding", agents=["echo"])],
                agents={
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="local-echo",
                    )
                },
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with self.assertRaises(HTTPError) as error:
                    _post_json(
                        f"{base}/v1/chat/completions",
                        {
                            "model": "agent-hub-coding",
                            "messages": [{"role": "user", "content": "<task>Read README</task>"}],
                            "tools": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "parameters": {"type": "object"},
                                    },
                                }
                            ],
                        },
                    )
                body = json.loads(error.exception.read().decode("utf-8"))
                error.exception.close()
            finally:
                _stop(server, thread)

            self.assertEqual(error.exception.code, 400)
            self.assertEqual(body["error"]["type"], "no_tool_capable_model")
            self.assertIn("No tool-capable model", body["error"]["message"])
            self.assertIn("suggested_fix", body["error"])

    def test_non_tool_echo_requires_debug_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                default_route=["echo"],
                agents={
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="local-echo",
                    )
                },
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with self.assertRaises(HTTPError) as error:
                    _post_json(
                        f"{base}/v1/chat/completions",
                        {
                            "model": "agent:echo",
                            "messages": [{"role": "user", "content": "hello"}],
                        },
                    )
                body = json.loads(error.exception.read().decode("utf-8"))
                error.exception.close()
            finally:
                _stop(server, thread)

            self.assertEqual(error.exception.code, 400)
            self.assertEqual(body["error"]["type"], "configuration_error")
            self.assertIn("Echo is disabled", body["error"]["message"])

    def test_debug_echo_non_tool_request_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                debug_echo_enabled=True,
                default_route=["echo"],
                agents={
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="local-echo",
                    )
                },
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                data = _post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent:echo",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
            finally:
                _stop(server, thread)

            self.assertEqual(data["choices"][0]["message"]["content"], "[echo] hello")

    def test_health_limits_and_models_expose_quota_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            server.router.provider_factory = _QuotaProvider
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                _post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
                health = _get_json(f"{base}/health")
                limits = _get_json(f"{base}/limits")
                models = _get_json(f"{base}/models")
            finally:
                _stop(server, thread)

            self.assertTrue(health["running"])
            self.assertEqual(health["server_status"], "running")
            self.assertIn("limits", health)
            self.assertIn("providers", health)
            self.assertTrue(any(row["agent"] == "tooly" for row in health["providers"]))
            self.assertEqual(health["provider_health"]["tooly"]["requests_remaining"], 7)
            self.assertEqual(health["provider_health"]["tooly"]["tokens_remaining"], 12345)

            tooly_limits = next(row for row in limits["limits"] if row["agent"] == "tooly")
            self.assertEqual(tooly_limits["provider"], "openai-compatible")
            self.assertEqual(tooly_limits["model"], "tool-model")
            self.assertEqual(tooly_limits["credits_remaining"], 2.5)
            self.assertIn("agent-hub-coding", limits["available_models"])
            self.assertEqual(models["object"], "list")

    def test_unknown_quota_is_reported_as_unknown_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                limits = _get_json(f"{base}/v1/limits")
                provider_health = _get_json(f"{base}/v1/provider-health")
            finally:
                _stop(server, thread)

            tooly_limits = next(row for row in limits["limits"] if row["agent"] == "tooly")
            self.assertEqual(tooly_limits["remaining"], "unknown")
            self.assertEqual(tooly_limits["quota_state"], "unknown")
            self.assertIsNone(tooly_limits["tokens_remaining"])
            self.assertEqual(provider_health["health"]["tooly"]["remaining"], "unknown")

    def test_openai_compatible_response_includes_limit_headers_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            server.router.provider_factory = _QuotaProvider
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                data, headers = _post_json_with_headers(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
            finally:
                _stop(server, thread)

            self.assertEqual(data["choices"][0]["message"]["content"], "ok")
            self.assertNotIn("agent_hub", data)
            self.assertEqual(headers.get("X-Agent-Hub-Provider"), "openai-compatible")
            self.assertEqual(headers.get("X-Agent-Hub-Model"), "tool-model")
            self.assertEqual(headers.get("X-Agent-Hub-Requests-Remaining"), "7")
            self.assertEqual(headers.get("X-Agent-Hub-Tokens-Remaining"), "12345")
            self.assertEqual(headers.get("X-Agent-Hub-Credits-Remaining"), "2.5")
            self.assertEqual(headers.get("X-AgentHub-Provider"), "openai-compatible")
            self.assertEqual(headers.get("X-AgentHub-Model"), "tool-model")
            self.assertEqual(headers.get("X-AgentHub-Requests-Remaining"), "7")
            self.assertEqual(headers.get("X-AgentHub-Permission-Status"), "allowed")

    def test_usage_permissions_and_metrics_endpoints_are_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            server.router.provider_factory = _QuotaProvider
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                _post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
                usage = _get_json(f"{base}/usage")
                permissions = _get_json(f"{base}/permissions")
                metrics = _get_json(f"{base}/metrics")
            finally:
                _stop(server, thread)

            self.assertEqual(usage["object"], "agent_hub.usage")
            self.assertGreaterEqual(usage["input_tokens"], 3)
            self.assertEqual(permissions["object"], "agent_hub.permissions")
            self.assertEqual(metrics["object"], "agent_hub.metrics")
            self.assertIn("routing_decisions", metrics)

    def test_v1_routing_diagnostics_endpoints_are_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            server.router.provider_factory = _QuotaProvider
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                _post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
                status = _get_json(f"{base}/v1/routing/status")
                last = _get_json(f"{base}/v1/routing/last-decision")
                failover = _get_json(f"{base}/v1/routing/test-failover")
                sources = _get_json(f"{base}/v1/client-sources")
                usage = _get_json(f"{base}/v1/usage")
            finally:
                _stop(server, thread)

            self.assertEqual(status["object"], "agent_hub.routing.status")
            self.assertEqual(last["object"], "agent_hub.routing.last_decision")
            self.assertTrue(failover["dry_run"])
            self.assertEqual(sources["object"], "agent_hub.client_sources")
            self.assertEqual(usage["object"], "agent_hub.usage")

    def test_auto_feedback_and_optimization_endpoints_are_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            config.expose_routing_details = True
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            server.router.provider_factory = _QuotaProvider
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                auto = _post_json(
                    f"{base}/v1/auto",
                    {
                        "session_id": "auto",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
                feedback = _post_json(
                    f"{base}/v1/feedback",
                    {"request_id": auto["id"], "rating": "up", "workflow_success": True},
                )
                openai_auto = _post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-auto",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
                optimization = _get_json(f"{base}/v1/optimization")
                metrics = _get_json(f"{base}/metrics")
                simulation = _post_json(
                    f"{base}/v1/routing/simulate",
                    {
                        "session_id": "simulate",
                        "messages": [{"role": "user", "content": "large architecture migration"}],
                    },
                )
                dashboard = _get_text(f"{base}/dashboard/optimization")
            finally:
                _stop(server, thread)

            self.assertEqual(auto["object"], "agent_hub.response")
            self.assertEqual(auto["agent_hub"]["workflow_selection"]["pattern"], "direct_route")
            self.assertTrue(feedback["matched"])
            self.assertEqual(openai_auto["object"], "chat.completion")
            self.assertEqual(optimization["object"], "agent_hub.optimization")
            self.assertIn("dashboard", optimization)
            self.assertIn("optimization", metrics)
            self.assertEqual(simulation["object"], "agent_hub.routing_simulation")
            self.assertTrue(simulation["dry_run"])
            self.assertEqual(simulation["workflow_selection"]["pattern"], "team_reviewed")
            self.assertIn("Optimization Dashboard", dashboard)
            self.assertIn("Workflow Analytics", dashboard)
            self.assertIn("Model Win Rates", dashboard)

    def test_routing_intelligence_endpoint_and_dashboard_are_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            server.router.provider_factory = _QuotaProvider
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                _post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "messages": [{"role": "user", "content": "Fix src/app.py"}],
                    },
                )
                intelligence = _get_json(f"{base}/v1/routing-intelligence")
                dashboard = _get_text(f"{base}/dashboard/routing-intelligence")
                last = _get_json(f"{base}/v1/routing/last-decision")
            finally:
                _stop(server, thread)

            self.assertEqual(intelligence["object"], "agent_hub.routing_intelligence")
            self.assertEqual(intelligence["feature"], "Adaptive Workspace Intelligence")
            self.assertIn("latest_explanation", intelligence)
            self.assertTrue(intelligence["latest_explanation"]["reasons"])
            self.assertEqual(
                intelligence["latest_explanation"]["object"],
                "agent_hub.routing_decision_explanation",
            )
            self.assertIn("Routing Intelligence", dashboard)
            self.assertIn("Provider Rankings", dashboard)
            self.assertIn("explanation", last["decision"]["routing_decision"])

    def test_data_light_dashboards_have_empty_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                costs = _get_text(f"{base}/dashboard/costs")
                leaderboard = _get_text(f"{base}/dashboard/model-leaderboard")
                benchmarks = _get_text(f"{base}/dashboard/benchmarks")
                provider_scores = _get_text(f"{base}/dashboard/provider-scores")
                routing_history = _get_text(f"{base}/dashboard/routing-history")
                status_dashboard = _get_text(f"{base}/dashboard/status")
                provider_health = _get_text(f"{base}/dashboard/provider-health")
                production_check = _get_text(f"{base}/dashboard/production-check")
                limits = _get_text(f"{base}/dashboard/limits")
                usage = _get_text(f"{base}/dashboard/usage")
                events = _get_text(f"{base}/dashboard/events")
                tools = _get_text(f"{base}/dashboard/tools")
                workflows = _get_text(f"{base}/dashboard/workflows")
                plugins = _get_text(f"{base}/dashboard/plugins")
                mcp = _get_text(f"{base}/dashboard/mcp")
                extension_contract = _get_text(f"{base}/dashboard/extension-contract")
                enterprise = _get_text(f"{base}/dashboard/enterprise")
                repository_dna = _get_text(f"{base}/dashboard/repository-dna")
                workspace_memory = _get_text(f"{base}/dashboard/workspace-memory")
                night_mode = _get_text(f"{base}/dashboard/night-mode")
                inbox = _get_text(f"{base}/dashboard/inbox")
                costs_json = _get_json(f"{base}/v1/cost-dashboard")
                leaderboard_json = _get_json(f"{base}/v1/model-leaderboard")
                benchmarks_json = _get_json(f"{base}/v1/benchmarks")
                inbox_json = _get_json(f"{base}/v1/inbox/status")
                mcp_json = _get_json(f"{base}/v1/mcp/status")
                extension_json = _get_json(f"{base}/v1/extension-contract")
            finally:
                _stop(server, thread)

            self.assertIn("Pricing coverage ready; measured spend pending", costs)
            self.assertIn("Pricing Coverage", costs)
            self.assertIn("Raw payload", costs)
            self.assertIn("Baseline agents", leaderboard)
            self.assertIn("Ranked Models", leaderboard)
            self.assertIn("Configuration baseline ready; live measurements pending", benchmarks)
            self.assertIn("Benchmark Coverage Snapshot", benchmarks)
            self.assertIn("Recent Reports", benchmarks)
            self.assertIn("Agent Hub Provider Scores", provider_scores)
            self.assertIn("Provider Scores", provider_scores)
            self.assertIn("Agent Hub Routing History", routing_history)
            self.assertIn("Recent Routing Events", routing_history)
            self.assertIn("Agent Hub Status", status_dashboard)
            self.assertIn("Provider Health", status_dashboard)
            self.assertIn("Agent Hub Provider Health", provider_health)
            self.assertIn("Recent Failures", provider_health)
            self.assertIn("Agent Hub Production Check", production_check)
            self.assertIn("Acceptance Checks", production_check)
            self.assertIn("Agent Hub Limits", limits)
            self.assertIn("Limits And Cooldowns", limits)
            self.assertIn("Agent Hub Usage", usage)
            self.assertIn("Recent Tool Executions", usage)
            self.assertIn("Agent Hub Events", events)
            self.assertIn("Routing Events", events)
            self.assertIn("Agent Hub Tools", tools)
            self.assertIn("Registered Tools", tools)
            self.assertIn("Agent Hub Workflows", workflows)
            self.assertIn("Recent Runs", workflows)
            self.assertIn("Agent Hub Plugins", plugins)
            self.assertIn("Discovered Plugins", plugins)
            self.assertIn("Agent Hub MCP", mcp)
            self.assertIn("MCP Servers", mcp)
            self.assertIn("Agent Hub Extension Contract", extension_contract)
            self.assertIn("Required Backend Features", extension_contract)
            self.assertIn("Agent Hub Enterprise", enterprise)
            self.assertIn("Enterprise users", enterprise)
            self.assertIn("Agent Hub Repository DNA", repository_dna)
            self.assertIn("Repository Profile", repository_dna)
            self.assertIn("Agent Hub Workspace Memory", workspace_memory)
            self.assertIn("Remembered Facts", workspace_memory)
            self.assertIn("Agent Hub Night Mode", night_mode)
            self.assertIn("Planned Tasks", night_mode)
            self.assertIn("Agent Hub Inbox", inbox)
            self.assertIn("Pending Tasks", inbox)
            self.assertEqual(costs_json["summary"]["data_state"], "pricing_ready_waiting_for_usage")
            self.assertEqual(leaderboard_json["summary"]["data_state"], "baseline_ready")
            self.assertEqual(leaderboard_json["summary"]["baseline_agent_count"], 1)
            self.assertEqual(benchmarks_json["summary"]["data_state"], "baseline_ready")
            self.assertEqual(inbox_json["object"], "agent_hub.inbox_status")
            self.assertEqual(mcp_json["object"], "agent_hub.mcp_status")
            self.assertEqual(extension_json["object"], "agent_hub.extension_contract")

    def test_inbox_submit_endpoint_queues_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                submitted = _post_json(
                    f"{base}/v1/inbox/submit",
                    {"task_id": "server-task", "task": "queued from api"},
                )
                status = _get_json(f"{base}/v1/inbox/status")
            finally:
                _stop(server, thread)

            self.assertTrue(submitted["accepted"])
            self.assertEqual(submitted["task"]["name"], "server-task.json")
            self.assertEqual(status["counts"]["pending"], 1)
            self.assertTrue(status["pending"][0]["valid"])

    def test_readiness_endpoint_exposes_scorecard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                readiness = _get_json(f"{base}/v1/readiness")
                status = _get_json(f"{base}/v1/status")
                production = _get_json(f"{base}/v1/production-check")
                feature_scorecard = _get_json(f"{base}/v1/feature-scorecard")
                dashboard = _get_text(f"{base}/dashboard")
                readiness_dashboard = _get_text(f"{base}/dashboard/readiness")
                feature_dashboard = _get_text(f"{base}/dashboard/feature-scorecard")
            finally:
                _stop(server, thread)

            self.assertEqual(readiness["object"], "agent_hub.readiness")
            self.assertIn("score", readiness)
            self.assertIn("runtime_usability", readiness)
            self.assertTrue(any(item["id"] == "route_ready_provider" for item in readiness["items"]))
            self.assertEqual(readiness["feature_status"]["external_mcp_bridge"]["state"], "execution_disabled")
            self.assertEqual(readiness["feature_status"]["universal_compatibility"]["state"], "ready")
            self.assertTrue(
                readiness["feature_status"]["universal_compatibility"]["tool_emulation_enabled"]
            )
            self.assertEqual(production["object"], "agent_hub.production_check")
            self.assertIn("checks", production)
            self.assertIn("runtime_usability", production)
            self.assertTrue(any(check["id"] == "vscode_backend_contract" for check in production["checks"]))
            self.assertEqual(status["runtime_usability"]["object"], "agent_hub.runtime_usability")
            self.assertEqual(feature_scorecard["object"], "agent_hub.feature_scorecard")
            self.assertEqual(feature_scorecard["rating"], 10.0)
            self.assertTrue(feature_scorecard["all_local_areas_10"], feature_scorecard["blockers"])
            self.assertIn("runtime_usability", feature_scorecard)
            self.assertIn("readiness", dashboard.lower())
            self.assertIn("/dashboard/readiness", dashboard)
            self.assertIn("/dashboard/feature-scorecard", dashboard)
            self.assertIn("/dashboard/status", dashboard)
            self.assertIn("/dashboard/provider-health", dashboard)
            self.assertIn("/dashboard/production-check", dashboard)
            self.assertIn("Raw APIs:", dashboard)
            self.assertIn("Agent Hub Readiness", readiness_dashboard)
            self.assertIn("Runtime Usability", readiness_dashboard)
            self.assertIn("Readiness Scorecard", readiness_dashboard)
            self.assertIn("Agent Hub Feature Scorecard", feature_dashboard)
            self.assertIn("Runtime usability is scored separately", feature_dashboard)
            self.assertIn("Area Ratings", feature_dashboard)

    def test_health_exposes_capability_graph_and_token_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            config.context_mode = "minimal"
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                health = _get_json(f"http://127.0.0.1:{server.server_address[1]}/health")
            finally:
                _stop(server, thread)

            self.assertTrue(health["features"]["central_token_budget_manager"])
            self.assertTrue(health["features"]["tool_security_classifier"])
            self.assertEqual(health["token_budget"]["mode"], "minimal")
            self.assertEqual(health["capability_graph"]["object"], "agent_hub.capability_graph")

    def test_detailed_routing_includes_limit_metadata_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            config.expose_routing_details = True
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            server.router.provider_factory = _QuotaProvider
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                data = _post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
            finally:
                _stop(server, thread)

            hub = data["agent_hub"]
            self.assertEqual(hub["agent"], "tooly")
            self.assertEqual(hub["active_model"]["model"], "tool-model")
            self.assertEqual(hub["limits"]["requests_remaining"], 7)
            self.assertEqual(hub["limits"]["tokens_remaining"], 12345)
            self.assertIn("failed_models", hub)
            self.assertIn("fallback_models", hub)
            self.assertEqual(hub["routing_summary"]["selected_agent"], "tooly")
            self.assertIn("why_provider_chosen", hub["routing_summary"])
            self.assertIn("estimated_cost_usd", hub["routing_summary"])
            self.assertGreaterEqual(hub["routing_summary"]["latency_ms"], 0)

    def test_openai_compatible_proxy_blocks_unknown_external_provider_without_permission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                workspace_dir=Path(tmp),
                approval_mode="auto",
                free_only=False,
                default_route=["unknown"],
                agents={
                    "unknown": AgentConfig(
                        name="unknown",
                        provider="openai-compatible",
                        provider_type="custom-external",
                        base_url="https://unknown.example.invalid/v1",
                        model="unknown-model",
                        api_key="secret",
                    )
                },
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with self.assertRaises(HTTPError) as error:
                    _post_json(
                        f"{base}/v1/chat/completions",
                        {
                            "model": "unknown-model",
                            "messages": [{"role": "user", "content": "Current file: app.py\nhello"}],
                        },
                    )
                body = json.loads(error.exception.read().decode("utf-8"))
                error.exception.close()
            finally:
                _stop(server, thread)

            self.assertEqual(error.exception.code, 403)
            self.assertEqual(body["error"]["type"], "agent_hub_permission_required")
            self.assertTrue(body["agent_hub"]["permission_required"])
            self.assertEqual(body["error"]["provider"], "unknown")
            self.assertEqual(body["agent_hub"]["trust_level"], "UNTRUSTED_EXTERNAL")
            self.assertTrue(body["error"]["suggested_fix"]["provider_approval_granted"])

    def test_openai_compatible_proxy_returns_actionable_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                workspace_dir=Path(tmp),
                approval_mode="ask",
                cline_compatibility_mode=False,
                free_only=False,
                default_route=["paid"],
                agents={
                    "paid": AgentConfig(
                        name="paid",
                        provider="openai",
                        model="paid-model",
                        api_key="secret",
                    )
                },
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with self.assertRaises(HTTPError) as error:
                    _post_json(
                        f"{base}/v1/chat/completions",
                        {
                            "model": "paid-model",
                            "messages": [{"role": "user", "content": "Current file: app.py\nhello"}],
                        },
                    )
                body = json.loads(error.exception.read().decode("utf-8"))
                error.exception.close()
            finally:
                _stop(server, thread)

            self.assertEqual(error.exception.code, 403)
            self.assertEqual(body["error"]["type"], "agent_hub_permission_required")
            self.assertEqual(
                body["error"]["message"],
                "Provider requires approval from the VS Code UI or a trusted session. "
                "Trusted cloud providers may also be enabled explicitly with approval_mode=auto.",
            )
            self.assertEqual(
                body["error"]["suggested_fix"],
                {
                    "approval_mode": "auto",
                    "trusted_approval_header": "X-Agent-Hub-Approval-Token",
                },
            )

    def test_cline_permission_error_returns_repair_prompt_chat_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                workspace_dir=Path(tmp),
                approval_mode="ask",
                cline_compatibility_mode=True,
                free_only=False,
                default_route=["paid"],
                agents={
                    "paid": AgentConfig(
                        name="paid",
                        provider="openai",
                        model="paid-model",
                        api_key="secret",
                    )
                },
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                body = _post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "messages": [{"role": "user", "content": "Current file: app.py\nhello"}],
                    },
                    headers={"User-Agent": "Cline/3.0"},
                )
            finally:
                _stop(server, thread)

            self.assertEqual(body["object"], "chat.completion")
            self.assertEqual(body["model"], "agent-hub-coding")
            content = body["choices"][0]["message"]["content"]
            self.assertIn("Agent Hub blocked this Cline request", content)
            self.assertIn('\"approval_mode\": \"auto\"', content)
            self.assertIn("--config", content)
            self.assertIn("Agent Hub: Restart Server", content)
            self.assertIn("Prompt Cline to make the config edit", content)

    def test_cline_secret_permission_error_includes_redacted_finding_summary(self) -> None:
        _CLINE_PERMISSION_GUIDANCE_CACHE.clear()
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                workspace_dir=Path(tmp),
                approval_mode="auto",
                cline_compatibility_mode=True,
                free_only=False,
                default_route=["paid"],
                agents={
                    "paid": AgentConfig(
                        name="paid",
                        provider="openai",
                        model="paid-model",
                        api_key="secret",
                        safe_for_secrets=True,
                    )
                },
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                body = _post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Current file: app.py\nAPI_KEY=super-secret-token-123",
                            }
                        ],
                    },
                    headers={"User-Agent": "Cline/3.0"},
                )
            finally:
                _stop(server, thread)

            content = body["choices"][0]["message"]["content"]
            self.assertIn("This request needs explicit approval because secret-like content was detected.", content)
            self.assertIn("Detected (redacted):", content)
            self.assertIn("secret_assignment", content)
            self.assertIn("line 2", content)
            self.assertIn("[REDACTED]", content)
            self.assertNotIn("super-secret-token-123", content)

    def test_cline_permission_guidance_dedupe_ignores_evolving_prompt_text(self) -> None:
        _CLINE_PERMISSION_GUIDANCE_CACHE.clear()
        error = {
            "message": "Provider request requires explicit approval because the request content triggered a security rule."
        }
        summary = {"findings": [{"kind": "long_secret", "source": "message:0", "line": 1}]}
        first = HubRequest(
            session_id="generated-session-a",
            messages=[{"role": "user", "content": "hi"}],
            raw={"model": "agent-hub-coding"},
            metadata={"source": "cline"},
        )
        retry = HubRequest(
            session_id="generated-session-b",
            messages=[
                {
                    "role": "user",
                    "content": "hi\nAgent Hub blocked this Cline request before sending workspace context.",
                }
            ],
            raw={"model": "agent-hub-coding"},
            metadata={"source": "cline"},
        )

        self.assertFalse(
            _cline_permission_guidance_repeated(
                request=first,
                provider="paid",
                model="paid-model",
                error=error,
                security_summary=summary,
            )
        )
        self.assertTrue(
            _cline_permission_guidance_repeated(
                request=retry,
                provider="paid",
                model="paid-model",
                error=error,
                security_summary=summary,
            )
        )

    def test_debug_request_preserves_cline_structured_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                debug = _post_json(
                    f"{base}/debug/request",
                    {
                        "api_shape": "openai-chat",
                        "model": "agent-hub-coding",
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "hello"},
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": "x",
                                        "content": [{"type": "text", "text": "tool output"}],
                                    },
                                ],
                                "task_progress": [{"title": "todo", "status": "in_progress"}],
                                "active_files": ["tests/test_cli.py"],
                            }
                        ],
                        "agent_hub": {"cline_compatibility_mode": True},
                    },
                )
                context = _get_json(f"{base}/debug/context")
            finally:
                _stop(server, thread)

            diagnostics = debug["diagnostics"]
            self.assertTrue(diagnostics["cline_compatibility_mode"])
            self.assertEqual(diagnostics["structured_content_messages"], 1)
            self.assertEqual(diagnostics["preserved_tool_results"], 1)
            self.assertEqual(diagnostics["preserved_todo_count"], 1)
            self.assertEqual(diagnostics["active_files_detected"], ["tests/test_cli.py"])
            self.assertEqual(context["summary"]["preserved_tool_results"], 1)

    def test_cline_openai_requests_attach_internal_health_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            server.router.provider_factory = _QuotaProvider
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                _post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                    headers={"User-Agent": "Cline/3.0"},
                )
                health = _get_json(f"{base}/v1/provider-health")
            finally:
                _stop(server, thread)

            row = health["health"]["tooly"]
            self.assertEqual(row["last_request_source"], "cline")
            self.assertEqual(row["last_route"], "coding")
            self.assertTrue(row["last_input_tokens"] >= 1)

    def test_openai_responses_debug_request_keeps_content_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _compat_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                debug = _post_json(
                    f"{base}/debug/request",
                    {
                        "api_shape": "openai-responses",
                        "model": "agent-hub-coding",
                        "input": [
                            {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {"type": "input_text", "text": "hello"},
                                    {"type": "tool_result", "tool_use_id": "x", "content": "ok"},
                                ],
                            }
                        ],
                        "task_progress": [{"title": "keep me"}],
                    },
                )
            finally:
                _stop(server, thread)

            diagnostics = debug["diagnostics"]
            self.assertEqual(diagnostics["structured_content_messages"], 1)
            self.assertEqual(diagnostics["preserved_tool_results"], 1)
            self.assertTrue(debug["metadata"]["cline_compatibility_mode"])


def _compat_config(path: Path) -> HubConfig:
    return HubConfig(
        workspace_dir=path,
        state_dir=path / "state",
        inbox_dir=path / "inbox",
        outbox_dir=path / "outbox",
        archive_dir=path / "archive",
        default_route=["tooly"],
        routes=[
            RouteRule(name="coding", agents=["tooly"]),
            RouteRule(name="cloud-agent", agents=["tooly"]),
            RouteRule(name="local-agent", agents=["tooly"]),
        ],
        agents={
            "tooly": AgentConfig(
                name="tooly",
                provider="openai-compatible",
                model="tool-model",
                base_url="http://127.0.0.1:9999",
                free=True,
                supports_tools=True,
                supports_function_calling=True,
            )
        },
    )


class _QuotaProvider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        return ProviderResult(
            text="ok",
            model=self.agent.model,
            raw={
                "agent_hub_provider": {
                    "quota": {
                        "requests_remaining": 7,
                        "tokens_remaining": 12345,
                        "credits_remaining": 2.5,
                        "rate_limit_reset_at": 2_000_000_000,
                    }
                }
            },
            usage={"prompt_tokens": 3, "completion_tokens": 1},
            finish_reason="stop",
        )


def _start(server: AgentHubHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _stop(server: AgentHubHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None) -> dict:
    return json.loads(_post_text(url, payload, headers=headers))


def _post_json_with_headers(
    url: str,
    payload: dict,
    headers: dict[str, str] | None = None,
) -> tuple[dict, object]:
    text, response_headers = _post_text_with_headers(url, payload, headers=headers)
    return json.loads(text), response_headers


def _post_text(url: str, payload: dict, headers: dict[str, str] | None = None) -> str:
    text, _headers = _post_text_with_headers(url, payload, headers=headers)
    return text


def _get_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json_with_headers(url: str) -> tuple[dict, object]:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8")), response.headers


def _get_text(url: str) -> str:
    with urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def _post_text_with_headers(
    url: str,
    payload: dict,
    headers: dict[str, str] | None = None,
) -> tuple[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    with urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8"), response.headers


if __name__ == "__main__":
    unittest.main()
