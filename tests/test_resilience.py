from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import patch

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.core.router import AgentRouter
from agent_hub.debug import provider_debug_context
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.providers import ProviderError, _post_stream_json
from agent_hub.providers.base import StreamChunk
from agent_hub.repository import RepositoryIndexer
from agent_hub.response_normalization import (
    SAFE_MALFORMED_CONTENT,
    normalize_openai_compatible_result,
    normalize_openai_stream_data,
)
from agent_hub.server import AgentHubHTTPServer
from agent_hub.tools.loop import compact_tool_result_for_loop, extract_tool_calls, valid_tool_calls, ToolLoopMetadata
from agent_hub.tools.types import ToolResult


class ResponseResilienceTests(unittest.TestCase):
    def test_openai_normalizer_repairs_missing_choices_and_tool_json(self) -> None:
        result = normalize_openai_compatible_result(
            {
                "message": {
                    "role": "bad-role",
                    "tool_calls": {
                        "id": "call_1",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"',
                        },
                    },
                }
            },
            default_model="model",
            provider_name="openai-compatible",
        )

        message = result.raw["choices"][0]["message"]
        call = message["tool_calls"][0]
        self.assertEqual(message["role"], "assistant")
        self.assertEqual(call["function"]["name"], "read_file")
        self.assertEqual(json.loads(call["function"]["arguments"]), {"path": "README.md"})
        self.assertTrue(result.raw["agent_hub_normalization"]["valid"])

    def test_stream_normalizer_ignores_empty_unusable_chunks(self) -> None:
        self.assertIsNone(normalize_openai_stream_data({}, default_model="model"))
        chunk = normalize_openai_stream_data(
            {"message": {"content": "hello"}},
            default_model="model",
        )
        self.assertEqual(chunk["delta"]["content"], "hello")
        self.assertEqual(chunk["finish_reason"], "stop")

    def test_router_retries_invalid_provider_then_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = _routing_config(Path(tmp), ["bad", "good"])

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(self.agent.name)
                    if self.agent.name == "bad":
                        return ProviderResult(text="", model=self.agent.model, raw={})
                    return ProviderResult(text="ok", model=self.agent.model, finish_reason="stop")

            response = AgentRouter(config, provider_factory=Provider).route(_request())

            self.assertEqual(response.text, "ok")
            self.assertEqual(calls, ["bad", "bad", "good"])
            self.assertEqual(response.failover[0].error_type, "invalid_provider_response")

    def test_router_generates_safe_empty_response_when_all_providers_are_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _routing_config(Path(tmp), ["bad"])

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    return ProviderResult(text="", model=self.agent.model, raw={})

            response = AgentRouter(config, provider_factory=Provider).route(_request())

            self.assertEqual(response.text, SAFE_MALFORMED_CONTENT)
            self.assertEqual(response.finish_reason, "stop")
            self.assertEqual(response.failover[0].error_type, "invalid_provider_response")

    def test_post_stream_json_skips_malformed_chunks_and_logs_missing_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            debug = provider_debug_context(
                enabled=True,
                debug_dir=Path(tmp) / "debug",
                request_id="stream-test",
                provider="openai-compatible",
                provider_name="test",
                model="model",
                routing_mode="coding",
                estimated_input_tokens=10,
                estimated_output_tokens=5,
                provider_limit=1000,
                stream_id="stream_1",
            )
            with patch(
                "urllib.request.urlopen",
                return_value=_FakeStreamResponse(
                    [
                        b"\n",
                        b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}\n\n',
                        b"data: {bad json\n\n",
                    ]
                ),
            ):
                chunks = list(
                    _post_stream_json(
                        "http://provider.invalid/stream",
                        headers={"Content-Type": "application/json"},
                        payload={"stream": True},
                        timeout=5,
                        debug=debug,
                    )
                )

            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0]["choices"][0]["delta"]["content"], "hi")
            log_text = (Path(tmp) / "debug" / "stream-test.jsonl").read_text(encoding="utf-8")
            self.assertIn("malformed_stream_chunk", log_text)
            self.assertIn("stream_missing_done", log_text)

    def test_cline_streaming_prefers_compatibility_even_when_native_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _routing_config(Path(tmp), ["native"])
            config.routes = [RouteRule(name="coding", agents=["native"])]
            config.agents["native"].supports_streaming = True
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            server.router.provider_factory = _NativeButClineCompatibilityProvider
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                text, headers = _post_text_with_headers(
                    f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "stream": True,
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                    headers={"User-Agent": "Cline/3.0"},
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(headers.get("X-Agent-Hub-Stream-Mode"), "compatibility")
            self.assertIn("compat", text)
            self.assertIn("data: [DONE]", text)

    def test_context_safety_cap_reduces_large_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            captured: list[HubRequest] = []
            config = _routing_config(Path(tmp), ["cap"])
            config.max_context_tokens = 1000
            config.agents["cap"].context_window = 2000
            config.agents["cap"].max_tokens = 200

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    captured.append(request)
                    return ProviderResult(text="ok", model=self.agent.model, finish_reason="stop")

            messages = [{"role": "user", "content": f"message {index} " + ("x" * 800)} for index in range(20)]
            AgentRouter(config, provider_factory=Provider).route(
                HubRequest(session_id="s", route="coding", messages=messages)
            )

            usage = captured[0].raw["agent_hub"]["context_usage"]
            self.assertTrue(usage["context_reduced"])
            self.assertLessEqual(usage["estimated_input_tokens"], 1200)
            self.assertIn("[Context reduced for provider compatibility]", usage["warnings"])

    def test_tool_call_and_result_recovery(self) -> None:
        result = ProviderResult(
            text="",
            model="model",
            raw={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "x",
                                    "function": {"name": "", "arguments": "{bad"},
                                },
                                {
                                    "id": "y",
                                    "function": {"name": "read_file", "arguments": "{bad"},
                                },
                            ]
                        }
                    }
                ]
            },
        )
        metadata = ToolLoopMetadata(max_tool_iterations=4)
        calls = valid_tool_calls(extract_tool_calls(result), metadata)

        self.assertEqual([call.name for call in calls], ["read_file"])
        self.assertEqual(calls[0].arguments, {})
        self.assertTrue(metadata.invalid_tool_calls)

        compacted = compact_tool_result_for_loop(
            ToolResult(call_id="y", name="read_file", ok=True, content={"content": "x" * 30_000})
        )
        self.assertTrue(compacted.metadata["compacted_for_provider"])
        self.assertTrue(compacted.content["truncated"])

    def test_repository_indexer_ignores_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".agent-hub" / "debug").mkdir(parents=True)
            (root / ".agent-hub" / "debug" / "trace.py").write_text("bad", encoding="utf-8")
            (root / "state").mkdir()
            (root / "state" / "session.py").write_text("bad", encoding="utf-8")
            (root / "logs").mkdir()
            (root / "logs" / "app.log").write_text("bad", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')", encoding="utf-8")

            index = RepositoryIndexer(
                root,
                ignore_patterns=[
                    ".agent-hub/**",
                    "state/**",
                    "sessions/**",
                    "logs/**",
                    "*.log",
                    "__pycache__/**",
                    ".pytest_cache/**",
                ],
            ).index()

            paths = {file.path for file in index.files}
            self.assertEqual(paths, {"src/app.py"})


class _FakeStreamResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines
        self.status = 200
        self.headers = {"x-request-id": "req_123"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def __iter__(self):
        return iter(self._lines)


class _NativeButClineCompatibilityProvider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        return ProviderResult(text="compat", model=self.agent.model, finish_reason="stop")

    def supports_streaming(self) -> bool:
        return True

    def stream(self, request: HubRequest):
        yield StreamChunk(text="native", delta={"content": "native"}, model=self.agent.model)
        raise ProviderError("native should not be used for Cline", error_type="invalid_provider_response")


def _routing_config(path: Path, agents: list[str]) -> HubConfig:
    return HubConfig(
        state_dir=path / "state",
        workspace_dir=path,
        approval_mode="auto",
        free_only=False,
        default_route=agents,
        routes=[RouteRule(name="coding", agents=agents)],
        agents={
            name: AgentConfig(
                name=name,
                provider="openai-compatible",
                provider_type="openai-compatible",
                base_url="http://127.0.0.1:9999",
                model=f"{name}-model",
                free=True,
            )
            for name in agents
        },
    )


def _request() -> HubRequest:
    return HubRequest(session_id="s", route="coding", messages=[{"role": "user", "content": "hello"}])


def _post_text_with_headers(url: str, payload: dict, headers: dict[str, str] | None = None) -> tuple[str, object]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8"), response.headers


if __name__ == "__main__":
    unittest.main()
