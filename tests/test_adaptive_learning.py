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
            )
            feedback = store.record_feedback(request_id="hub-1", rating="up", workflow_success=True)
            summary = AdaptiveLearningStore(Path(tmp)).optimization_summary()

            self.assertTrue(feedback["matched"])
            self.assertEqual(summary["workflow_success_rate"]["successes"], 1)
            self.assertEqual(summary["failed_requests_recovered"], 1)
            self.assertGreater(summary["average_known_cost_usd"], 0)

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

            response = AgentRouter(
                config,
                provider_factory=lambda agent: _Provider(agent, calls),
            ).route(HubRequest(session_id="s", messages=[{"role": "user", "content": "fix this code"}]))

            self.assertEqual(response.agent, "good")
            self.assertEqual(calls, ["good"])

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
