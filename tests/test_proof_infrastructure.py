import json
import tempfile
import time
import unittest
from pathlib import Path

from agent_hub.adaptive import AdaptiveLearningStore
from agent_hub.anonymous_proof import generate_anonymous_proof
from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.evaluation.datasets import resolve_benchmark_dataset, verify_benchmark_report
from agent_hub.evaluation.proof_benchmark import BenchmarkProofRunner, load_benchmark_corpus
from agent_hub.explainability import explain_route_body, format_route_explanation
from agent_hub.learning_proof import learning_dashboard_body, route_history_body
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.core.router import AgentRouter
from agent_hub.observability import record_event
from agent_hub.proof_artifacts import (
    benchmark_evolution_body,
    benchmark_share_card_body,
    case_study_body,
    format_route_replay,
    replay_route_body,
)


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
            self.assertIn("dataset_fingerprint", saved)

    def test_public_dataset_alias_exports_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _proof_config(Path(tmp))
            dataset = resolve_benchmark_dataset(
                config,
                dataset="coding-100",
                route="coding",
                limit=0,
                corpus_dir=Path("benchmarks"),
            )

            self.assertEqual(dataset.name, "coding-100")
            self.assertEqual(len(dataset.tasks), 100)
            self.assertTrue(dataset.fingerprint)

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    return ProviderResult(
                        text="validate test error fix provider",
                        model=self.agent.model,
                        usage={"prompt_tokens": 100, "completion_tokens": 40},
                        finish_reason="stop",
                    )

            report = BenchmarkProofRunner(config, provider_factory=Provider).run(
                route="coding",
                baseline="baseline",
                dataset="coding-100",
                limit=3,
                corpus_dir=Path("benchmarks"),
                output_dir=Path(tmp) / "reports",
            )
            verification = verify_benchmark_report(
                config,
                report_path=report["report_paths"]["json"],
                dataset="coding-100",
                corpus_dir=Path("benchmarks"),
            )

            self.assertEqual(report["task_count"], 3)
            self.assertEqual(report["dataset"]["name"], "coding-100")
            self.assertTrue(verification["ok"])

    def test_benchmark_verification_preserves_task_route_and_tool_need(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _proof_config(Path(tmp))
            corpus = Path(tmp) / "tool-tasks.jsonl"
            corpus.write_text(
                json.dumps(
                    {
                        "type": "coding",
                        "route": "coding",
                        "prompt": "Edit a workspace file and run the matching test.",
                        "expected_keywords": ["edit", "test"],
                        "needs_tools": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    assert request.route == "coding"
                    assert request.raw.get("needs_tools")
                    return ProviderResult(
                        text="edit workspace file test",
                        model=self.agent.model,
                        usage={"prompt_tokens": 100, "completion_tokens": 40},
                        finish_reason="stop",
                    )

            report = BenchmarkProofRunner(config, provider_factory=Provider).run(
                route="cloud-agent",
                baseline="baseline",
                dataset=str(corpus),
                output_dir=Path(tmp) / "reports",
            )
            verification = verify_benchmark_report(
                config,
                report_path=report["report_paths"]["json"],
                dataset=str(corpus),
            )

            self.assertTrue(report["results"][0]["needs_tools"])
            self.assertEqual(report["results"][0]["route"], "coding")
            self.assertTrue(verification["ok"])

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

    def test_route_replay_shows_selected_alternatives_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _proof_config(Path(tmp))
            record_event(
                config.state_dir,
                "routing",
                {
                    "type": "routing_decision",
                    "request_id": "replay-1",
                    "request_preview": "Fix failing pytest",
                    "agent": "routed",
                    "provider": "openai-compatible",
                    "model": "routed-model",
                    "routing_decision": {
                        "selected_agent": "routed",
                        "selected_provider": "openai-compatible",
                        "selected_model": "routed-model",
                        "reason": "best cost/performance score",
                        "candidate_scores": [
                            {
                                "agent": "routed",
                                "provider": "openai-compatible",
                                "model": "routed-model",
                                "final_routing_score": 82,
                                "estimated_cost_usd": 0.01,
                            },
                            {
                                "agent": "baseline",
                                "provider": "anthropic",
                                "model": "claude-sonnet-baseline",
                                "final_routing_score": 83,
                                "estimated_cost_usd": 0.0314,
                            },
                        ],
                    },
                },
            )

            replay = replay_route_body(config, "replay-1")
            text = format_route_replay(replay)

            self.assertTrue(replay["found"])
            self.assertEqual(replay["request"]["text"], "Fix failing pytest")
            self.assertEqual(replay["selected"]["agent"], "routed")
            self.assertEqual(replay["alternatives"][0]["agent"], "baseline")
            self.assertIn("Selected:", text)
            self.assertIn("Expected Quality:", text)

    def test_share_cards_case_study_and_evolution_use_local_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _proof_config(Path(tmp))
            reports_dir = config.state_dir / "benchmark_reports"
            reports_dir.mkdir(parents=True)
            (reports_dir / "benchmark-report.json").write_text(
                json.dumps(
                    {
                        "object": "agent_hub.benchmark_proof",
                        "task_count": 50,
                        "baseline": {"agent": "baseline", "provider": "anthropic", "model": "claude-sonnet"},
                        "comparison": {
                            "cost_reduction": 34.0,
                            "latency_reduction": 18.0,
                            "success_delta": 3.0,
                        },
                        "results": [],
                    }
                ),
                encoding="utf-8",
            )
            now = time.time()
            record_event(
                config.state_dir,
                "routing",
                {"type": "routing_decision", "request_id": "m1", "time": now - 61 * 24 * 3600, "agent": "baseline"},
            )
            record_event(
                config.state_dir,
                "routing",
                {"type": "routing_decision", "request_id": "m3", "time": now, "agent": "routed"},
            )

            card = benchmark_share_card_body(config)
            case_study = case_study_body(config)
            evolution = benchmark_evolution_body(config, months=3)

            self.assertIn("My Agent-Hub Benchmark", card["variants"]["markdown"])
            self.assertEqual(card["metrics"]["cost_reduction"], 34.0)
            self.assertEqual(case_study["benchmark"]["success_delta"], 3.0)
            self.assertEqual(evolution["object"], "agent_hub.benchmark_evolution")
            self.assertGreaterEqual(evolution["total_routes"], 2)

    def test_anonymous_proof_resolves_relative_state_dir_from_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            config = HubConfig(
                workspace_dir=workspace,
                state_dir=Path(".agent-hub/state"),
            )
            record_event(
                workspace / ".agent-hub" / "state",
                "routing",
                {"type": "routing_decision", "request_id": "proof-1", "provider": "local"},
            )

            proof = generate_anonymous_proof(config)

        self.assertEqual(proof["routes"], 1)
        self.assertEqual(proof["providers_used"], 1)


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
