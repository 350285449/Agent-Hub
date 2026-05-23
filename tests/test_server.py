from __future__ import annotations

import json
import threading
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.router import AgentRouter
from agent_hub.server import (
    BACKEND_FEATURES,
    BACKEND_VERSION,
    AgentHubHTTPServer,
    _apply_model_routing,
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
        self.assertTrue(BACKEND_FEATURES["local_dummy_auth_compatibility"])

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
            self.assertTrue(data["grouped_patch_enforcement"]["enabled"])
            self.assertEqual(data["repository_context_scoring"]["strict_minimum"], 6)
            self.assertTrue(data["features"]["repository_context_scoring"])

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
                stream = _post_text(
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


def _compat_config(path: Path) -> HubConfig:
    return HubConfig(
        state_dir=path / "state",
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


def _post_text(url: str, payload: dict, headers: dict[str, str] | None = None) -> str:
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
    with urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8")


if __name__ == "__main__":
    unittest.main()
