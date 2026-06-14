from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.coding_agent_optimizer import compact_prompt, minify_tool_schemas, prepare_codex_prompt
from agent_hub.failure_prediction import predict_failure_risk
from agent_hub.repo_dna import adapt_prompt, repository_prompt_prefix, scan_repository
from agent_hub.routing_memory.recommender import recommend_models
from agent_hub.core.routing.context_router import context_bucket, context_fits_model
from agent_hub.core.routing.cost_router import cost_aware_rank
from agent_hub.core.routing.explanation_builder import build_route_explanation
from agent_hub.core.routing.fallback_router import fallback_candidates


class PhaseOneToSixContractTests(unittest.TestCase):
    def test_repo_dna_detects_stack_and_builds_prompt_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                """
[project]
dependencies = ["fastapi", "pydantic", "pytest", "ruff"]

[tool.ruff]
line-length = 100
""",
                encoding="utf-8",
            )
            (root / "server.py").write_text("from fastapi import Depends\nvalue = Depends(lambda: 1)\n", encoding="utf-8")
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_api.py").write_text("def test_ok(): pass\n", encoding="utf-8")

            profile = scan_repository(root)
            prompt = repository_prompt_prefix(profile)

            self.assertEqual(profile.language, "Python")
            self.assertIn("FastAPI", profile.framework)
            self.assertEqual(profile.test_framework, "pytest")
            self.assertEqual(profile.architecture_pattern, "dependency injection")
            self.assertIn("pydantic", profile.dependencies)
            self.assertIn("Follow the existing style.", prompt)
            self.assertIn("Prefer tests in tests/.", prompt)
            self.assertTrue(adapt_prompt("Fix it", profile).startswith("This repository uses:"))

    def test_routing_memory_recommender_boosts_successful_similar_model(self) -> None:
        pattern = {"task_type": "bug_fix", "language": "python", "framework": "fastapi"}
        rows = [
            {"task_type": "bug_fix", "language": "python", "framework": "fastapi", "model": "claude-sonnet", "success": True, "user_accepted": True},
            {"task_type": "bug_fix", "language": "python", "framework": "fastapi", "model": "claude-sonnet", "success": True},
            {"task_type": "bug_fix", "language": "python", "framework": "fastapi", "model": "gemini-flash", "success": False},
            {"task_type": "refactor", "language": "python", "framework": "fastapi", "model": "gemini-flash", "success": False},
        ]

        recommendations = recommend_models(pattern, rows, ["gemini-flash", "claude-sonnet"])

        self.assertEqual(recommendations[0]["model"], "claude-sonnet")
        self.assertGreater(recommendations[0]["adjustment"], recommendations[1]["adjustment"])
        self.assertTrue(recommendations[0]["reasons"])

    def test_failure_prediction_flags_large_refactor_on_small_model(self) -> None:
        result = predict_failure_risk(
            {
                "task_type": "large_refactor",
                "files_changed": [f"src/file_{index}.py" for index in range(14)],
                "tests_available": False,
            },
            candidate={"model": "gemini-flash", "success_rate": 0.3, "estimated_cost_usd": 0.05},
        )

        self.assertEqual(result["risk"], "high")
        self.assertIn("high_context_risk", result["risk_flags"])
        self.assertIn("low_model_capability_risk", result["risk_flags"])
        self.assertIn("gemini-flash", result["avoid_models"])

    def test_coding_agent_optimizer_compacts_and_reports_savings(self) -> None:
        prompt = "important context\n" + ("middle\n" * 2000) + "final instruction"

        result = compact_prompt(prompt, mode="maximum_savings")
        codex = prepare_codex_prompt(prompt, mode="save_codex_calls")

        self.assertEqual(result["mode"], "maximum_savings")
        self.assertLess(result["optimized_tokens_estimated"], result["original_tokens_estimated"])
        self.assertGreater(result["savings"]["tokens_saved"], 0)
        self.assertEqual(codex["adapter"], "codex")
        self.assertIn("strategy", result)

        schemas = minify_tool_schemas(
            [{"name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string", "examples": ["a"]}}}}]
        )
        self.assertEqual(schemas[0]["parameters"]["properties"]["path"]["type"], "string")

    def test_routing_split_helpers_are_usable(self) -> None:
        scores = [
            {"agent": "slow", "model": "m1", "routing_score": 8, "estimated_cost_usd": 0.40},
            {"agent": "cheap", "model": "m2", "routing_score": 7, "estimated_cost_usd": 0.01},
        ]

        self.assertEqual(context_bucket(25_000), "large")
        self.assertTrue(context_fits_model(1000, 4096, output_tokens=500))
        self.assertEqual(cost_aware_rank(scores)[0]["agent"], "cheap")
        self.assertEqual(fallback_candidates(scores, selected_agent="cheap"), ["slow"])
        explanation = build_route_explanation(selected=scores[0], rejected=[scores[1]], risks={"risk": "low"})
        self.assertEqual(explanation["object"], "agent_hub.routing.explanation")

    def test_phase_five_refactor_modules_exist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        expected = [
            root / "agent_hub" / "core" / "routing" / "provider_filter.py",
            root / "agent_hub" / "core" / "routing" / "model_ranker.py",
            root / "agent_hub" / "core" / "routing" / "context_router.py",
            root / "agent_hub" / "core" / "routing" / "cost_router.py",
            root / "agent_hub" / "core" / "routing" / "fallback_router.py",
            root / "agent_hub" / "core" / "routing" / "explanation_builder.py",
            root / "agent_hub" / "core" / "routing" / "route_trace.py",
            root / "vscode-extension" / "src" / "api" / "client.js",
            root / "vscode-extension" / "src" / "ui" / "dashboard.js",
            root / "vscode-extension" / "src" / "telemetry" / "localMetrics.js",
        ]
        self.assertEqual([str(path) for path in expected if not path.exists()], [])


if __name__ == "__main__":
    unittest.main()
