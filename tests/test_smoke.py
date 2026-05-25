from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agent_hub.agent_tools import AgentToolbox
from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.server import AgentHubHTTPServer


class ProductionSmokeTests(unittest.TestCase):
    def test_backend_startup_health_models_and_compat_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[HubRequest] = []
            config = _smoke_config(Path(tmp))
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(request)
                    return ProviderResult(text="ok", model=self.agent.model, usage={"prompt_tokens": 4, "completion_tokens": 1})

            server.router.provider_factory = Provider
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                health = _get_json(f"{base}/health")
                models = _get_json(f"{base}/v1/models")
                openai = _post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
                anthropic = _post_json(
                    f"{base}/v1/messages",
                    {
                        "model": "agent-hub-coding",
                        "max_tokens": 16,
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
                cline = _post_json(
                    f"{base}/debug/request",
                    {
                        "api_shape": "openai-chat",
                        "model": "agent-hub-coding",
                        "messages": [
                            {
                                "role": "user",
                                "content": [{"type": "text", "text": "keep context"}],
                                "task_progress": [{"title": "task"}],
                                "active_files": ["tests/test_smoke.py"],
                            }
                        ],
                    },
                )
                debug_context = _get_json(f"{base}/debug/context")
            finally:
                _stop(server, thread)

            self.assertTrue(health["running"])
            self.assertTrue(health["features"]["context_debug_endpoints"])
            self.assertIn("agent-hub-coding", {row["id"] for row in models["data"]})
            self.assertEqual(openai["choices"][0]["message"]["content"], "ok")
            self.assertEqual(anthropic["content"][0]["text"], "ok")
            self.assertEqual(calls[0].route, "coding")
            self.assertEqual(cline["diagnostics"]["preserved_todo_count"], 1)
            self.assertEqual(debug_context["summary"]["active_files_detected"], ["tests/test_smoke.py"])

    def test_echo_hidden_by_default_and_debug_echo_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                default_route=["echo"],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo-model")},
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                models = _get_json(f"{base}/v1/models")
                with self.assertRaises(HTTPError) as error:
                    _post_json(f"{base}/v1/chat/completions", {"model": "agent:echo", "messages": [{"role": "user", "content": "hi"}]})
                error.exception.close()
            finally:
                _stop(server, thread)

            self.assertNotIn("echo-model", {row["id"] for row in models["data"]})

            config.debug_echo_enabled = True
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                data = _post_json(f"{base}/v1/chat/completions", {"model": "agent:echo", "messages": [{"role": "user", "content": "hi"}]})
            finally:
                _stop(server, thread)

            self.assertEqual(data["choices"][0]["message"]["content"], "[echo] hi")

    def test_permission_required_shell_command_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            toolbox = AgentToolbox(
                HubConfig(workspace_dir=Path(tmp), state_dir=Path(tmp) / "state", approval_mode="safe"),
                HubRequest(session_id="s", messages=[]),
            )

            result = toolbox.run("run_command", {"command": "npm install left-pad"})

            self.assertFalse(result["ok"])
            self.assertTrue(result["approval_required"])


def _smoke_config(path: Path) -> HubConfig:
    return HubConfig(
        state_dir=path / "state",
        default_route=["tooly"],
        routes=[RouteRule(name="coding", agents=["tooly"])],
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


def _get_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
