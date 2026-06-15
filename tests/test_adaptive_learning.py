from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from agent_hub.adaptive import AdaptiveLearningStore, estimate_known_cost_usd
from agent_hub.config import AgentConfig, HubConfig
from agent_hub.core.router import AgentRouter
from agent_hub.evaluation import BenchmarkTask
from agent_hub.evaluation.benchmark_suite import BenchmarkSuiteRunner
from agent_hub.failure_prediction import explain_success_probability, route_by_success_probability, score_success_probability, train_success_model
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.routing_memory.learning import learn_from_outcomes
from agent_hub.workflows.selector import WorkflowSelector


class AdaptiveLearningTests(unittest.TestCase):
    def test_store_persists_outcomes_and_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = AgentConfig(
                name="claude",
                provider="anthropic",
                model="claude-test",
                cost_per_million_input=3,
                cost_per_million_output=15,
            )
            store = AdaptiveLearningStore(Path(tmp))

            store.record_outcome(
                request_id="hub-1",
                route="coding",
                task_type="coding",
                workflow_pattern="single_worker",
                workflow_role="coder",
                agent=agent,
                model=agent.model,
                success=True,
                latency_seconds=1.2,
                failover_attempts=1,
                input_tokens=1000,
                output_tokens=200,
                estimated_cost_usd=estimate_known_cost_usd(agent, input_tokens=1000, output_tokens=200),
                retry_count=1,
                final=True,
            )
            store.record_workflow_result(
                request_id="hub-1",
                pattern="single_worker",
                task_type="coding",
                success=True,
                latency_seconds=1.4,
                recovered_by_failover=True,
                final_status="completed",
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
                retry_count=1,
            )
            feedback = store.record_feedback(request_id="hub-1", rating="up", workflow_success=True)
            summary = AdaptiveLearningStore(Path(tmp)).optimization_summary()

            self.assertTrue(feedback["matched"])
            self.assertEqual(summary["workflow_success_rate"]["successes"], 1)
            self.assertEqual(summary["failed_requests_recovered"], 1)
            self.assertEqual(summary["total_retries"], 1)
            self.assertEqual(summary["average_retries"], 1.0)
            self.assertGreater(summary["average_known_cost_usd"], 0)
            self.assertEqual(summary["task_model_winners"]["coding"]["agent"], "claude")
            self.assertEqual(summary["role_model_winners"]["coder"]["agent"], "claude")
            self.assertTrue(summary["model_scorecards"])
            self.assertEqual(summary["most_effective_providers"][0]["provider"], "anthropic")
            self.assertEqual(summary["recent_optimization_decisions"][-1]["retry_count"], 1)
            self.assertTrue(summary["dashboard"]["cards"])

    def test_store_sanitizes_non_finite_latency_and_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = AgentConfig(name="claude", provider="anthropic", model="claude-test")
            store = AdaptiveLearningStore(Path(tmp))

            store.record_outcome(
                request_id="bad-telemetry",
                route="coding",
                task_type="coding",
                workflow_pattern="single_worker",
                workflow_role="coder",
                agent=agent,
                model=agent.model,
                success=True,
                latency_seconds=float("nan"),
                failover_attempts=0,
                input_tokens=100,
                output_tokens=50,
                estimated_cost_usd=float("inf"),
                final=True,
            )
            store.record_workflow_result(
                request_id="bad-telemetry",
                pattern="single_worker",
                task_type="coding",
                success=True,
                latency_seconds=float("inf"),
                recovered_by_failover=False,
                final_status="completed",
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
                estimated_cost_usd=float("nan"),
            )

            summary = store.optimization_summary()

            self.assertIsNone(summary["average_known_cost_usd"])
            self.assertEqual(summary["recent_optimization_decisions"][-1]["latency_ms"], 0.0)
            workflow = next(
                item
                for item in summary["workflow_patterns"]
                if item["workflow_pattern"] == "single_worker"
            )
            self.assertEqual(workflow["average_latency_ms"], 0.0)
            self.assertNotIn("average_known_cost_usd", workflow)

    def test_workflow_analytics_reports_task_rows_and_role_winners(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            planner = AgentConfig(
                name="claude-planner",
                provider="anthropic",
                model="claude-planner-test",
                cost_per_million_input=3,
                cost_per_million_output=15,
            )
            worker = AgentConfig(
                name="gpt-worker",
                provider="openai",
                model="gpt-worker-test",
                cost_per_million_input=2,
                cost_per_million_output=10,
            )
            store = AdaptiveLearningStore(Path(tmp))

            store.record_outcome(
                request_id="research-planner",
                route="reasoning",
                task_type="research",
                workflow_pattern="planned_worker",
                workflow_role="planner",
                agent=planner,
                model=planner.model,
                success=True,
                latency_seconds=2.0,
                failover_attempts=0,
                retry_count=0,
                input_tokens=1200,
                output_tokens=300,
                estimated_cost_usd=estimate_known_cost_usd(planner, input_tokens=1200, output_tokens=300),
                final=True,
            )
            store.record_outcome(
                request_id="research-worker",
                route="coding",
                task_type="research",
                workflow_pattern="planned_worker",
                workflow_role="coder",
                agent=worker,
                model=worker.model,
                success=True,
                latency_seconds=3.0,
                failover_attempts=1,
                retry_count=1,
                input_tokens=1500,
                output_tokens=500,
                estimated_cost_usd=estimate_known_cost_usd(worker, input_tokens=1500, output_tokens=500),
                final=True,
            )
            store.record_workflow_result(
                request_id="research-worker",
                pattern="planned_worker",
                task_type="research",
                success=True,
                latency_seconds=14.0,
                recovered_by_failover=True,
                final_status="completed",
                agent=worker.name,
                provider=worker.provider,
                model=worker.model,
                retry_count=2,
            )

            summary = store.optimization_summary()
            row = next(
                item
                for item in summary["workflow_analytics"]
                if item["workflow_pattern"] == "planned_worker" and item["task_type"] == "research"
            )

            self.assertEqual(row["label"], "Research Workflow")
            self.assertEqual(row["success_rate"], 1.0)
            self.assertEqual(row["average_latency_ms"], 14000.0)
            self.assertGreater(row["average_known_cost_usd"], 0)
            self.assertEqual(row["total_retries"], 2)
            self.assertEqual(row["average_retries"], 2.0)
            self.assertEqual(row["best_planner"]["agent"], "claude-planner")
            self.assertEqual(row["best_worker"]["agent"], "gpt-worker")
            self.assertEqual(summary["dashboard"]["workflow_analytics"][0]["label"], "Research Workflow")

    def test_routing_signal_exposes_scorecard_and_threshold_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = AgentConfig(name="claude", provider="anthropic", model="claude-test")
            store = AdaptiveLearningStore(Path(tmp))

            for index in range(4):
                store.record_outcome(
                    request_id=f"warm-{index}",
                    route="coding",
                    task_type="coding",
                    workflow_pattern="single_worker",
                    workflow_role="coder",
                    agent=agent,
                    model=agent.model,
                    success=True,
                    latency_seconds=1,
                    failover_attempts=0,
                    input_tokens=100,
                    output_tokens=50,
                    estimated_cost_usd=None,
                    final=True,
                )

            warming = store.routing_signal(
                "claude",
                route="coding",
                task_type="coding",
                workflow_pattern="single_worker",
                workflow_role="coder",
            )
            self.assertFalse(warming["active"])
            self.assertEqual(warming["scope"], "exact")
            self.assertEqual(warming["samples_needed"], 1)

            store.record_outcome(
                request_id="ready",
                route="coding",
                task_type="coding",
                workflow_pattern="single_worker",
                workflow_role="coder",
                agent=agent,
                model=agent.model,
                success=True,
                latency_seconds=1,
                failover_attempts=0,
                input_tokens=100,
                output_tokens=50,
                estimated_cost_usd=None,
                final=True,
            )
            ready = store.routing_signal(
                "claude",
                route="coding",
                task_type="coding",
                workflow_pattern="single_worker",
                workflow_role="coder",
            )

            self.assertTrue(ready["active"])
            self.assertGreater(ready["adaptive_bonus"], 0)
            self.assertEqual(ready["scorecard"]["success_rate"], 1.0)
            self.assertIn("sample_confidence", ready["scorecard"])
            self.assertIn("freshness_score", ready["scorecard"])
            self.assertIn("adjusted_quality_score", ready["scorecard"])
            self.assertIn("trend_score", ready["scorecard"])
            self.assertIn("consistency_score", ready["scorecard"])
            self.assertIn("retry_score", ready["scorecard"])

    def test_adaptive_scorecard_rewards_recent_improvement_and_penalizes_instability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = AgentConfig(name="claude", provider="anthropic", model="claude-test")
            store = AdaptiveLearningStore(Path(tmp))

            for index, success in enumerate([False] * 12 + [True] * 18):
                store.record_outcome(
                    request_id=f"trend-{index}",
                    route="coding",
                    task_type="coding",
                    workflow_pattern="single_worker",
                    workflow_role="coder",
                    agent=agent,
                    model=agent.model,
                    success=success,
                    latency_seconds=1,
                    failover_attempts=0,
                    input_tokens=100,
                    output_tokens=50,
                    estimated_cost_usd=None,
                    retry_count=0,
                    error_type="" if success else "runtime_error",
                    final=True,
                )

            signal = store.routing_signal(
                "claude",
                route="coding",
                task_type="coding",
                workflow_pattern="single_worker",
                workflow_role="coder",
            )
            scorecard = signal["scorecard"]

            self.assertTrue(signal["active"])
            self.assertGreater(scorecard["trend_score"], 0.5)
            self.assertEqual(scorecard["success_streak"], 18)
            self.assertGreater(scorecard["error_rate"], 0.0)
            self.assertLess(scorecard["error_score"], 1.0)

    def test_adaptive_bonus_is_damped_by_confidence_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = AgentConfig(name="claude", provider="anthropic", model="claude-test")
            store = AdaptiveLearningStore(Path(tmp))

            for index in range(20):
                store.record_outcome(
                    request_id=f"fresh-{index}",
                    route="coding",
                    task_type="coding",
                    workflow_pattern="single_worker",
                    workflow_role="coder",
                    agent=agent,
                    model=agent.model,
                    success=True,
                    latency_seconds=1,
                    failover_attempts=0,
                    input_tokens=100,
                    output_tokens=50,
                    estimated_cost_usd=None,
                    final=True,
                )

            fresh = store.routing_signal(
                "claude",
                route="coding",
                task_type="coding",
                workflow_pattern="single_worker",
                workflow_role="coder",
            )
            state = store.load()
            for row in state["aggregates"].values():
                row["last_seen_at"] = time.time() - (180 * 86400)
            store.save(state)
            stale = store.routing_signal(
                "claude",
                route="coding",
                task_type="coding",
                workflow_pattern="single_worker",
                workflow_role="coder",
            )

            self.assertGreater(fresh["scorecard"]["sample_confidence"], 0.6)
            self.assertLess(stale["scorecard"]["freshness_score"], fresh["scorecard"]["freshness_score"])
            self.assertLess(stale["adaptive_bonus"], fresh["adaptive_bonus"])

    def test_learning_ranking_uses_quality_recency_feedback_and_bad_data(self) -> None:
        now = time.time()
        rows = [
            {
                "agent": "fresh-good",
                "language": "python",
                "framework": "fastapi",
                "success": True,
                "input_tokens": 1000,
                "output_tokens": 200,
                "retry_count": 0,
                "outcome_score": 0.92,
                "latency_ms": 900,
                "feedback_rating": "up",
                "time": now,
                "similarity": 1.0,
            }
            for _ in range(8)
        ] + [
            {
                "agent": "stale-bad",
                "language": "python",
                "framework": "fastapi",
                "success": False,
                "input_tokens": 1000,
                "output_tokens": 800,
                "retry_count": 3,
                "outcome_score": 0.25,
                "latency_ms": 9000,
                "feedback_rating": "down",
                "time": now - (120 * 86400),
                "similarity": 1.0,
            }
            for _ in range(8)
        ]

        learning = learn_from_outcomes(rows)
        ranking = learning["ranking"]

        self.assertEqual(ranking[0]["agent"], "fresh-good")
        self.assertGreater(ranking[0]["rank_score"], ranking[1]["rank_score"])
        self.assertIn("score_breakdown", ranking[0])
        self.assertGreater(ranking[0]["freshness_score"], ranking[1]["freshness_score"])
        self.assertLess(ranking[0]["bad_rate"], ranking[1]["bad_rate"])

    def test_router_uses_adaptive_bonus_after_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _router_config(root)
            good = config.agents["good"]
            bad = config.agents["bad"]
            store = AdaptiveLearningStore(config.state_dir)
            for index in range(5):
                store.record_outcome(
                    request_id=f"good-{index}",
                    route="",
                    task_type="coding",
                    workflow_pattern="",
                    workflow_role="",
                    agent=good,
                    model=good.model,
                    success=True,
                    latency_seconds=1,
                    failover_attempts=0,
                    input_tokens=10,
                    output_tokens=5,
                    estimated_cost_usd=None,
                    final=True,
                )
                store.record_outcome(
                    request_id=f"bad-{index}",
                    route="",
                    task_type="coding",
                    workflow_pattern="",
                    workflow_role="",
                    agent=bad,
                    model=bad.model,
                    success=False,
                    latency_seconds=5,
                    failover_attempts=0,
                    input_tokens=10,
                    output_tokens=0,
                    estimated_cost_usd=None,
                    final=False,
                )
            calls: list[str] = []
            config.expose_routing_details = True

            response = AgentRouter(
                config,
                provider_factory=lambda agent: _Provider(agent, calls),
            ).route(HubRequest(session_id="s", messages=[{"role": "user", "content": "fix this code"}]))

            self.assertEqual(response.agent, "good")
            self.assertEqual(calls, ["good"])
            decision = response.raw["agent_hub"]["routing_decision"]
            self.assertEqual(decision["selected_agent"], "good")
            self.assertTrue(decision["candidate_scores"][0]["adaptive"]["active"])
            self.assertGreater(decision["candidate_scores"][0]["adaptive"]["adaptive_bonus"], 0)
            self.assertGreater(decision["candidate_scores"][0]["adaptive_adjustment"], 0)
            self.assertIn(
                "adaptive_learning",
                [item["name"] for item in decision["candidate_scores"][0]["score_adjustments"]],
            )

    def test_trained_cloud_model_strongly_beats_untrained_cloud_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                repo_context_enabled=False,
                automatic_escalation_enabled=False,
                default_route=["untrained-cloud", "trained-cloud"],
                agents={
                    "untrained-cloud": AgentConfig(
                        name="untrained-cloud",
                        provider="openai-compatible",
                        provider_type="ollama-cloud",
                        model="untrained:cloud",
                        base_url="http://127.0.0.1:9999",
                    ),
                    "trained-cloud": AgentConfig(
                        name="trained-cloud",
                        provider="openai-compatible",
                        provider_type="ollama-cloud",
                        model="trained:cloud",
                        base_url="http://127.0.0.1:9999",
                    ),
                },
            )
            trained = config.agents["trained-cloud"]
            store = AdaptiveLearningStore(config.state_dir)
            for index in range(36):
                store.record_outcome(
                    request_id=f"trained-cloud-{index}",
                    route="",
                    task_type="coding",
                    workflow_pattern="",
                    workflow_role="",
                    agent=trained,
                    model=trained.model,
                    success=True,
                    latency_seconds=1,
                    failover_attempts=0,
                    input_tokens=100,
                    output_tokens=50,
                    estimated_cost_usd=None,
                    final=True,
                )

            config.expose_routing_details = True
            decision = AgentRouter(config).decide(
                HubRequest(session_id="s", messages=[{"role": "user", "content": "fix this code"}])
            )

            trained_score = next(row for row in decision.candidate_scores if row["agent"] == "trained-cloud")
            untrained_score = next(row for row in decision.candidate_scores if row["agent"] == "untrained-cloud")

            self.assertEqual(decision.selected_agent, "trained-cloud")
            self.assertGreaterEqual(trained_score["adaptive"]["adaptive_bonus"], 20.0)
            self.assertEqual(untrained_score["adaptive"]["adaptive_bonus"], 0.0)
            self.assertEqual(trained_score["adaptive"]["scorecard"]["training_status"], "trained_cloud")
            self.assertGreater(
                trained_score["final_score"] - untrained_score["final_score"],
                15.0,
            )

    def test_router_keeps_cold_start_and_manual_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _router_config(root)
            store = AdaptiveLearningStore(config.state_dir)
            for index in range(4):
                store.record_outcome(
                    request_id=f"good-{index}",
                    route="",
                    task_type="coding",
                    workflow_pattern="",
                    workflow_role="",
                    agent=config.agents["good"],
                    model="good-test",
                    success=True,
                    latency_seconds=1,
                    failover_attempts=0,
                    input_tokens=1,
                    output_tokens=1,
                    estimated_cost_usd=None,
                    final=True,
                )
            calls: list[str] = []
            router = AgentRouter(config, provider_factory=lambda agent: _Provider(agent, calls))

            cold = router.route(HubRequest(session_id="s1", messages=[{"role": "user", "content": "fix code"}]))
            manual = router.route(
                HubRequest(
                    session_id="s2",
                    preferred_agent="bad",
                    messages=[{"role": "user", "content": "fix code"}],
                )
            )

            self.assertEqual(cold.agent, "bad")
            self.assertEqual(manual.agent, "bad")

    def test_router_can_disable_adaptive_routing_bonus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _router_config(root)
            config.adaptive_routing_enabled = False
            store = AdaptiveLearningStore(config.state_dir)
            for index in range(5):
                store.record_outcome(
                    request_id=f"good-{index}",
                    route="",
                    task_type="coding",
                    workflow_pattern="",
                    workflow_role="",
                    agent=config.agents["good"],
                    model="good-test",
                    success=True,
                    latency_seconds=1,
                    failover_attempts=0,
                    input_tokens=1,
                    output_tokens=1,
                    estimated_cost_usd=None,
                    final=True,
                )
            calls: list[str] = []

            response = AgentRouter(config, provider_factory=lambda agent: _Provider(agent, calls)).route(
                HubRequest(session_id="s", messages=[{"role": "user", "content": "fix code"}])
            )

            self.assertEqual(response.agent, "bad")

    def test_workflow_selector_patterns_and_override(self) -> None:
        selector = WorkflowSelector(HubConfig())

        self.assertEqual(
            selector.select(HubRequest(session_id="s", messages=[{"role": "user", "content": "hello"}])).pattern,
            "direct_route",
        )
        self.assertEqual(
            selector.select(HubRequest(session_id="s", messages=[{"role": "user", "content": "fix app.py"}])).pattern,
            "single_worker",
        )
        self.assertEqual(
            selector.select(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "critical security review app.py tests/test_app.py"}],
                )
            ).pattern,
            "reviewed_worker",
        )
        self.assertEqual(
            selector.select(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "hello"}],
                    raw={"agent_hub": {"workflow_pattern": "team_reviewed"}},
                )
            ).pattern,
            "team_reviewed",
        )
        large = selector.select(
            HubRequest(
                session_id="s",
                messages=[{"role": "user", "content": "large architecture migration touching many files"}],
            )
        )
        self.assertEqual(large.pattern, "team_reviewed")
        self.assertTrue(large.to_dict()["signals"]["large_or_high_risk"])

    def test_workflow_selector_uses_adaptive_upgrade_after_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(state_dir=Path(tmp) / "state")
            store = AdaptiveLearningStore(config.state_dir)
            for index in range(5):
                store.record_workflow_result(
                    request_id=f"single-{index}",
                    pattern="single_worker",
                    task_type="coding",
                    success=False,
                    latency_seconds=2,
                    recovered_by_failover=False,
                    final_status="blocked",
                    agent="bad",
                    provider="openai-compatible",
                    model="bad-test",
                )
                store.record_workflow_result(
                    request_id=f"reviewed-{index}",
                    pattern="reviewed_worker",
                    task_type="coding",
                    success=True,
                    latency_seconds=3,
                    recovered_by_failover=False,
                    final_status="completed",
                    agent="good",
                    provider="openai-compatible",
                    model="good-test",
                )

            selection = WorkflowSelector(config).select(
                HubRequest(session_id="s", messages=[{"role": "user", "content": "fix app.py"}])
            )
            override = WorkflowSelector(config).select(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "fix app.py"}],
                    raw={"agent_hub": {"workflow_pattern": "single_worker"}},
                )
            )

            self.assertEqual(selection.pattern, "reviewed_worker")
            self.assertTrue(selection.adaptive_upgrade)
            self.assertEqual(selection.baseline_pattern, "single_worker")
            self.assertEqual(override.pattern, "single_worker")

    def test_workflow_upgrade_prefers_task_specific_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(state_dir=Path(tmp) / "state")
            store = AdaptiveLearningStore(config.state_dir)
            for index in range(5):
                store.record_workflow_result(
                    request_id=f"docs-single-{index}",
                    pattern="single_worker",
                    task_type="docs",
                    success=False,
                    latency_seconds=2,
                    recovered_by_failover=False,
                    final_status="blocked",
                    agent="bad",
                    provider="openai-compatible",
                    model="bad-test",
                )
                store.record_workflow_result(
                    request_id=f"docs-reviewed-{index}",
                    pattern="reviewed_worker",
                    task_type="docs",
                    success=True,
                    latency_seconds=3,
                    recovered_by_failover=False,
                    final_status="completed",
                    agent="good",
                    provider="openai-compatible",
                    model="good-test",
                )

            selection = WorkflowSelector(config).select(
                HubRequest(session_id="s", messages=[{"role": "user", "content": "fix app.py"}])
            )

            self.assertEqual(selection.pattern, "single_worker")
            self.assertFalse(selection.adaptive_upgrade)

    def test_record_workflow_result_replaces_duplicate_request_contribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AdaptiveLearningStore(Path(tmp))
            store.record_workflow_result(
                request_id="repeat",
                pattern="single_worker",
                task_type="coding",
                success=False,
                latency_seconds=2,
                recovered_by_failover=False,
                final_status="blocked",
                agent="bad",
                provider="openai-compatible",
                model="bad-test",
                retry_count=2,
                estimated_cost_usd=0.2,
            )
            store.record_workflow_result(
                request_id="repeat",
                pattern="single_worker",
                task_type="coding",
                success=True,
                latency_seconds=4,
                recovered_by_failover=True,
                final_status="completed",
                agent="good",
                provider="openai-compatible",
                model="good-test",
                retry_count=1,
                estimated_cost_usd=0.1,
            )

            row = next(
                item
                for item in store.optimization_summary()["workflow_patterns"]
                if item["workflow_pattern"] == "single_worker"
            )
            analytics = next(
                item
                for item in store.optimization_summary()["workflow_analytics"]
                if item["workflow_pattern"] == "single_worker" and item["task_type"] == "coding"
            )

            self.assertEqual(row["attempts"], 1)
            self.assertEqual(row["success_rate"], 1.0)
            self.assertEqual(row["total_retries"], 1)
            self.assertEqual(row["average_latency_ms"], 4000.0)
            self.assertEqual(analytics["average_known_cost_usd"], 0.1)

    def test_feedback_workflow_override_keeps_duplicate_replacement_balanced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AdaptiveLearningStore(Path(tmp))
            store.record_workflow_result(
                request_id="repeat-feedback",
                pattern="single_worker",
                task_type="coding",
                success=False,
                latency_seconds=2,
                recovered_by_failover=False,
                final_status="blocked",
                agent="bad",
                provider="openai-compatible",
                model="bad-test",
            )
            store.record_feedback(
                request_id="repeat-feedback",
                rating="up",
                workflow_success=True,
            )
            store.record_workflow_result(
                request_id="repeat-feedback",
                pattern="single_worker",
                task_type="coding",
                success=True,
                latency_seconds=3,
                recovered_by_failover=False,
                final_status="completed",
                agent="good",
                provider="openai-compatible",
                model="good-test",
            )

            row = next(
                item
                for item in store.optimization_summary()["workflow_patterns"]
                if item["workflow_pattern"] == "single_worker"
            )

            self.assertEqual(row["attempts"], 1)
            self.assertEqual(row["success_rate"], 1.0)

    def test_failure_prediction_training_matches_named_candidates(self) -> None:
        model = train_success_model(
            [
                {"name": "fast-agent", "provider": "openai", "task_type": "coding", "success": True},
                {"name": "fast-agent", "provider": "openai", "task_type": "coding", "success": True},
                {"name": "slow-agent", "provider": "anthropic", "task_type": "coding", "success": False},
                {"name": "slow-agent", "provider": "anthropic", "task_type": "coding", "success": False},
            ]
        )

        scores = score_success_probability(
            {"task_type": "coding"},
            [
                {"name": "fast-agent", "provider": "openai", "coding_score": 0.5},
                {"name": "slow-agent", "provider": "anthropic", "coding_score": 0.5},
            ],
            model=model,
        )

        self.assertGreater(scores["fast-agent"], scores["slow-agent"])
        self.assertGreater(scores["fast-agent"], 0.7)
        self.assertLess(scores["slow-agent"], 0.4)

    def test_failure_prediction_training_is_calibrated_and_confidence_weighted(self) -> None:
        model = train_success_model(
            [
                {
                    "name": "kimi-cloud",
                    "provider": "openai-compatible",
                    "provider_type": "ollama-cloud",
                    "model": "kimi:cloud",
                    "task_type": "coding",
                    "language": "python",
                    "success": True,
                    "similarity": 1.0,
                }
                for _ in range(24)
            ]
            + [
                {
                    "name": "cold-cloud",
                    "provider": "openai-compatible",
                    "provider_type": "ollama-cloud",
                    "model": "cold:cloud",
                    "task_type": "coding",
                    "language": "python",
                    "success": False,
                    "similarity": 1.0,
                }
                for _ in range(4)
            ]
        )

        bucket = model["buckets"]["provider_task:kimi-cloud:coding"]
        self.assertEqual(model["version"], 2)
        self.assertGreater(bucket["confidence"], 0.75)
        self.assertIn("smoothed_success_rate", bucket)
        self.assertIn("evidence_strength", bucket)

        scores = score_success_probability(
            {"task_type": "coding", "language": "python"},
            [
                {
                    "name": "kimi-cloud",
                    "provider": "openai-compatible",
                    "provider_type": "ollama-cloud",
                    "model": "kimi:cloud",
                    "coding_score": 0.5,
                },
                {
                    "name": "cold-cloud",
                    "provider": "openai-compatible",
                    "provider_type": "ollama-cloud",
                    "model": "cold:cloud",
                    "coding_score": 0.5,
                },
                {
                    "name": "new-cloud",
                    "provider": "openai-compatible",
                    "provider_type": "ollama-cloud",
                    "model": "new:cloud",
                    "coding_score": 0.5,
                },
            ],
            model=model,
        )

        self.assertGreater(scores["kimi-cloud"] - scores["new-cloud"], 0.15)
        self.assertGreater(scores["new-cloud"] - scores["cold-cloud"], 0.10)

    def test_failure_prediction_ignores_non_finite_training_values(self) -> None:
        model = train_success_model(
            [
                {
                    "name": "steady-agent",
                    "provider": "openai",
                    "task_type": "coding",
                    "success": True,
                    "weight": "nan",
                },
                {
                    "name": "steady-agent",
                    "provider": "openai",
                    "task_type": "coding",
                    "success": True,
                    "similarity": "inf",
                },
            ]
        )

        explanation = explain_success_probability(
            {"task_type": "coding"},
            [{"name": "steady-agent", "provider": "openai", "coding_score": "nan"}],
            model={**model, "prior_success_rate": "inf"},
        )

        selected = explanation["candidates"][0]
        self.assertGreater(selected["success_probability"], 0.5)
        self.assertLess(selected["success_probability"], 0.99)
        self.assertGreater(selected["trained_confidence"], 0.0)

    def test_failure_prediction_trains_provider_type_and_normalized_feedback(self) -> None:
        model = train_success_model(
            [
                {
                    "name": "local-a",
                    "provider": "openai-compatible",
                    "provider_type": "ollama",
                    "task_type": "coding",
                    "success": True,
                    "feedback_rating": " UP ",
                },
                {
                    "name": "local-b",
                    "provider": "openai-compatible",
                    "provider_type": "ollama",
                    "task_type": "coding",
                    "success": False,
                    "feedback_rating": " DOWN ",
                },
            ]
        )

        self.assertIn("provider_task:ollama:coding", model["buckets"])
        self.assertGreater(model["buckets"]["provider_task:local-a:coding"]["attempts"], 1.0)
        self.assertGreater(model["buckets"]["provider_task:local-b:coding"]["attempts"], 1.0)
        self.assertEqual(model["sample_count"], 2)

    def test_failure_prediction_explains_evidence_and_ranking(self) -> None:
        model = train_success_model(
            [
                {
                    "name": "deep-agent",
                    "provider": "openai",
                    "model": "deep-model",
                    "task_type": "coding",
                    "language": "python",
                    "success": True,
                    "similarity": 1.0,
                }
                for _ in range(10)
            ]
            + [
                {
                    "name": "shallow-agent",
                    "provider": "openai",
                    "model": "shallow-model",
                    "task_type": "coding",
                    "language": "python",
                    "success": False,
                    "similarity": 1.0,
                }
                for _ in range(6)
            ]
        )

        explanation = explain_success_probability(
            {
                "task_type": "coding",
                "language": "python",
                "context_tokens": 70000,
                "tests_available": True,
                "public_api_change": True,
            },
            [
                {"name": "shallow-agent", "provider": "openai", "model": "shallow-model", "coding_score": 0.5},
                {"name": "deep-agent", "provider": "openai", "model": "deep-model", "coding_score": 0.5},
            ],
            model=model,
        )
        route = route_by_success_probability(
            {"task_type": "coding", "language": "python"},
            [
                {"name": "shallow-agent", "provider": "openai", "model": "shallow-model", "coding_score": 0.5},
                {"name": "deep-agent", "provider": "openai", "model": "deep-model", "coding_score": 0.5},
            ],
            model=model,
        )

        selected = explanation["candidates"][0]
        self.assertEqual(explanation["object"], "agent_hub.failure_prediction.success_probability_explanation")
        self.assertEqual(explanation["selected"], "deep-agent")
        self.assertEqual(selected["name"], "deep-agent")
        self.assertEqual(selected["evidence_level"], "strong")
        self.assertGreater(selected["trained_confidence"], 0.75)
        self.assertTrue(selected["bucket_matches"])
        self.assertIn("trained_provider_task", [item["name"] for item in selected["adjustments"]])
        self.assertIn("large_context", [item["name"] for item in selected["adjustments"]])
        self.assertTrue(selected["top_reasons"])
        self.assertEqual(route["selected"], "deep-agent")
        self.assertEqual(route["ranking"][0]["name"], "deep-agent")

    def test_benchmark_suite_compares_static_and_adaptive_routing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _router_config(Path(tmp))
            config.expose_routing_details = True
            calls: list[str] = []
            report = BenchmarkSuiteRunner(
                config,
                provider_factory=lambda agent: _Provider(agent, calls),
            ).run(
                route="",
                limit=1,
                tasks=[
                    BenchmarkTask(
                        "latency",
                        "Reply with ok.",
                        ["ok"],
                        route="",
                    )
                ],
            )

            self.assertEqual(report["object"], "agent_hub.benchmark_suite")
            self.assertEqual(report["static_routing"]["task_count"], 1)
            self.assertEqual(report["adaptive_routing"]["task_count"], 1)
            self.assertIn(report["comparison"]["winner"], {"adaptive", "static", "tie"})
            self.assertTrue(Path(report["report_path"]).exists())
            self.assertEqual(calls, ["bad", "bad"])


class _Provider:
    def __init__(self, agent: AgentConfig, calls: list[str]) -> None:
        self.agent = agent
        self.calls = calls

    def complete(self, request: HubRequest) -> ProviderResult:
        self.calls.append(self.agent.name)
        return ProviderResult(text="ok", model=self.agent.model, usage={"prompt_tokens": 1, "completion_tokens": 1})


def _router_config(root: Path) -> HubConfig:
    return HubConfig(
        state_dir=root / "state",
        repo_context_enabled=False,
        automatic_escalation_enabled=False,
        default_route=["bad", "good"],
        agents={
            "bad": AgentConfig(name="bad", provider="openai-compatible", model="bad-test", base_url="http://127.0.0.1:9999"),
            "good": AgentConfig(name="good", provider="openai-compatible", model="good-test", base_url="http://127.0.0.1:9999"),
        },
    )


if __name__ == "__main__":
    unittest.main()
