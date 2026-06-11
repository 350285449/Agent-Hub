from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.boost import boost_policy, normalize_boost_mode
from agent_hub.config import AgentConfig, HubConfig, config_from_dict, config_to_dict
from agent_hub.core.router import AgentRouter
from agent_hub.core.task_classifier import TaskClassifier
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.output_validator import validate_output
from agent_hub.repository import RepositoryIndexer, RepoContextSelector


class BoostOptimizerTests(unittest.TestCase):
    def test_boost_mode_round_trips_config_and_aliases(self) -> None:
        config = config_from_dict({"boost_mode": "Save Tokens", "agents": []})

        self.assertEqual(config.boost_mode, "save_tokens")
        self.assertEqual(config_to_dict(config)["boost_mode"], "save_tokens")
        self.assertEqual(normalize_boost_mode("Big Refactor"), "big_refactor")
        self.assertEqual(boost_policy("local first").routing_mode, "local_private")

    def test_boost_mode_runtime_selector_options(self) -> None:
        config = HubConfig()

        self.assertEqual(config.boost_mode_label, "Balanced")
        self.assertIn("Best Code", [option["label"] for option in config.boost_mode_options])
        self.assertEqual(config.set_boost_mode("Save Tokens"), "save_tokens")
        self.assertEqual(config.boost_mode_label, "Save Tokens")

    def test_task_classifier_exposes_optimizer_policy_without_breaking_route_type(self) -> None:
        classification = TaskClassifier().classify(
            HubRequest(
                session_id="s",
                messages=[{"role": "user", "content": "Fix the failing parser test in src/router.py."}],
            )
        )
        data = classification.to_dict()

        self.assertEqual(classification.task_type, "debug")
        self.assertEqual(data["optimization_policy"]["task_type"], "bug_fix")
        self.assertEqual(data["context_policy"], "focused_files")
        self.assertEqual(data["model_policy"], "cheap_first")
        self.assertEqual(data["validation_policy"], "run_tests")

    def test_repository_context_ranks_files_and_assigns_context_levels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "router.py").write_text(
                "\n".join(
                    [
                        "import json",
                        "class Router:",
                        "    def route(self, value):",
                        "        return json.loads(value)",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "tests" / "test_router.py").write_text(
                "from src.router import Router\n\ndef test_route():\n    assert Router().route('{}') == {}\n",
                encoding="utf-8",
            )
            (root / "docs.md").write_text("old docs\n", encoding="utf-8")
            index = RepositoryIndexer(root).index()

            selection = RepoContextSelector(index).select(
                'Traceback\n  File "src/router.py", line 3\nFix Router.route and tests/test_router.py',
                max_files=3,
                max_chars=4_000,
                full_files=1,
                compressed_files=1,
                map_files=1,
            )
            payload = selection.to_dict()

        self.assertEqual(payload["selected_files"][0], "src/router.py")
        self.assertIn("tests/test_router.py", payload["selected_files"])
        self.assertEqual(payload["context_levels"]["src/router.py"], "Full")
        self.assertGreaterEqual(payload["tokens_saved"], 0)
        self.assertIn("Matched", payload["reason"])

    def test_output_validator_reports_quality_and_retry_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            result = validate_output(
                request=HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "Fix src/app.py"}],
                ),
                response_text="Fix src/app.py by changing VALUE and adding a test.",
                workspace_dir=root,
                selected_files=["src/app.py"],
                token_usage={"estimated_input_tokens": 120, "max_context_tokens": 100},
            )

        self.assertFalse(result.passed)
        self.assertTrue(result.should_retry)
        self.assertEqual(result.retry_strategy, "compress_prompt")
        self.assertEqual(result.checks["token_budget"], "exceeded")

    def test_router_boost_mode_and_efficiency_scorecards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                workspace_dir=root,
                state_dir=root / "state",
                free_only=False,
                repo_context_enabled=False,
                boost_mode="balanced",
                default_route=["fast", "quality"],
                agents={
                    "fast": AgentConfig(
                        name="fast",
                        provider="openai-compatible",
                        model="fast",
                        base_url="http://127.0.0.1:9999",
                        free=True,
                        speed_score=1.0,
                        coding_score=0.4,
                        context_window=32_000,
                    ),
                    "quality": AgentConfig(
                        name="quality",
                        provider="openai",
                        model="quality",
                        free=False,
                        coding_score=1.0,
                        reasoning_score=1.0,
                        context_window=128_000,
                    ),
                },
            )
            router = AgentRouter(config, provider_factory=_OkProvider)
            decision = router.decide(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "Fix the small bug in src/app.py fast."}],
                    raw={"agent_hub": {"boost_mode": "fast_fix"}},
                )
            )

        self.assertEqual(decision.boost_mode, "fast_fix")
        self.assertEqual(decision.routing_mode, "fastest")
        self.assertIn("route_efficiency", decision.candidate_scores[0])
        self.assertIn("task_policy", decision.to_dict())


class _OkProvider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        return ProviderResult(text="ok", model=self.agent.model)


if __name__ == "__main__":
    unittest.main()
