import json
import tempfile
import time
import unittest
from pathlib import Path

from agent_hub.adaptive import AdaptiveLearningStore
from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.evaluation.proof_benchmark import BenchmarkProofRunner, load_benchmark_corpus
from agent_hub.explainability import explain_route_body, format_route_explanation
from agent_hub.learning_proof import learning_dashboard_body, route_history_body
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.core.router import AgentRouter
from agent_hub.observability import record_event


class ProofInfrastructureTests(unittest.TestCase):
    def test_corpus_loader_reads_fifty_tasks(self) -> None:
        tasks = load_benchmark_corpus(Path("benchmarks"), route="coding", limit=50)

        self.assertEqual(len(tasks), 50)
        self.assertEqual(
            sorted({task.type for task in tasks}),
            ["coding", "debugging", "refactoring", "repo-analysis", "test-generation"],
        )

    def test_benchmark_proof_runner_writes_json_and_markdown_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _proof_config(Path(tmp))

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    if self.agent.name == "baseline":
                        time.sleep(0.01)
                    return ProviderResult(
                        text="validate test error fix provider",
                        model=self.agent.model,
                        usage={"prompt_tokens": 100, "completion_tokens": 40},
                        finish_reason="stop",
                    )

            report = BenchmarkProofRunner(config, provider_factory=Provider).run(
                route="coding",
                baseline="baseline",
                limit=3,
                corpus_dir=Path("benchmarks"),
                output_dir=Path(tmp) / "reports",
            )

            self.assertEqual(report["object"], "agent_hub.benchmark_proof")
            self.assertEqual(report["task_count"], 3)
            self.assertGreater(report["cost_reduction"], 0)
            self.assertIsNotNone(report["latency_reduction"])
            self.assertIn("success_delta", report)
            self.assertTrue(Path(report["report_paths"]["json"]).exists())
            self.assertTrue(Path(report["report_paths"]["markdown"]).exists())
            saved = json.loads(Path(report["report_paths"]["json"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["object"], "agent_hub.benchmark_proof")

    def test_explain_route_reports_selected_reasons_and_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _proof_config(Path(tmp))
            report = explain_route_body(
                config,
                route="coding",
                prompt="fix tests",
                output_tokens=100,
                prefer="balanced",
                needs_tools=False,
            )
            text = format_route_explanation(report)

            self.assertEqual(report["object"], "agent_hub.route_explanation")
            self.assertTrue(report["candidates"])
            self.assertIn("Selected:", text)
            self.assertIn("Reasons:", text)
            self.assertIn("Rejected", text)

    def test_learning_dashboard_and_route_history_show_proof_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _proof_config(Path(tmp))
            store = AdaptiveLearningStore(config.state_dir)
            store.record_outcome(
                request_id="r1",
                route="coding",
                task_type="coding",
                workflow_pattern="direct_route",
                workflow_role="",
                agent=config.agents["routed"],
                model="routed-model",
                success=True,
                latency_seconds=0.1,
                failover_attempts=0,
                input_tokens=100,
                output_tokens=40,
                estimated_cost_usd=0.00018,
                final=True,
            )
            record_event(
                config.state_dir,
                "routing",
                {
                    "type": "routing_decision",
                    "request_id": "r1",
                    "agent": "routed",
                    "provider": "openai-compatible",
                    "model": "routed-model",
                    "routing_decision": {"selected_agent": "routed"},
                },
            )
            router = AgentRouter(config, provider_factory=_UnusedProvider)

            learning = learning_dashboard_body(config, router)
            history = route_history_body(config, weeks=4)

            self.assertEqual(learning["object"], "agent_hub.learning_dashboard")
            self.assertGreaterEqual(learning["summary"]["routes"], 1)
            self.assertEqual(history["object"], "agent_hub.route_history")
            self.assertGreaterEqual(history["total_routes"], 1)


def _proof_config(root: Path) -> HubConfig:
    return HubConfig(
        state_dir=root / "state",
        workspace_dir=Path.cwd(),
        approval_mode="auto",
        free_only=False,
        default_route=["routed", "baseline"],
        routes=[RouteRule(name="coding", agents=["routed", "baseline"])],
        agents={
            "routed": AgentConfig(
                name="routed",
                provider="openai-compatible",
                model="routed-model",
                base_url="http://127.0.0.1:9999",
                cost_per_million_input=1.0,
                cost_per_million_output=2.0,
                supports_tools=True,
            ),
            "baseline": AgentConfig(
                name="baseline",
                provider="anthropic",
                model="claude-sonnet-baseline",
                cost_per_million_input=10.0,
                cost_per_million_output=20.0,
                supports_tools=True,
            ),
        },
    )


class _UnusedProvider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        raise AssertionError("provider should not be called")


if __name__ == "__main__":
    unittest.main()
