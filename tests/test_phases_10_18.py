from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from agent_hub.config import AgentConfig, HubConfig, RouteRule, config_from_dict
from agent_hub.evaluation import BenchmarkRunner, BenchmarkTask, ProviderScoreStore
from agent_hub.mcp import MCPServerRegistry
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.repository import RepoContextSelector, RepositoryIndexer
from agent_hub.server import AgentHubHTTPServer
from agent_hub.tools import ToolCall, ToolExecutionContext, ToolExecutionPipeline, create_builtin_registry, openai_tool_specs
from agent_hub.workflows import WorkflowEngine
from agent_hub.core.router import AgentRouter


class ToolHardeningAndLoopTests(unittest.TestCase):
    def test_tool_registry_file_safety_shell_denial_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("hello", encoding="utf-8")
            config = _tool_config(root)
            registry = create_builtin_registry(config)
            pipeline = ToolExecutionPipeline(registry)
            context = ToolExecutionContext(config=config)

            read = pipeline.execute(ToolCall(name="read_file", arguments={"path": "README.md"}), context)
            escaped = pipeline.execute(ToolCall(name="file_read", arguments={"path": "../outside.txt"}), context)
            shell = pipeline.execute(ToolCall(name="shell_execute", arguments={"command": "git reset --hard"}), context)
            specs = openai_tool_specs(registry)

        self.assertTrue(read.ok)
        self.assertFalse(escaped.ok)
        self.assertIn("workspace", escaped.error.lower())
        self.assertFalse(shell.ok)
        self.assertIn("blocked", shell.error.lower())
        self.assertTrue(any(spec["function"]["name"] == "file_read" for spec in specs))

    def test_tool_loop_executes_one_call_and_returns_final_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("tool loop evidence", encoding="utf-8")
            calls: list[HubRequest] = []
            router = AgentRouter(_tool_config(root), provider_factory=lambda agent: _SequenceProvider(agent, calls, [
                _tool_result("file_read", {"path": "README.md"}),
                ProviderResult(text="final after tool", model=agent.model, finish_reason="stop"),
            ]))

            response = router.route(HubRequest(session_id="s", route="coding", messages=[{"role": "user", "content": "read README.md"}]))

        self.assertEqual(response.text, "final after tool")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[-1].messages[-1]["role"], "tool")
        hub = response.raw["agent_hub"]
        self.assertEqual(hub["tool_iteration_count"], 1)
        self.assertTrue(hub["tool_results"][0]["ok"])

    def test_tool_loop_handles_multiple_denied_failed_and_max_iterations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("alpha beta", encoding="utf-8")
            config = _tool_config(root)

            multi_calls: list[HubRequest] = []
            multi_router = AgentRouter(config, provider_factory=lambda agent: _SequenceProvider(agent, multi_calls, [
                _tool_result_many([
                    ("file_read", {"path": "README.md"}),
                    ("search_repo", {"query": "beta"}),
                ]),
                ProviderResult(text="multi final", model=agent.model, finish_reason="stop"),
            ]))
            multi = multi_router.route(HubRequest(session_id="multi", route="coding", messages=[{"role": "user", "content": "search beta"}]))

            denied_config = _tool_config(root)
            denied_config.approval_mode = "ask"
            denied_calls: list[HubRequest] = []
            denied_router = AgentRouter(denied_config, provider_factory=lambda agent: _SequenceProvider(agent, denied_calls, [
                _tool_result("file_write", {"path": "x.txt", "content": "x"}),
                ProviderResult(text="denied handled", model=agent.model, finish_reason="stop"),
            ]))
            denied = denied_router.route(HubRequest(session_id="denied", route="coding", messages=[{"role": "user", "content": "write file"}]))

            failed_calls: list[HubRequest] = []
            failed_router = AgentRouter(config, provider_factory=lambda agent: _SequenceProvider(agent, failed_calls, [
                _tool_result("file_read", {"path": "missing.txt"}),
                ProviderResult(text="failure handled", model=agent.model, finish_reason="stop"),
            ]))
            failed = failed_router.route(HubRequest(session_id="failed", route="coding", messages=[{"role": "user", "content": "read missing.txt"}]))

            max_config = _tool_config(root)
            max_config.max_tool_iterations = 1
            max_calls: list[HubRequest] = []
            max_router = AgentRouter(max_config, provider_factory=lambda agent: _SequenceProvider(agent, max_calls, [
                _tool_result("file_read", {"path": "README.md"}),
                _tool_result("file_read", {"path": "README.md"}),
            ]))
            maxed = max_router.route(HubRequest(session_id="max", route="coding", messages=[{"role": "user", "content": "loop"}]))

        self.assertEqual(multi.raw["agent_hub"]["tool_iteration_count"], 1)
        self.assertEqual(len(multi.raw["agent_hub"]["tool_results"]), 2)
        self.assertEqual(denied.text, "denied handled")
        self.assertFalse(denied.raw["agent_hub"]["tool_results"][0]["ok"])
        self.assertEqual(failed.text, "failure handled")
        self.assertFalse(failed.raw["agent_hub"]["tool_results"][0]["ok"])
        self.assertEqual(maxed.finish_reason, "tool_loop_max_reached")
        self.assertTrue(maxed.raw["agent_hub"]["tool_loop"]["max_tool_iterations_reached"])


class MCPRepoWorkflowEvaluationStatusTests(unittest.TestCase):
    def test_mcp_config_normalizes_tools_into_agent_hub_tools(self) -> None:
        config = config_from_dict(
            {
                "agents": [],
                "mcp_servers": [
                    {
                        "name": "local",
                        "tools": [
                            {
                                "name": "lookup",
                                "description": "Lookup a symbol",
                                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
                                "permissions": ["read"],
                            }
                        ],
                    }
                ],
            }
        )
        registry = MCPServerRegistry(config)
        tools = registry.agent_hub_tools()

        self.assertEqual(tools[0].name, "mcp.local.lookup")
        self.assertEqual(tools[0].metadata["mcp"]["status"], "future_ready")

    def test_repository_index_selection_size_and_important_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Project docs", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
            pkg = root / "agent_hub"
            pkg.mkdir()
            (pkg / "router.py").write_text("import json\nclass Router: pass\n", encoding="utf-8")
            (pkg / "tools.py").write_text("from agent_hub.router import Router\n", encoding="utf-8")

            index = RepositoryIndexer(root).index()
            selection = RepoContextSelector(index).select("fix router tool imports", max_files=2, max_chars=500)

        self.assertIn("pyproject.toml", index.important_files)
        self.assertLessEqual(len(selection.files), 2)
        self.assertLessEqual(sum(len(text) for text in selection.summaries.values()), 500)
        self.assertTrue(any(file.path == "agent_hub/router.py" for file in selection.files))

    def test_workflow_retry_validation_and_patch_summary_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls: list[HubRequest] = []
            config = _tool_config(root)
            engine = WorkflowEngine(config)
            engine.router.provider_factory = lambda agent: _SequenceProvider(agent, calls, [
                ProviderResult(text="plan app.py", model=agent.model),
                ProviderResult(text="work app.py", model=agent.model),
                ProviderResult(text="blocking issue in app.py", model=agent.model),
                ProviderResult(text="retry fixed app.py", model=agent.model),
                ProviderResult(text="no blocking issues", model=agent.model),
                ProviderResult(text="validation pass", model=agent.model),
            ])

            result = engine.execute(
                "code",
                HubRequest(
                    session_id="wf",
                    messages=[{"role": "user", "content": "edit app.py"}],
                    raw={"validate": True, "patch_summary": True},
                ),
            )

        stages = [stage.stage for stage in result.memory.stage_results]
        self.assertIn("work_retry", stages)
        self.assertIn("validate", stages)
        self.assertIn("patch_summary", stages)
        self.assertEqual(result.memory.state.retries, 1)
        self.assertEqual(result.memory.state.final_status, "completed")

    def test_evaluation_scores_are_stored_and_status_endpoints_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _tool_config(root)
            router = AgentRouter(config, provider_factory=lambda agent: _SequenceProvider(agent, [], [
                ProviderResult(text="ok test fix health route context file_read", model=agent.model)
            ]))
            results = BenchmarkRunner(router, store=ProviderScoreStore(config.state_dir)).run(
                [BenchmarkTask("coding", "fix a test", ["test", "fix"], route="coding")]
            )
            scores = ProviderScoreStore(config.state_dir).load()

            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                status = _get_json(f"{base}/v1/status")
                history = _get_json(f"{base}/v1/routing-history")
                provider_scores = _get_json(f"{base}/v1/provider-scores")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertTrue(results[0].ok)
        self.assertIn("tooly", scores)
        self.assertEqual(status["object"], "agent_hub.status")
        self.assertEqual(history["object"], "agent_hub.routing_history")
        self.assertIn("tooly", provider_scores["data"])


class _SequenceProvider:
    def __init__(self, agent: AgentConfig, calls: list[HubRequest], results: list[ProviderResult]) -> None:
        self.agent = agent
        self.calls = calls
        self.results = results

    def complete(self, request: HubRequest) -> ProviderResult:
        self.calls.append(request)
        if len(self.calls) <= len(self.results):
            return self.results[len(self.calls) - 1]
        return self.results[-1]


def _tool_config(root: Path) -> HubConfig:
    return HubConfig(
        state_dir=root / "state",
        workspace_dir=root,
        approval_mode="auto",
        allow_shell_tools=True,
        shell_command_policy="allow",
        repo_context_enabled=False,
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


def _tool_result(name: str, arguments: dict) -> ProviderResult:
    return _tool_result_many([(name, arguments)])


def _tool_result_many(calls: list[tuple[str, dict]]) -> ProviderResult:
    return ProviderResult(
        text="",
        model="tool-model",
        raw={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call_{index}",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(arguments)},
                            }
                            for index, (name, arguments) in enumerate(calls, start=1)
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        finish_reason="tool_calls",
    )


def _get_json(url: str) -> dict:
    request = Request(url, method="GET")
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
