from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.application.diagnostics_service import DiagnosticsApplicationService
from agent_hub.benchmarks.report_builder import build_public_150_reference_report
from agent_hub.benchmarks.task_suite import public_150_suite
from agent_hub.config import AgentConfig, HubConfig
from agent_hub.core.router import AgentRouter
from agent_hub.models import HubRequest
from agent_hub.routing_memory import learn_from_outcomes


class PublicBenchmarkProofDashboardTests(unittest.TestCase):
    def test_public_suite_has_required_category_counts(self) -> None:
        tasks = public_150_suite()
        counts: dict[str, int] = {}
        for task in tasks:
            counts[task.task] = counts.get(task.task, 0) + 1

        self.assertEqual(len(tasks), 150)
        self.assertEqual(counts["bug_fix"], 50)
        self.assertEqual(counts["refactor"], 50)
        self.assertEqual(counts["feature_request"], 50)

    def test_public_reference_report_publishes_required_counts(self) -> None:
        report = build_public_150_reference_report()

        self.assertEqual(report["object"], "agent_hub.public_benchmark_results")
        self.assertEqual(report["task_count"], 150)
        self.assertEqual(
            report["category_counts"],
            {"bug_fix": 50, "refactor": 50, "feature_request": 50},
        )
        self.assertGreater(report["savings"], 0)

    def test_context_intelligence_is_in_routing_scorecards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "billing.py").write_text(
                "class BillingService:\n    def charge(self, user):\n        return user\n",
                encoding="utf-8",
            )
            config = _config(root)
            router = AgentRouter(config)
            decision = router.decide(
                HubRequest(
                    session_id="s",
                    route="coding",
                    messages=[{"role": "user", "content": "Fix src/billing.py BillingService charge bug"}],
                )
            )

        self.assertTrue(decision.routing_context["context_intelligence"]["active"])
        stages = {
            row["stage"]
            for row in decision.routing_context["context_intelligence"]["routing_stages"]
        }
        self.assertEqual(
            stages,
            {"classification", "context_ranking", "context_packing", "candidate_scoring", "explainability"},
        )
        self.assertIn("context_intelligence", decision.candidate_scores[0])
        self.assertIn("context_intelligence_adjustment", decision.candidate_scores[0])

    def test_routing_memory_learning_builds_segment_profiles(self) -> None:
        learning = learn_from_outcomes(
            [
                {
                    "agent": "Claude",
                    "language": "Python",
                    "framework": "FastAPI",
                    "success": True,
                    "input_tokens": 7000,
                    "output_tokens": 1000,
                    "retry_count": 0,
                }
            ]
        )

        self.assertEqual(learning["model_profiles"]["Claude"]["Python/FastAPI"]["success"], 100.0)
        self.assertGreater(learning["ranking"][0]["confidence"], 0.0)
        self.assertLess(learning["ranking"][0]["confidence"], 1.0)

    def test_routing_memory_learning_weights_tokens_and_retries_by_similarity(self) -> None:
        learning = learn_from_outcomes(
            [
                {
                    "agent": "Claude",
                    "language": "Python",
                    "framework": "FastAPI",
                    "success": True,
                    "input_tokens": 1000,
                    "output_tokens": 0,
                    "retry_count": 1,
                    "similarity": 1.0,
                },
                {
                    "agent": "Claude",
                    "language": "Python",
                    "framework": "FastAPI",
                    "success": True,
                    "input_tokens": 1000,
                    "output_tokens": 0,
                    "retry_count": 1,
                    "similarity": 0.5,
                },
            ]
        )

        profile = learning["model_profiles"]["Claude"]["Python/FastAPI"]
        self.assertEqual(profile["weighted_attempts"], 1.5)
        self.assertEqual(profile["avg_tokens"], 1000.0)
        self.assertEqual(profile["avg_retries"], 1.0)
        self.assertEqual(learning["ranking"][0]["confidence"], 0.1579)

    def test_routing_memory_learning_handles_malformed_similarity_and_slashes(self) -> None:
        learning = learn_from_outcomes(
            [
                {
                    "agent": "Claude/Opus",
                    "language": "C/C++",
                    "framework": "Qt/Widgets",
                    "success": True,
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "retry_count": 0,
                    "similarity": "nan",
                    "latency_ms": "inf",
                }
            ]
        )

        profile = learning["model_profiles"]["Claude/Opus"]["C/C++/Qt/Widgets"]
        self.assertEqual(profile["success"], 100.0)
        self.assertEqual(profile["weighted_attempts"], 1.0)
        self.assertEqual(profile["avg_latency_ms"], 0.0)

    def test_proof_dashboard_exposes_repository_cards_and_model_performance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            body = DiagnosticsApplicationService(config).proof_dashboard_body()

        labels = {card["label"] for card in body["cards"]}
        self.assertEqual(body["object"], "agent_hub.visual_proof_dashboard")
        self.assertIn("Tokens Saved", labels)
        self.assertIn("Cost Saved", labels)
        self.assertIn("Success Rate", labels)
        self.assertIn("Retry Reduction", labels)
        self.assertIn("repository_proof", body)
        self.assertIn("model_performance", body)
        self.assertEqual(body["repository"]["name"], root.name)


def _config(root: Path) -> HubConfig:
    return HubConfig(
        workspace_dir=root,
        state_dir=root / "state",
        free_only=False,
        repo_context_enabled=False,
        default_route=["claude", "codex"],
        routes=[],
        agents={
            "claude": AgentConfig(
                name="claude",
                provider="anthropic",
                model="claude-test",
                context_window=200000,
                coding_score=0.9,
                supports_tools=True,
            ),
            "codex": AgentConfig(
                name="codex",
                provider="openai",
                model="codex-test",
                context_window=128000,
                coding_score=0.8,
                supports_tools=True,
            ),
        },
    )


if __name__ == "__main__":
    unittest.main()
