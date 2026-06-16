from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_hub.research.data_quality_audit import load_audited_rows, run_data_quality_audit
from agent_hub.research.certificate_features import infer_certificate_features
from agent_hub.research.live_matrix_runner import live_matrix_path, summarize_live_matrix
from agent_hub.research.task_generator import REPOSITORIES, TASK_CATEGORIES, generate_benchmark_tasks, validate_benchmark_tasks
from agent_hub.research.theory_test_harness import (
    build_certificate_theory_report,
    build_cross_model_holdout_report,
    build_cross_repo_holdout_report,
    build_geometry_diagnostic_report,
    build_latest_theory_validation,
    build_ml_ceiling_report,
    build_prospective_prediction_files,
    build_theory_ranking_report,
    build_unified_theory_report,
    cross_model_holdout_validation,
    cross_repo_holdout_validation,
    evaluate_theory,
    geometry_diagnostic,
    leakage_prevention_check,
    ml_ceiling_benchmark,
    prospective_predictions,
    run_theory_suite,
    unified_theory_validation,
)


class ResearchBenchmarkFrameworkTests(unittest.TestCase):
    def test_benchmark_generation_is_balanced(self) -> None:
        tasks = generate_benchmark_tasks(tasks_per_category=10)
        audit = validate_benchmark_tasks(tasks)

        self.assertTrue(audit["balanced"])
        self.assertEqual(audit["task_count"], len(REPOSITORIES) * len(TASK_CATEGORIES) * 10)
        self.assertTrue(all("expected_output_type" in task for task in tasks))

    def test_data_quality_excludes_non_live_and_provider_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / ".agent-hub" / "state"
            path = live_matrix_path(state)
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "dedupe_key": "a",
                    "live": True,
                    "model": "gpt-5.5",
                    "repository": "Agent-Hub",
                    "task": "t1",
                    "category": "testing",
                    "context_budget": 50,
                    "context_tokens": 100,
                    "success": True,
                    "validation_score": 0.8,
                    "latency": 1.0,
                    "retries": 0,
                    "error": "",
                    "provider_type": "codex-cli",
                    "output_preview": "{}",
                },
                {
                    "dedupe_key": "b",
                    "live": True,
                    "model": "gpt-5.5",
                    "repository": "Agent-Hub",
                    "task": "t2",
                    "category": "testing",
                    "context_budget": 50,
                    "context_tokens": 100,
                    "success": False,
                    "validation_score": 0.0,
                    "latency": 0.1,
                    "retries": 0,
                    "error": "401 unauthorized",
                    "provider_type": "codex-cli",
                    "output_preview": "",
                },
                {
                    "dedupe_key": "c",
                    "live": False,
                    "model": "local-model",
                    "repository": "Agent-Hub",
                    "task": "t3",
                    "category": "testing",
                    "context_budget": 50,
                    "error": "",
                    "provider_type": "local-research",
                    "output_preview": "synthetic",
                },
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            usable, excluded = load_audited_rows(path)
            result = run_data_quality_audit(state)

            self.assertEqual(len(usable), 1)
            self.assertEqual({row["excluded_reason"] for row in excluded}, {"auth_failure", "disallowed_model"})
            self.assertTrue(Path(result["data_quality_report"]).exists())

    def test_theory_suite_generates_reports_without_synthetic_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / ".agent-hub" / "state"
            summary = summarize_live_matrix(state)
            paths = run_theory_suite(state)

            self.assertEqual(summary["usable_live_rows"], 0)
            self.assertTrue(Path(summary["live_matrix"]).exists())
            self.assertTrue(Path(paths["research_dashboard"]).exists())
            dashboard = Path(paths["research_dashboard"]).read_text(encoding="utf-8")
            self.assertIn("Usable clean live rows: 0", dashboard)
            self.assertIn("undetermined until live rows are collected", dashboard)

    def test_cross_repo_holdout_validation_reports_each_requested_split(self) -> None:
        rows = _research_rows()

        payload = cross_repo_holdout_validation(rows)

        self.assertEqual(len(payload["scenarios"]), 3)
        self.assertEqual(
            [scenario["test"] for scenario in payload["scenarios"]],
            ["ytdl_site", "face", "Agent-Hub"],
        )
        for scenario in payload["scenarios"]:
            compatibility = next(row for row in scenario["theories"] if row["theory"] == "Model-Task-Context Compatibility")
            self.assertGreater(compatibility["train_rows"], 0)
            self.assertGreater(compatibility["held_out_rows"], 0)
            self.assertIn("generalization_verdict", compatibility)

    def test_certificate_feature_inference_ignores_post_run_outcomes(self) -> None:
        base = _research_rows()[0]
        failed = {**base, "success": False, "validation_score": 0.0, "error": "boom", "output_preview": ""}
        succeeded = {**base, "success": True, "validation_score": 1.0, "error": "", "output_preview": "great"}

        self.assertEqual(infer_certificate_features(failed), infer_certificate_features(succeeded))

    def test_leakage_prevention_check_blocks_outcome_fields(self) -> None:
        result = leakage_prevention_check()

        self.assertTrue(result["passed"])
        self.assertIn("success", result["forbidden_fields"])
        self.assertNotIn("success", result["feature_fields"])

    def test_new_research_reports_are_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / ".agent-hub" / "state"
            rows = _research_rows()
            excluded = [{"excluded_reason": "provider_failure"}]
            results = [evaluate_theory(rows, "Model-Task-Context Compatibility")]

            latest = build_latest_theory_validation(state, rows, excluded, results)
            holdout = build_cross_repo_holdout_report(state, rows)
            certificate = build_certificate_theory_report(state, rows, results)

            self.assertTrue(latest["markdown"].exists())
            self.assertTrue(latest["json"].exists())
            self.assertTrue(holdout.exists())
            self.assertTrue(certificate.exists())
            self.assertIn("Latest Theory Validation", latest["markdown"].read_text(encoding="utf-8"))
            self.assertIn("Cross-Repository Hold-Out Report", holdout.read_text(encoding="utf-8"))
            self.assertIn("Certificate Theory Report", certificate.read_text(encoding="utf-8"))

    def test_cross_model_holdout_uses_disjoint_model_splits(self) -> None:
        payload = cross_model_holdout_validation(_research_rows())

        self.assertEqual(len(payload["scenarios"]), 3)
        for scenario in payload["scenarios"]:
            self.assertNotIn(scenario["test"], scenario["train"])
            self.assertEqual(len(scenario["train"]), 2)
            compatibility = next(row for row in scenario["theories"] if row["theory"] == "Model-Task-Context Compatibility")
            self.assertIn("auc", compatibility["held_out_classification"])
            self.assertGreater(compatibility["held_out_rows"], 0)

    def test_ml_ceiling_excludes_success_derived_features(self) -> None:
        payload = ml_ceiling_benchmark(_research_rows())

        forbidden = {"success", "validation_score", "latency", "latency_ms", "retries", "error", "output_preview"}
        self.assertTrue(forbidden.isdisjoint(payload["feature_fields"]))
        self.assertEqual(set(payload["excluded_fields"]), forbidden)
        self.assertIn("best_model_metrics", payload)

    def test_prospective_predictions_are_generated_for_underfilled_cells(self) -> None:
        rows = _research_rows()
        predictions = prospective_predictions(rows)

        self.assertTrue(predictions)
        sample = predictions[0]
        self.assertIn("compatibility_score", sample)
        self.assertIn("predicted_success_probability", sample)
        self.assertIn("theory_version_hash", sample)

    def test_geometry_diagnostic_flags_success_derived_rates(self) -> None:
        payload = geometry_diagnostic(_research_rows())

        self.assertFalse(payload["leakage_check"]["uses_post_run_fields"])
        self.assertTrue(payload["leakage_check"]["uses_success_derived_training_rates"])
        self.assertIn("verdict", payload)

    def test_unified_theory_output_reports_r2_gain(self) -> None:
        payload = unified_theory_validation(_research_rows())

        self.assertTrue(payload["ablations"])
        self.assertIn("r2_gain_over_compatibility", payload["ablations"][0])
        self.assertIn("leakage_checks", payload)

    def test_new_report_files_are_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / ".agent-hub" / "state"
            rows = _research_rows()
            results = [evaluate_theory(rows, theory) for theory in ("Model-Task-Context Compatibility", "Capability Geometry")]

            cross_model = build_cross_model_holdout_report(state, rows)
            ml = build_ml_ceiling_report(state, rows)
            prospective = build_prospective_prediction_files(state, rows)
            geometry = build_geometry_diagnostic_report(state, rows)
            unified = build_unified_theory_report(state, rows)
            ranking = build_theory_ranking_report(state, rows, results)

            for path in (cross_model["markdown"], cross_model["json"], ml["markdown"], ml["json"], prospective["predictions"], prospective["protocol"], geometry, unified["markdown"], unified["json"], ranking):
                self.assertTrue(path.exists())

def _research_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for repo_index, repository in enumerate(("Agent-Hub", "face", "ytdl_site")):
        for model_index, model in enumerate(("gpt-5.5", "gemma4:31b-cloud", "nemotron-3-super:cloud")):
            for category_index, category in enumerate(("testing", "bug_fix", "documentation")):
                for budget in (0, 50, 100):
                    success = (model_index + category_index + budget // 50 + repo_index) % 3 != 0
                    rows.append(
                        {
                            "dedupe_key": f"{repository}-{model}-{category}-{budget}",
                            "live": True,
                            "model": model,
                            "repository": repository,
                            "task": f"{repository}-{category}",
                            "task_id": f"{repository}-{category}",
                            "category": category,
                            "context_budget": budget,
                            "context_tokens": budget * 20,
                            "selected_files": ["tests/test_example.py"] if category == "testing" else ["README.md"],
                            "success": success,
                            "validation_score": 1.0 if success else 0.0,
                            "latency": 1.0,
                            "retries": 0,
                            "error": "",
                            "provider_type": "codex-cli" if model == "gpt-5.5" else "ollama-cloud",
                            "output_preview": "{}",
                        }
                    )
    return rows


if __name__ == "__main__":
    unittest.main()
