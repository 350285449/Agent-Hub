from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.core.context import ContextEngine, RepositoryMemory
from agent_hub.core.health import ProviderHealth, ProviderHealthManager, calculate_provider_score
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.providers import OpenAIChatProvider
from agent_hub.providers.base import StreamChunk
from agent_hub.server import AgentHubHTTPServer
from agent_hub.tools import (
    ToolCall,
    ToolExecutionContext,
    ToolExecutionPipeline,
    create_builtin_registry,
    openai_tool_specs,
)
from agent_hub.workflows import WorkflowEngine


class NativeStreamingTests(unittest.TestCase):
    def test_openai_compatible_provider_yields_stream_chunks(self) -> None:
        agent = AgentConfig(
            name="local",
            provider="openai-compatible",
            model="test-model",
            base_url="http://127.0.0.1:9999",
            supports_streaming=True,
        )
        provider = OpenAIChatProvider(agent)
        request = HubRequest(session_id="s", messages=[{"role": "user", "content": "hi"}])

        with patch("agent_hub.providers._post_stream_json") as stream_json:
            stream_json.return_value = iter(
                [
                    {"model": "test-model", "choices": [{"delta": {"content": "hel"}, "finish_reason": None}]},
                    {"model": "test-model", "choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]},
                ]
            )
            chunks = list(provider.stream(request))

        self.assertEqual([chunk.text for chunk in chunks], ["hel", "lo"])
        self.assertEqual(chunks[-1].finish_reason, "stop")

    def test_openai_sse_uses_native_stream_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = AgentHubHTTPServer(("127.0.0.1", 0), _stream_config(Path(tmp), streaming=True))
            server.router.provider_factory = _NativeProvider
            thread = _start(server)
            try:
                text, headers = _post_text_with_headers(
                    f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "stream": True,
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
            finally:
                _stop(server, thread)

        self.assertEqual(headers.get("X-Agent-Hub-Stream-Mode"), "native")
        self.assertIn('"content": "hel"', text)
        self.assertIn('"content": "lo"', text)
        self.assertIn("data: [DONE]", text)

    def test_streaming_falls_back_to_compatibility_when_native_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = AgentHubHTTPServer(("127.0.0.1", 0), _stream_config(Path(tmp), streaming=False))
            server.router.provider_factory = _CompatibilityOnlyProvider
            thread = _start(server)
            try:
                text, headers = _post_text_with_headers(
                    f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "stream": True,
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                )
            finally:
                _stop(server, thread)

        self.assertEqual(headers.get("X-Agent-Hub-Stream-Mode"), "compatibility")
        self.assertIn("compat", text)


class HealthContextWorkflowToolTests(unittest.TestCase):
    def test_provider_health_score_and_persistence_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider_health.json"
            health = ProviderHealth(success_count=4, failure_count=1, total_latency_seconds=2.0)
            manager = ProviderHealthManager(path)
            manager.save({"agent": health})
            loaded = manager.load()
            score = calculate_provider_score(
                AgentConfig(name="agent", provider="openai-compatible", model="m", base_url="http://127.0.0.1:1"),
                loaded["agent"],
            )

        self.assertEqual(loaded["agent"].success_count, 4)
        self.assertGreater(score.total, 0)
        self.assertGreater(score.reliability, 0)

    def test_context_engine_compresses_old_messages_and_keeps_recent_context(self) -> None:
        memory = RepositoryMemory(repo_summary="Small router project")
        memory.remember_file("agent_hub/core/router.py", "Routes providers.", important=True)
        engine = ContextEngine(max_tokens=220, preserve_recent=2, repository_memory=memory)
        messages = [
            {"role": "user", "content": "old " + ("x" * 900)},
            {"role": "assistant", "content": "older " + ("y" * 900)},
            {"role": "user", "content": "important state", "task_progress": [{"title": "keep"}]},
            {"role": "user", "content": "recent one"},
            {"role": "assistant", "content": "recent two"},
        ]
        window = engine.compress(HubRequest(session_id="s", messages=messages))

        text = "\n".join(str(message.get("content")) for message in window.messages)
        self.assertIn("Conversation summary", text)
        self.assertIn("recent one", text)
        self.assertTrue(any("task_progress" in message for message in window.messages))
        self.assertIn("agent_hub/core/router.py", text)
        self.assertGreater(window.metadata.estimated_tokens, window.metadata.compressed_tokens)

    def test_workflow_engine_runs_planner_worker_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["agent"],
                routes=[RouteRule(name="coding", agents=["agent"])],
                agents={
                    "agent": AgentConfig(
                        name="agent",
                        provider="openai-compatible",
                        model="workflow-model",
                        base_url="http://127.0.0.1:9999",
                        free=True,
                    )
                },
            )
            engine = WorkflowEngine(config)
            engine.router.provider_factory = lambda agent: _WorkflowProvider(agent, calls)
            result = engine.execute(
                "code",
                HubRequest(session_id="wf", messages=[{"role": "user", "content": "add a test"}]),
            )

        self.assertEqual(calls, ["agent", "agent", "agent"])
        self.assertEqual([stage.role for stage in result.memory.stage_results], ["planner", "coder", "reviewer"])
        self.assertIn("workflow", result.response.raw["agent_hub"])

    def test_tool_registry_and_execution_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("hello tool world", encoding="utf-8")
            config = HubConfig(state_dir=root / "state", workspace_dir=root, approval_mode="auto")
            registry = create_builtin_registry(config)
            context = ToolExecutionContext(config=config)
            pipeline = ToolExecutionPipeline(registry)

            read = pipeline.execute(ToolCall(name="file_read", arguments={"path": "README.md"}), context)
            search = pipeline.execute(ToolCall(name="search_repo", arguments={"query": "tool"}), context)
            write = pipeline.execute(
                ToolCall(name="file_write", arguments={"path": "out.txt", "content": "ok"}),
                context,
            )

        self.assertTrue(read.ok)
        self.assertIn("hello tool world", read.content["content"])
        self.assertTrue(search.ok)
        self.assertEqual(search.content["matches"][0]["path"], "README.md")
        self.assertTrue(write.ok)
        self.assertIn("file_read", registry.names())
        self.assertTrue(any(spec["function"]["name"] == "file_read" for spec in openai_tool_specs(registry)))


class _NativeProvider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def supports_streaming(self) -> bool:
        return True

    def complete(self, request: HubRequest) -> ProviderResult:
        return ProviderResult(text="compat", model=self.agent.model, finish_reason="stop")

    def chat(self, request: HubRequest) -> ProviderResult:
        return self.complete(request)

    def stream(self, request: HubRequest):
        yield StreamChunk(text="hel", delta={"content": "hel"}, model=self.agent.model)
        yield StreamChunk(text="lo", delta={"content": "lo"}, model=self.agent.model)
        yield StreamChunk(delta={}, model=self.agent.model, finish_reason="stop")


class _CompatibilityOnlyProvider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        return ProviderResult(text="compat", model=self.agent.model, finish_reason="stop")


class _WorkflowProvider:
    def __init__(self, agent: AgentConfig, calls: list[str]) -> None:
        self.agent = agent
        self.calls = calls

    def complete(self, request: HubRequest) -> ProviderResult:
        self.calls.append(self.agent.name)
        return ProviderResult(text=f"stage {len(self.calls)} done", model=self.agent.model, finish_reason="stop")


def _stream_config(path: Path, *, streaming: bool) -> HubConfig:
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
                supports_streaming=streaming,
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


def _post_text_with_headers(url: str, payload: dict) -> tuple[str, object]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8"), response.headers


if __name__ == "__main__":
    unittest.main()
