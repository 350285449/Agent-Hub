from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.core.router import AgentRouter
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.research import (
    BayesianSuccessRouter,
    ContextAblationExperiment,
    ContextFileSignal,
    EpsilonGreedyRouter,
    ModelObjective,
    dominates,
    pareto_frontier,
    select_context_files,
)
from agent_hub.research.datasets import load_jsonl_dataset, write_jsonl_dataset
from agent_hub.research.metrics import load_research_runs, summarize_runs
from agent_hub.research.report import generate_research_report
from agent_hub.research.rl_router import reward
from agent_hub.research.telemetry import ResearchRun, append_research_run, runs_path


class ResearchEngineTests(unittest.TestCase):
    def test_pareto_frontier_filters_dominated_models(self) -> None:
        strong = ModelObjective("strong", quality=0.9, cost=0.1, latency=100)
        dominated = ModelObjective("dominated", quality=0.8, cost=0.2, latency=120)
        cheap = ModelObjective("cheap", quality=0.7, cost=0.01, latency=80)

        self.assertTrue(dominates(strong, dominated))
        self.assertEqual({item.model for item in pareto_frontier([strong, dominated, cheap])}, {"strong", "cheap"})

    def test_bayesian_router_scores_model_task_context(self) -> None:
        router = BayesianSuccessRouter()
        router.record("model-a", "coding", "50%", success=True)
        router.record("model-a", "coding", "50%", success=True)
        router.record("model-b", "coding", "50%", success=False)

        self.assertGreater(
            router.expected_success("model-a", "coding", "50%"),
            router.expected_success("model-b", "coding", "50%"),
        )
        self.assertEqual(
            router.choose(["model-a", "model-b"], "coding", "50%", costs={"model-a": 0.01}),
            "model-a",
        )

    def test_information_context_selects_density_under_budget(self) -> None:
        files = [
            ContextFileSignal("large.py", file_relevance=10, token_count=1000),
            ContextFileSignal("dense.py", file_relevance=4, historical_success_lift=2, token_count=100),
            ContextFileSignal("redundant.py", file_relevance=5, redundancy_score=4, token_count=100),
        ]

        selected = select_context_files(files, token_budget=200)

        self.assertEqual([item.path for item in selected], ["dense.py", "redundant.py"])
        self.assertGreater(selected[0].information_density, files[0].information_density)

    def test_epsilon_greedy_router_records_rewards(self) -> None:
        router = EpsilonGreedyRouter(epsilon=0.0, rng=random.Random(1))
        router.record("model-a", reward(validation_score=0.9, token_cost_penalty=0.1))
        router.record("model-b", reward(validation_score=0.4))

        self.assertEqual(router.choose(["model-a", "model-b"]), "model-a")

    def test_context_ablation_experiment_runs_standard_levels(self) -> None:
        experiment = ContextAblationExperiment(
            lambda task, level: {
                "success": level >= 50,
                "validation_score": level / 100,
                "tokens_used": level * 10,
                "latency_ms": level,
                "cost": level / 1000,
            }
        )

        results = experiment.run({"prompt": "fix tests"})

        self.assertEqual([item.context_percent for item in results], [0, 25, 50, 75, 100])
        self.assertTrue(results[-1].success)

    def test_research_report_generates_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / ".agent-hub" / "state"
            append_research_run(
                state,
                ResearchRun(
                    task_id="r1",
                    task_type="coding",
                    selected_model="m1",
                    candidate_models=["m1", "m2"],
                    input_tokens=100,
                    output_tokens=20,
                    context_token_count=1000,
                    latency_ms=50,
                    cost_estimate=0.01,
                    success=True,
                    validation_score=0.9,
                    event_type="route_outcome",
                ),
            )

            paths = generate_research_report(state)
            summary = summarize_runs(load_research_runs(state))
            self.assertEqual(summary.success_rate, 1.0)
            for path in paths.values():
                self.assertTrue(Path(path).exists(), path)
            self.assertIn("Agent-Hub Research Report", Path(paths["report"]).read_text(encoding="utf-8"))

    def test_dataset_round_trip_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.jsonl"
            write_jsonl_dataset(path, [{"task_id": "a"}, {"task_id": "b"}])

            self.assertEqual([row["task_id"] for row in load_jsonl_dataset(path)], ["a", "b"])

    def test_router_records_research_telemetry_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / ".agent-hub" / "state"
            config = HubConfig(
                state_dir=state,
                debug_echo_enabled=True,
                default_route=["echo"],
                routes=[RouteRule(name="cloud-agent", agents=["echo"])],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="local-echo", free=True)},
            )

            response = AgentRouter(config).route(
                HubRequest(
                    session_id="s",
                    route="cloud-agent",
                    messages=[{"role": "user", "content": "hello"}],
                )
            )
            rows = [json.loads(line) for line in runs_path(state).read_text(encoding="utf-8").splitlines()]

        self.assertEqual(response.model, "local-echo")
        self.assertTrue(any(row["event_type"] == "route_started" for row in rows))
        self.assertTrue(any(row["event_type"] == "route_outcome" and row["success"] is True for row in rows))


if __name__ == "__main__":
    unittest.main()
