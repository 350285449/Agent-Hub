from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.adaptive import AdaptiveLearningStore, estimate_known_cost_usd
from agent_hub.config import AgentConfig, HubConfig
from agent_hub.core.router import AgentRouter
from agent_hub.models import HubRequest, ProviderResult
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
        default_route=["bad", "good"],
        agents={
            "bad": AgentConfig(name="bad", provider="openai-compatible", model="bad-test", base_url="http://127.0.0.1:9999"),
            "good": AgentConfig(name="good", provider="openai-compatible", model="good-test", base_url="http://127.0.0.1:9999"),
        },
    )


if __name__ == "__main__":
    unittest.main()
