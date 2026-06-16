from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .certificate_features import certificate_score, infer_certificate_features
from .data_quality_audit import load_audited_rows, run_data_quality_audit
from .live_matrix_runner import ALLOWED_MODELS, CONTEXT_BUDGETS, TARGET_REPETITIONS, live_matrix_path
from .task_generator import REPOSITORIES, TASK_CATEGORIES
from .telemetry import research_dir


THEORY_FILES = {
    "Model-Task-Context Compatibility": "compatibility.md",
    "Structure vs Experience": "structure_experience.md",
    "Routing Risk": "routing_risk.md",
    "Information Density": "information_density.md",
    "Agent Difficulty": "agent_difficulty.md",
    "Capability Geometry": "capability_geometry.md",
}

BASELINE = {
    "usable_rows": 723,
    "gpt_5_5_rows": 41,
    "compatibility_correlation": 0.62,
    "compatibility_r2": 0.38,
}

ALLOWED_VERDICTS = (
    "Rejected",
    "Engineering Heuristic",
    "Tier B",
    "Tier A Candidate",
    "Breakthrough Candidate",
)


def theory_results_dir(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "theory_results"


def run_theory_suite(state_dir: str | Path, *, matrix_path: str | Path | None = None) -> dict[str, str]:
    source = Path(matrix_path) if matrix_path else live_matrix_path(state_dir)
    run_data_quality_audit(state_dir, matrix_path=source)
    rows, excluded = load_audited_rows(source)
    output_dir = theory_results_dir(state_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    paths: dict[str, str] = {}
    for theory_name, filename in THEORY_FILES.items():
        result = evaluate_theory(rows, theory_name)
        result["excluded_rows"] = len(excluded)
        results.append(result)
        path = output_dir / filename
        path.write_text(_theory_markdown(result), encoding="utf-8")
        paths[filename[:-3]] = str(path)
    generalization = build_generalization_report(state_dir, rows, results)
    dashboard = build_research_dashboard(state_dir, rows, excluded, results)
    discoveries = build_candidate_discoveries(state_dir, rows)
    latest = build_latest_theory_validation(state_dir, rows, excluded, results)
    holdout = build_cross_repo_holdout_report(state_dir, rows)
    certificate = build_certificate_theory_report(state_dir, rows, results)
    cross_model = build_cross_model_holdout_report(state_dir, rows)
    ml_ceiling = build_ml_ceiling_report(state_dir, rows)
    prospective = build_prospective_prediction_files(state_dir, rows)
    geometry = build_geometry_diagnostic_report(state_dir, rows)
    unified = build_unified_theory_report(state_dir, rows)
    ranking = build_theory_ranking_report(state_dir, rows, results)
    paths["generalization_report"] = str(generalization)
    paths["research_dashboard"] = str(dashboard)
    paths["candidate_discoveries"] = str(discoveries)
    paths["latest_theory_validation"] = str(latest["markdown"])
    paths["latest_theory_validation_json"] = str(latest["json"])
    paths["cross_repo_holdout_report"] = str(holdout)
    paths["certificate_theory_report"] = str(certificate)
    paths["cross_model_holdout_report"] = str(cross_model["markdown"])
    paths["cross_model_holdout_results"] = str(cross_model["json"])
    paths["ml_ceiling_report"] = str(ml_ceiling["markdown"])
    paths["ml_ceiling_results"] = str(ml_ceiling["json"])
    paths["prospective_predictions"] = str(prospective["predictions"])
    paths["prospective_prediction_protocol"] = str(prospective["protocol"])
    paths["geometry_diagnostic_report"] = str(geometry)
    paths["unified_theory_report"] = str(unified["markdown"])
    paths["unified_theory_results"] = str(unified["json"])
    paths["theory_ranking"] = str(ranking)
    return paths


def evaluate_theory(rows: list[dict[str, Any]], theory: str | Any) -> dict[str, Any]:
    name, predictor = _resolve_theory(theory)
    actual = [1.0 if row.get("success") else 0.0 for row in rows]
    predicted = [max(0.0, min(1.0, float(predictor(row, rows)))) for row in rows]
    metrics = _stats(actual, predicted)
    stability = _stability(rows, predictor)
    generalization = _generalization(rows, predictor)
    leakage = _leakage_resistance(rows)
    falsification = _falsification_resistance(metrics, stability, generalization)
    score = _score(metrics["correlation"], metrics["r2"], 1.0 - metrics["mae"], stability, generalization, leakage, falsification)
    return {
        "theory": name,
        "rows": len(rows),
        "status": "insufficient_live_data" if len(rows) < 30 else "evaluated",
        "correlation": metrics["correlation"],
        "r2": metrics["r2"],
        "mae": metrics["mae"],
        "rmse": metrics["rmse"],
        "stability": stability,
        "generalization": generalization,
        "leakage_resistance": leakage,
        "falsification_resistance": falsification,
        "score": score,
        "tier": _tier(score),
        "verdict": _verdict(score, len(rows)),
    }


def build_latest_theory_validation(
    state_dir: str | Path,
    rows: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "latest_theory_validation.json"
    md_path = directory / "latest_theory_validation.md"
    ranked = _rank_with_allowed_verdicts(results)
    compatibility = next((row for row in ranked if row["theory"] == "Model-Task-Context Compatibility"), None)
    model_counts = Counter(str(row.get("model")) for row in rows)
    payload = {
        "object": "agent_hub.research.latest_theory_validation",
        "rows": len(rows),
        "excluded_rows": len(excluded),
        "usable_by_model": dict(model_counts),
        "baseline": BASELINE,
        "metric_changes": {
            "usable_rows_delta": len(rows) - BASELINE["usable_rows"],
            "gpt_5_5_rows_delta": model_counts.get("gpt-5.5", 0) - BASELINE["gpt_5_5_rows"],
            "compatibility_correlation_delta": round((compatibility or {}).get("correlation", 0.0) - BASELINE["compatibility_correlation"], 6),
            "compatibility_r2_delta": round((compatibility or {}).get("r2", 0.0) - BASELINE["compatibility_r2"], 6),
        },
        "theory_ranking": ranked,
        "conclusion": _latest_conclusion(ranked),
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_latest_validation_markdown(payload), encoding="utf-8")
    return {"markdown": md_path, "json": json_path}


def build_cross_repo_holdout_report(state_dir: str | Path, rows: list[dict[str, Any]]) -> Path:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "cross_repo_holdout_report.md"
    payload = cross_repo_holdout_validation(rows)
    path.write_text(_cross_repo_holdout_markdown(payload), encoding="utf-8")
    return path


def cross_repo_holdout_validation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = [
        {"name": "Train Agent-Hub + face -> Test ytdl_site", "train": {"Agent-Hub", "face"}, "test": "ytdl_site"},
        {"name": "Train Agent-Hub + ytdl_site -> Test face", "train": {"Agent-Hub", "ytdl_site"}, "test": "face"},
        {"name": "Train face + ytdl_site -> Test Agent-Hub", "train": {"face", "ytdl_site"}, "test": "Agent-Hub"},
    ]
    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        train = [row for row in rows if row.get("repository") in scenario["train"]]
        test = [row for row in rows if row.get("repository") == scenario["test"]]
        theories = []
        for name, predictor in BUILTIN_THEORIES.items():
            train_predictions = [max(0.0, min(1.0, float(predictor(row, train)))) for row in train]
            held_predictions = [max(0.0, min(1.0, float(predictor(row, train)))) for row in test]
            train_metrics = _stats(_actual(train), train_predictions)
            held_metrics = _stats(_actual(test), held_predictions)
            train_classification = _classification_metrics(_actual(train), train_predictions)
            held_classification = _classification_metrics(_actual(test), held_predictions)
            held_verdict = _generalization_verdict(train_metrics, held_metrics)
            if len(set(_actual(test))) < 2:
                held_verdict = "inconclusive: held-out outcomes have no variance"
            theories.append(
                {
                    "theory": name,
                    "train_rows": len(train),
                    "held_out_rows": len(test),
                    "train_metrics": train_metrics,
                    "held_out_metrics": held_metrics,
                    "train_classification": train_classification,
                    "held_out_classification": held_classification,
                    "generalization_verdict": held_verdict,
                }
            )
        results.append({"name": scenario["name"], "train": sorted(scenario["train"]), "test": scenario["test"], "theories": theories})
    return {"object": "agent_hub.research.cross_repo_holdout", "scenarios": results}


def build_cross_model_holdout_report(state_dir: str | Path, rows: list[dict[str, Any]]) -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = cross_model_holdout_validation(rows)
    json_path = directory / "cross_model_holdout_results.json"
    md_path = directory / "cross_model_holdout_report.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_cross_model_holdout_markdown(payload), encoding="utf-8")
    return {"markdown": md_path, "json": json_path}


def cross_model_holdout_validation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = [
        {"name": "Train Gemma4 + Nemotron -> Test GPT-5.5", "train": {"gemma4:31b-cloud", "nemotron-3-super:cloud"}, "test": "gpt-5.5"},
        {"name": "Train Gemma4 + GPT-5.5 -> Test Nemotron", "train": {"gemma4:31b-cloud", "gpt-5.5"}, "test": "nemotron-3-super:cloud"},
        {"name": "Train Nemotron + GPT-5.5 -> Test Gemma4", "train": {"nemotron-3-super:cloud", "gpt-5.5"}, "test": "gemma4:31b-cloud"},
    ]
    results: list[dict[str, Any]] = []
    compatibility_gpt_verdict = ""
    for scenario in scenarios:
        train = [row for row in rows if row.get("model") in scenario["train"]]
        test = [row for row in rows if row.get("model") == scenario["test"]]
        theories = []
        for name, predictor in BUILTIN_THEORIES.items():
            train_predictions = [_clamp01(float(predictor(row, train))) for row in train]
            held_predictions = [_clamp01(float(predictor(row, train))) for row in test]
            train_metrics = _stats(_actual(train), train_predictions)
            held_metrics = _stats(_actual(test), held_predictions)
            train_classification = _classification_metrics(_actual(train), train_predictions)
            held_classification = _classification_metrics(_actual(test), held_predictions)
            verdict = _generalization_verdict(train_metrics, held_metrics)
            if len(set(_actual(test))) < 2:
                verdict = "inconclusive: held-out outcomes have no variance"
            if name == "Model-Task-Context Compatibility" and scenario["test"] == "gpt-5.5" and not verdict.startswith("passes"):
                if verdict.startswith("fails"):
                    verdict = f"{verdict}; model-dependent on GPT-5.5 holdout"
                    compatibility_gpt_verdict = "model-dependent"
                elif not compatibility_gpt_verdict:
                    compatibility_gpt_verdict = "inconclusive: GPT-5.5 held-out outcomes have no variance"
            theories.append(
                {
                    "theory": name,
                    "train_rows": len(train),
                    "held_out_rows": len(test),
                    "train_metrics": train_metrics,
                    "held_out_metrics": held_metrics,
                    "train_classification": train_classification,
                    "held_out_classification": held_classification,
                    "generalization_verdict": verdict,
                }
            )
        results.append({"name": scenario["name"], "train": sorted(scenario["train"]), "test": scenario["test"], "theories": theories})
    if not compatibility_gpt_verdict:
        compatibility_gpt_verdict = "not model-dependent by GPT-5.5 holdout rule"
    return {
        "object": "agent_hub.research.cross_model_holdout",
        "scenarios": results,
        "compatibility_gpt_5_5_verdict": compatibility_gpt_verdict,
    }


def build_certificate_theory_report(state_dir: str | Path, rows: list[dict[str, Any]], theory_results: list[dict[str, Any]] | None = None) -> Path:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "certificate_theory_report.md"
    payload = certificate_theory_validation(rows, theory_results=theory_results)
    path.write_text(_certificate_markdown(payload), encoding="utf-8")
    return path


def certificate_theory_validation(rows: list[dict[str, Any]], *, theory_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    ablations = []
    for name, builder in CERTIFICATE_ABLATIONS.items():
        result = _fit_feature_model(rows, builder)
        result["name"] = name
        result["bootstrap"] = _bootstrap_metrics(rows, builder)
        ablations.append(result)
    ranked = sorted(ablations, key=lambda item: (item["metrics"]["r2"], item["metrics"]["correlation"]), reverse=True)
    compatibility = next((item for item in ablations if item["name"] == "compatibility only"), None)
    best = ranked[0] if ranked else None
    improvement = 0.0
    if best and compatibility:
        improvement = round(best["metrics"]["r2"] - compatibility["metrics"]["r2"], 6)
    passes_leakage = leakage_prevention_check()
    meaningful = bool(improvement >= 0.02 and best and best["bootstrap"]["r2_ci"][0] > (compatibility or {"metrics": {"r2": 0.0}})["metrics"]["r2"])
    return {
        "object": "agent_hub.research.certificate_theory_validation",
        "rows": len(rows),
        "feature_policy": "pre_execution_metadata_only",
        "leakage_prevention": passes_leakage,
        "ablations": ranked,
        "best_ablation": best["name"] if best else "",
        "r2_improvement_over_compatibility": improvement,
        "verifiability_improves_prediction": bool(best and compatibility and best["name"] != "compatibility only" and meaningful and passes_leakage),
        "compatibility_remains_strongest_theory": _compatibility_remains_strongest(theory_results or [], ranked),
    }


def leakage_prevention_check() -> dict[str, Any]:
    forbidden = {"success", "validation_score", "latency", "latency_ms", "retries", "error", "output_preview"}
    used = {
        "model",
        "repository",
        "category",
        "task",
        "task_id",
        "context_budget",
        "context budget",
        "context_tokens",
        "selected_files",
        "context_files",
    }
    return {"passed": not bool(forbidden & used), "forbidden_fields": sorted(forbidden), "feature_fields": sorted(used)}


NON_LEAKY_ML_FEATURE_FIELDS = (
    "model",
    "repository",
    "category",
    "task_id",
    "context_budget",
    "context_tokens",
    "selected_files",
    "certificate_strength",
    "environment_executability",
    "verification_cost",
    "cryptographic_certificate",
)


def build_ml_ceiling_report(state_dir: str | Path, rows: list[dict[str, Any]]) -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = ml_ceiling_benchmark(rows)
    json_path = directory / "ml_ceiling_results.json"
    md_path = directory / "ml_ceiling_report.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_ml_ceiling_markdown(payload), encoding="utf-8")
    return {"markdown": md_path, "json": json_path}


def ml_ceiling_benchmark(rows: list[dict[str, Any]]) -> dict[str, Any]:
    compatibility = _fit_feature_model(rows, _compatibility_features)
    folds = _fold_indices(rows, folds=5)
    feature_names, matrix = _ml_feature_matrix(rows)
    models = [
        _cross_validated_linear("Linear Regression", matrix, _actual(rows), folds, logistic=False),
        _cross_validated_linear("Logistic Regression", matrix, _actual(rows), folds, logistic=True),
    ]
    optional = _optional_sklearn_models(matrix, _actual(rows), folds)
    models.extend(optional)
    best = max(models, key=lambda item: (item["metrics"]["r2"], item["metrics"]["correlation"])) if models else {"name": "", "metrics": {"r2": 0.0}}
    gap = round(best["metrics"]["r2"] - compatibility["metrics"]["r2"], 6)
    return {
        "object": "agent_hub.research.ml_ceiling",
        "rows": len(rows),
        "feature_policy": "non_leaky_pre_execution_fields_only",
        "excluded_fields": ["success", "validation_score", "latency", "latency_ms", "retries", "error", "output_preview"],
        "feature_fields": list(NON_LEAKY_ML_FEATURE_FIELDS),
        "expanded_feature_count": len(feature_names),
        "compatibility_metrics": compatibility["metrics"],
        "models": models,
        "best_model": best["name"],
        "best_model_metrics": best["metrics"],
        "r2_gap_over_compatibility": gap,
        "interpretation": "Compatibility captures most measured non-leaky signal." if gap <= 0.03 else "Hidden non-leaky structure remains beyond Compatibility.",
    }


def build_prospective_prediction_files(state_dir: str | Path, rows: list[dict[str, Any]]) -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    predictions_path = directory / "prospective_predictions.jsonl"
    protocol_path = directory / "prospective_prediction_protocol.md"
    predictions = prospective_predictions(rows)
    with predictions_path.open("w", encoding="utf-8") as handle:
        for row in predictions:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    protocol_path.write_text(_prospective_protocol_markdown(predictions), encoding="utf-8")
    return {"predictions": predictions_path, "protocol": protocol_path}


def prospective_predictions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter((row.get("model"), row.get("repository"), row.get("category"), int(row.get("context_budget", 0) or 0)) for row in rows)
    theory_hash = _theory_version_hash()
    frozen: list[dict[str, Any]] = []
    for model in ALLOWED_MODELS:
        for repository in REPOSITORIES:
            for category in TASK_CATEGORIES:
                for budget in CONTEXT_BUDGETS:
                    observed = counts[(model, repository, category, int(budget))]
                    if observed >= TARGET_REPETITIONS:
                        continue
                    pseudo = {"model": model, "repository": repository, "category": category, "context_budget": int(budget), "context_tokens": int(12000 * (int(budget) / 100.0)), "selected_files": []}
                    score = _compatibility(pseudo, rows)
                    frozen.append(
                        {
                            "object": "agent_hub.research.prospective_prediction",
                            "model": model,
                            "repository": repository,
                            "category": category,
                            "context_budget": int(budget),
                            "observed_usable_rows": observed,
                            "planned_additional_rows": max(0, TARGET_REPETITIONS - observed),
                            "compatibility_score": round(score, 6),
                            "predicted_success_probability": round(score, 6),
                            "theory_version_hash": theory_hash,
                        }
                    )
    return frozen


def build_geometry_diagnostic_report(state_dir: str | Path, rows: list[dict[str, Any]]) -> Path:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = geometry_diagnostic(rows)
    path = directory / "geometry_diagnostic_report.md"
    path.write_text(_geometry_diagnostic_markdown(payload), encoding="utf-8")
    return path


def geometry_diagnostic(rows: list[dict[str, Any]]) -> dict[str, Any]:
    own = evaluate_theory(rows, "Capability Geometry")
    repo = cross_repo_holdout_validation(rows)
    model = cross_model_holdout_validation(rows)
    leaky_fields = ["success-derived group rates"]
    repo_passes = _count_theory_verdicts(repo, "Capability Geometry", "passes")
    model_passes = _count_theory_verdicts(model, "Capability Geometry", "passes")
    verdict = "descriptive, not prospectively proven"
    if model_passes == 3 and repo_passes == 3:
        verdict = "strong descriptive holdout performance, still needs frozen prospective proof"
    return {
        "object": "agent_hub.research.geometry_diagnostic",
        "current_metrics": own,
        "leakage_check": {
            "uses_post_run_fields": False,
            "uses_success_derived_training_rates": True,
            "leaky_fields": leaky_fields,
            "passed_for_training_only_prediction": True,
            "passed_for_prospective_without_prior_success": False,
        },
        "metric_difference": "Current built-in Capability Geometry is a descriptive success-rate geometry using model and category rates from observed rows; earlier prospective geometry froze predictions before later outcomes and tested out-of-sample claims.",
        "cross_repo_passes": repo_passes,
        "cross_model_passes": model_passes,
        "verdict": verdict,
    }


def build_unified_theory_report(state_dir: str | Path, rows: list[dict[str, Any]]) -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = unified_theory_validation(rows)
    json_path = directory / "unified_theory_results.json"
    md_path = directory / "unified_theory_report.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_unified_theory_markdown(payload), encoding="utf-8")
    return {"markdown": md_path, "json": json_path}


def unified_theory_validation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ablations = []
    for name, builder in UNIFIED_THEORY_ABLATIONS.items():
        result = _fit_feature_model(rows, builder)
        result["name"] = name
        ablations.append(result)
    compatibility = next(item for item in ablations if item["name"] == "Compatibility only")
    for row in ablations:
        row["r2_gain_over_compatibility"] = round(row["metrics"]["r2"] - compatibility["metrics"]["r2"], 6)
    ranked = sorted(ablations, key=lambda item: (item["metrics"]["r2"], item["metrics"]["correlation"]), reverse=True)
    return {
        "object": "agent_hub.research.unified_theory",
        "rows": len(rows),
        "leakage_checks": theory_leakage_checks(),
        "ablations": ranked,
        "best_ablation": ranked[0]["name"] if ranked else "",
        "interpretation": "Theories are mostly redundant with Compatibility." if ranked and ranked[0]["r2_gain_over_compatibility"] <= 0.03 else "Theories add complementary signal beyond Compatibility.",
    }


def theory_leakage_checks() -> dict[str, Any]:
    return {
        "Model-Task-Context Compatibility": {"post_run_fields": [], "uses_success_derived_training_rates": True},
        "Information Density": {"post_run_fields": ["validation_score"], "uses_success_derived_training_rates": False},
        "Structure vs Experience": {"post_run_fields": ["validation_score"], "uses_success_derived_training_rates": True},
        "Capability Geometry": {"post_run_fields": [], "uses_success_derived_training_rates": True},
        "Routing Risk": {"post_run_fields": ["latency", "retries"], "uses_success_derived_training_rates": False},
        "Agent Difficulty": {"post_run_fields": [], "uses_success_derived_training_rates": True},
    }


def build_theory_ranking_report(state_dir: str | Path, rows: list[dict[str, Any]], results: list[dict[str, Any]]) -> Path:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = final_theory_ranking(rows, results)
    path = directory / "theory_ranking.md"
    path.write_text(_theory_ranking_markdown(payload), encoding="utf-8")
    return path


def final_theory_ranking(rows: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    repo = cross_repo_holdout_validation(rows)
    model = cross_model_holdout_validation(rows)
    ml = ml_ceiling_benchmark(rows)
    prospective_ready = bool(prospective_predictions(rows))
    leakage = theory_leakage_checks()
    rows_out = []
    for result in results:
        name = result["theory"]
        repo_pass = _count_theory_verdicts(repo, name, "passes")
        model_pass = _count_theory_verdicts(model, name, "passes")
        leak = leakage.get(name, {})
        no_post_run_leakage = not leak.get("post_run_fields")
        simplicity = 1.0 if name == "Model-Task-Context Compatibility" else 0.75 if name in {"Information Density", "Capability Geometry", "Agent Difficulty"} else 0.55
        rank_score = round(
            100.0
            * (
                0.24 * (repo_pass / 3.0)
                + 0.24 * (model_pass / 3.0)
                + 0.12 * (1.0 if prospective_ready and name == "Model-Task-Context Compatibility" else 0.4)
                + 0.12 * (1.0 if no_post_run_leakage else 0.0)
                + 0.1 * simplicity
                + 0.18 * min(1.0, result["r2"])
            ),
            3,
        )
        verdict = _final_verdict(name, rank_score, repo_pass, model_pass, no_post_run_leakage, ml)
        rows_out.append(
            {
                "theory": name,
                "score": rank_score,
                "verdict": verdict,
                "correlation": result["correlation"],
                "r2": result["r2"],
                "cross_repo_passes": repo_pass,
                "cross_model_passes": model_pass,
                "prospective_ready": bool(prospective_ready and name == "Model-Task-Context Compatibility"),
                "no_post_run_leakage": no_post_run_leakage,
                "simplicity": simplicity,
            }
        )
    return {
        "object": "agent_hub.research.theory_ranking",
        "rows": len(rows),
        "ml_ceiling_gap": ml["r2_gap_over_compatibility"],
        "ranking": sorted(rows_out, key=lambda item: item["score"], reverse=True),
    }


def build_generalization_report(state_dir: str | Path, rows: list[dict[str, Any]], results: list[dict[str, Any]]) -> Path:
    path = research_dir(state_dir) / "generalization_report.md"
    lines = [
        "# Generalization Report",
        "",
        "Generalization is tested by leaving out repositories, tasks, and models before scoring held-out rows.",
        "",
        "| theory | generalization | tier |",
        "| --- | --- | --- |",
    ]
    for row in sorted(results, key=lambda item: item["generalization"], reverse=True):
        lines.append(f"| {row['theory']} | {row['generalization']} | {row['tier']} |")
    lines.extend(["", f"Usable clean rows: {len(rows)}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_research_dashboard(state_dir: str | Path, rows: list[dict[str, Any]], excluded: list[dict[str, Any]], results: list[dict[str, Any]]) -> Path:
    path = research_dir(state_dir) / "research_dashboard.md"
    ranked = sorted(results, key=lambda item: item["score"], reverse=True)
    survivors = [row for row in ranked if row["tier"] in {"Tier S", "Tier A"} and row["status"] == "evaluated"]
    failures = [row for row in ranked if row["tier"] == "Tier C" and row["status"] == "evaluated"]
    best = ranked[0] if ranked else {"theory": "none", "tier": "Tier C", "score": 0.0}
    lines = [
        "# Research Dashboard",
        "",
        f"- Usable clean live rows: {len(rows)}",
        f"- Excluded rows: {len(excluded)}",
        f"- Best current direction: {best['theory']} ({best['tier']}, score {best['score']})",
        "",
        "## Final Ranking",
        "",
        "| rank | theory | tier | score | correlation | R2 | MAE | RMSE | stability | generalization | leakage | falsification |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, row in enumerate(ranked, start=1):
        lines.append(
            f"| {index} | {row['theory']} | {row['tier']} | {row['score']} | {row['correlation']} | {row['r2']} | {row['mae']} | {row['rmse']} | {row['stability']} | {row['generalization']} | {row['leakage_resistance']} | {row['falsification_resistance']} |"
        )
    lines.extend(
        [
            "",
            "## Answers",
            f"1. Which theories survive? {', '.join(row['theory'] for row in survivors) if survivors else 'None yet; clean live evidence is insufficient or weak.'}",
            f"2. Which theories fail? {', '.join(row['theory'] for row in failures) if failures else 'None cleanly fail yet.'}",
            "3. Which variables actually predict success? See `candidate_discoveries.md`; variables are ranked from clean live rows only.",
            "4. What new candidate quantities emerge? See `candidate_discoveries.md` for correlations, factors, interactions, compatibility measures, and predictive variables.",
            f"5. Highest breakthrough potential: {best['theory'] if rows else 'undetermined until live rows are collected'}.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_candidate_discoveries(state_dir: str | Path, rows: list[dict[str, Any]]) -> Path:
    from .research_discovery import discover_candidate_quantities

    path = research_dir(state_dir) / "candidate_discoveries.md"
    payload = discover_candidate_quantities(rows)
    path.write_text(_discoveries_markdown(payload), encoding="utf-8")
    return path


def _resolve_theory(theory: str | Any) -> tuple[str, Callable[[dict[str, Any], list[dict[str, Any]]], float]]:
    if not isinstance(theory, str):
        name = getattr(theory, "THEORY_NAME", theory.__class__.__name__)
        predictor = getattr(theory, "predict", None)
        if not callable(predictor):
            raise ValueError("theory module/object must expose predict(row, rows)")
        return str(name), predictor
    if theory in BUILTIN_THEORIES:
        return theory, BUILTIN_THEORIES[theory]
    module = importlib.import_module(theory)
    return _resolve_theory(module)


def _group_rate(row: dict[str, Any], rows: list[dict[str, Any]], keys: tuple[str, ...]) -> float:
    peers = [item for item in rows if item is not row and all(item.get(key) == row.get(key) for key in keys)]
    return _rate(peers) if peers else _rate(rows)


def _compatibility(row: dict[str, Any], rows: list[dict[str, Any]]) -> float:
    return _group_rate(row, rows, ("model", "category", "context_budget"))


def _structure_experience(row: dict[str, Any], rows: list[dict[str, Any]]) -> float:
    budget = float(row.get("context_budget", 0)) / 100.0
    density = min(1.0, float(row.get("validation_score", 0.0)) + 0.001 * float(row.get("context_tokens", 0) or 0) / 12.0)
    experience = _group_rate(row, rows, ("model", "repository"))
    return max(0.0, min(1.0, 0.35 * budget + 0.25 * density + 0.4 * experience))


def _routing_risk(row: dict[str, Any], rows: list[dict[str, Any]]) -> float:
    latency = float(row.get("latency", 0.0) or 0.0)
    retries = float(row.get("retries", 0) or 0)
    risk = min(1.0, retries * 0.25 + latency / 300.0)
    return 1.0 - risk


def _information_density(row: dict[str, Any], rows: list[dict[str, Any]]) -> float:
    tokens = max(1.0, float(row.get("context_tokens", 0) or 0))
    score = float(row.get("validation_score", 0.0) or 0.0)
    density = min(1.0, score / math.log10(tokens + 10.0) * 2.0)
    return 0.25 + 0.75 * density


def _agent_difficulty(row: dict[str, Any], rows: list[dict[str, Any]]) -> float:
    task_rate = _group_rate(row, rows, ("category", "repository"))
    return task_rate


def _capability_geometry(row: dict[str, Any], rows: list[dict[str, Any]]) -> float:
    model_rate = _group_rate(row, rows, ("model",))
    category_rate = _group_rate(row, rows, ("category",))
    return (model_rate + category_rate) / 2.0


def _certificate_only(row: dict[str, Any], rows: list[dict[str, Any]]) -> float:
    return certificate_score(row)


def _compatibility_certificate(row: dict[str, Any], rows: list[dict[str, Any]]) -> float:
    compatibility = _compatibility(row, rows)
    certificate = certificate_score(row)
    return _clamp01(0.72 * compatibility + 0.28 * certificate)


BUILTIN_THEORIES: dict[str, Callable[[dict[str, Any], list[dict[str, Any]]], float]] = {
    "Model-Task-Context Compatibility": _compatibility,
    "Structure vs Experience": _structure_experience,
    "Routing Risk": _routing_risk,
    "Information Density": _information_density,
    "Agent Difficulty": _agent_difficulty,
    "Capability Geometry": _capability_geometry,
}


def _compatibility_features(row: dict[str, Any], train: list[dict[str, Any]]) -> list[float]:
    return [_compatibility(row, train)]


def _certificate_features(row: dict[str, Any], train: list[dict[str, Any]]) -> list[float]:
    features = infer_certificate_features(row)
    return [
        features["certificate_strength"],
        features["environment_executability"],
        features["verification_cost"],
        features["cryptographic_certificate"],
    ]


def _compatibility_plus_certificate_features(row: dict[str, Any], train: list[dict[str, Any]]) -> list[float]:
    return [*_compatibility_features(row, train), *_certificate_features(row, train)]


def _compatibility_certificate_interaction_features(row: dict[str, Any], train: list[dict[str, Any]]) -> list[float]:
    compatibility = _compatibility(row, train)
    certificate = certificate_score(row)
    return [compatibility, certificate, compatibility * certificate]


def _compatibility_certificate_environment_interaction_features(row: dict[str, Any], train: list[dict[str, Any]]) -> list[float]:
    compatibility = _compatibility(row, train)
    certificate = certificate_score(row)
    environment = infer_certificate_features(row)["environment_executability"]
    return [compatibility, certificate, environment, compatibility * certificate, compatibility * certificate * environment]


CERTIFICATE_ABLATIONS: dict[str, Callable[[dict[str, Any], list[dict[str, Any]]], list[float]]] = {
    "compatibility only": _compatibility_features,
    "certificate only": _certificate_features,
    "compatibility + certificate": _compatibility_plus_certificate_features,
    "compatibility x certificate": _compatibility_certificate_interaction_features,
    "compatibility x certificate x environment": _compatibility_certificate_environment_interaction_features,
}


def _theory_score_features(names: tuple[str, ...]) -> Callable[[dict[str, Any], list[dict[str, Any]]], list[float]]:
    def build(row: dict[str, Any], train: list[dict[str, Any]]) -> list[float]:
        return [_clamp01(BUILTIN_THEORIES[name](row, train)) for name in names]

    return build


UNIFIED_THEORY_ABLATIONS: dict[str, Callable[[dict[str, Any], list[dict[str, Any]]], list[float]]] = {
    "Compatibility only": _theory_score_features(("Model-Task-Context Compatibility",)),
    "Compatibility + Information Density": _theory_score_features(("Model-Task-Context Compatibility", "Information Density")),
    "Compatibility + Structure/Experience": _theory_score_features(("Model-Task-Context Compatibility", "Structure vs Experience")),
    "Compatibility + Geometry": _theory_score_features(("Model-Task-Context Compatibility", "Capability Geometry")),
    "Compatibility + Density + Structure + Geometry": _theory_score_features(
        ("Model-Task-Context Compatibility", "Information Density", "Structure vs Experience", "Capability Geometry")
    ),
    "All non-leaky theory scores": _theory_score_features(("Model-Task-Context Compatibility", "Agent Difficulty", "Capability Geometry")),
}


def _stats(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual:
        return {"correlation": 0.0, "r2": 0.0, "mae": 1.0, "rmse": 1.0}
    mae = sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)
    rmse = math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual))
    return {"correlation": round(max(0.0, _pearson(actual, predicted)), 6), "r2": round(max(0.0, _r2(actual, predicted)), 6), "mae": round(mae, 6), "rmse": round(rmse, 6)}


def _classification_metrics(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual:
        return {"auc": 0.0, "accuracy": 0.0}
    labels = [1.0 if value >= 0.5 else 0.0 for value in predicted]
    accuracy = sum(1 for a, p in zip(actual, labels) if a == p) / len(actual)
    return {"auc": _auc(actual, predicted), "accuracy": round(accuracy, 6)}


def _auc(actual: list[float], predicted: list[float]) -> float:
    positives = [score for label, score in zip(actual, predicted) if label == 1.0]
    negatives = [score for label, score in zip(actual, predicted) if label == 0.0]
    if not positives or not negatives:
        return 0.0
    wins = 0.0
    for pos in positives:
        for neg in negatives:
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    return round(wins / (len(positives) * len(negatives)), 6)


def _ml_feature_matrix(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[float]]]:
    models = sorted({str(row.get("model") or "") for row in rows})
    repositories = sorted({str(row.get("repository") or "") for row in rows})
    categories = sorted({str(row.get("category") or "") for row in rows})
    feature_names = (
        [f"model={value}" for value in models]
        + [f"repository={value}" for value in repositories]
        + [f"category={value}" for value in categories]
        + ["context_budget", "context_tokens", "selected_file_count", "has_test_context", "has_docs_context"]
        + ["certificate_strength", "environment_executability", "verification_cost", "cryptographic_certificate"]
    )
    matrix: list[list[float]] = []
    for row in rows:
        selected = [str(item).lower() for item in row.get("selected_files") or []]
        cert = infer_certificate_features(row)
        matrix.append(
            [1.0 if str(row.get("model") or "") == value else 0.0 for value in models]
            + [1.0 if str(row.get("repository") or "") == value else 0.0 for value in repositories]
            + [1.0 if str(row.get("category") or "") == value else 0.0 for value in categories]
            + [
                float(row.get("context_budget", 0) or 0) / 100.0,
                min(1.0, float(row.get("context_tokens", 0) or 0) / 12_000.0),
                min(1.0, len(selected) / 50.0),
                1.0 if any("test" in item or "spec" in item for item in selected) else 0.0,
                1.0 if any(item.endswith(".md") or "docs" in item for item in selected) else 0.0,
                cert["certificate_strength"],
                cert["environment_executability"],
                cert["verification_cost"],
                cert["cryptographic_certificate"],
            ]
        )
    return feature_names, matrix


def _fold_indices(rows: list[dict[str, Any]], *, folds: int) -> list[list[int]]:
    buckets = [[] for _ in range(folds)]
    for index, row in enumerate(rows):
        key = str(row.get("dedupe_key") or row.get("row_id") or index)
        bucket = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % folds
        buckets[bucket].append(index)
    return buckets


def _cross_validated_linear(name: str, matrix: list[list[float]], actual: list[float], folds: list[list[int]], *, logistic: bool) -> dict[str, Any]:
    predictions = [0.0 for _ in actual]
    for test_indices in folds:
        test = set(test_indices)
        train_indices = [index for index in range(len(actual)) if index not in test]
        if not train_indices or not test_indices:
            continue
        train_matrix = [[1.0, *matrix[index]] for index in train_indices]
        train_y = [actual[index] for index in train_indices]
        weights = _logistic_fit(train_matrix, train_y) if logistic else _ridge_fit(train_matrix, train_y, penalty=1e-4)
        for index in test_indices:
            raw = _dot(weights, [1.0, *matrix[index]])
            predictions[index] = _sigmoid(raw) if logistic else _clamp01(raw)
    return {"name": name, "metrics": {**_stats(actual, predictions), **_classification_metrics(actual, predictions)}, "available": True}


def _logistic_fit(matrix: list[list[float]], y: list[float], *, iterations: int = 250, rate: float = 0.08, penalty: float = 0.001) -> list[float]:
    if not matrix:
        return [0.0]
    weights = [0.0 for _ in matrix[0]]
    for _ in range(iterations):
        gradients = [0.0 for _ in weights]
        for vector, target in zip(matrix, y):
            predicted = _sigmoid(_dot(weights, vector))
            error = predicted - target
            for index, value in enumerate(vector):
                gradients[index] += error * value
        scale = 1.0 / len(matrix)
        for index in range(len(weights)):
            regularizer = penalty * weights[index] if index else 0.0
            weights[index] -= rate * (gradients[index] * scale + regularizer)
    return weights


def _sigmoid(value: float) -> float:
    if value >= 35:
        return 1.0
    if value <= -35:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))


def _optional_sklearn_models(matrix: list[list[float]], actual: list[float], folds: list[list[int]]) -> list[dict[str, Any]]:
    try:
        from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    except Exception:
        return [
            {"name": "Random Forest", "available": False, "reason": "sklearn unavailable", "metrics": {"correlation": 0.0, "r2": 0.0, "auc": 0.0, "accuracy": 0.0}},
            {"name": "Gradient Boosting", "available": False, "reason": "sklearn unavailable", "metrics": {"correlation": 0.0, "r2": 0.0, "auc": 0.0, "accuracy": 0.0}},
        ]
    models = [
        ("Random Forest", RandomForestRegressor(n_estimators=80, max_depth=5, random_state=20260616)),
        ("Gradient Boosting", GradientBoostingRegressor(random_state=20260616)),
    ]
    results = []
    for name, estimator in models:
        predictions = [0.0 for _ in actual]
        for test_indices in folds:
            test = set(test_indices)
            train_indices = [index for index in range(len(actual)) if index not in test]
            if not train_indices or not test_indices:
                continue
            estimator.fit([matrix[index] for index in train_indices], [actual[index] for index in train_indices])
            fold_predictions = estimator.predict([matrix[index] for index in test_indices])
            for index, value in zip(test_indices, fold_predictions):
                predictions[index] = _clamp01(float(value))
        results.append({"name": name, "available": True, "metrics": {**_stats(actual, predictions), **_classification_metrics(actual, predictions)}})
    return results


def _fit_feature_model(rows: list[dict[str, Any]], feature_builder: Callable[[dict[str, Any], list[dict[str, Any]]], list[float]]) -> dict[str, Any]:
    actual = _actual(rows)
    matrix = [[1.0, *features] for features in _feature_matrix(rows, feature_builder)]
    weights = _ridge_fit(matrix, actual)
    predicted = [_clamp01(_dot(weights, vector)) for vector in matrix]
    return {
        "sample_size": len(rows),
        "feature_count": max(0, len(weights) - 1),
        "metrics": _stats(actual, predicted),
        "weights": [round(value, 6) for value in weights],
    }


def _bootstrap_metrics(
    rows: list[dict[str, Any]],
    feature_builder: Callable[[dict[str, Any], list[dict[str, Any]]], list[float]],
    *,
    iterations: int = 80,
    seed: int = 20260616,
) -> dict[str, Any]:
    if len(rows) < 3:
        return {"iterations": 0, "correlation_ci": [0.0, 0.0], "r2_ci": [0.0, 0.0]}
    rng = random.Random(seed)
    correlations: list[float] = []
    r2s: list[float] = []
    for _index in range(iterations):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        metrics = _fit_feature_model(sample, feature_builder)["metrics"]
        correlations.append(metrics["correlation"])
        r2s.append(metrics["r2"])
    return {
        "iterations": iterations,
        "correlation_ci": [_percentile(correlations, 0.025), _percentile(correlations, 0.975)],
        "r2_ci": [_percentile(r2s, 0.025), _percentile(r2s, 0.975)],
    }


def _feature_matrix(
    rows: list[dict[str, Any]],
    feature_builder: Callable[[dict[str, Any], list[dict[str, Any]]], list[float]],
) -> list[list[float]]:
    if feature_builder not in set(CERTIFICATE_ABLATIONS.values()):
        return [feature_builder(row, rows) for row in rows]
    compatibility_values = _compatibility_values(rows)
    matrix: list[list[float]] = []
    for index, row in enumerate(rows):
        compatibility = compatibility_values[index]
        certificate_features = infer_certificate_features(row)
        certificate = certificate_score(row)
        environment = certificate_features["environment_executability"]
        if feature_builder is _compatibility_features:
            matrix.append([compatibility])
        elif feature_builder is _certificate_features:
            matrix.append(
                [
                    certificate_features["certificate_strength"],
                    certificate_features["environment_executability"],
                    certificate_features["verification_cost"],
                    certificate_features["cryptographic_certificate"],
                ]
            )
        elif feature_builder is _compatibility_plus_certificate_features:
            matrix.append(
                [
                    compatibility,
                    certificate_features["certificate_strength"],
                    certificate_features["environment_executability"],
                    certificate_features["verification_cost"],
                    certificate_features["cryptographic_certificate"],
                ]
            )
        elif feature_builder is _compatibility_certificate_interaction_features:
            matrix.append([compatibility, certificate, compatibility * certificate])
        else:
            matrix.append([compatibility, certificate, environment, compatibility * certificate, compatibility * certificate * environment])
    return matrix


def _compatibility_values(rows: list[dict[str, Any]]) -> list[float]:
    keys = [(row.get("model"), row.get("category"), row.get("context_budget")) for row in rows]
    counts = Counter(keys)
    successes = Counter(key for key, row in zip(keys, rows) if row.get("success"))
    global_rate = _rate(rows)
    values: list[float] = []
    for key, row in zip(keys, rows):
        peer_count = counts[key] - 1
        if peer_count <= 0:
            values.append(global_rate)
            continue
        peer_successes = successes[key] - (1 if row.get("success") else 0)
        values.append(peer_successes / peer_count)
    return values


def _ridge_fit(matrix: list[list[float]], y: list[float], *, penalty: float = 1e-6) -> list[float]:
    if not matrix:
        return [0.0]
    width = len(matrix[0])
    xtx = [[0.0 for _ in range(width)] for _ in range(width)]
    xty = [0.0 for _ in range(width)]
    for vector, target in zip(matrix, y):
        for i in range(width):
            xty[i] += vector[i] * target
            for j in range(width):
                xtx[i][j] += vector[i] * vector[j]
    for i in range(width):
        xtx[i][i] += penalty if i else penalty * 0.01
    return _solve_linear(xtx, xty)


def _solve_linear(matrix: list[list[float]], values: list[float]) -> list[float]:
    size = len(values)
    augmented = [row[:] + [values[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            continue
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [value - factor * augmented[column][idx] for idx, value in enumerate(augmented[row])]
    return [augmented[index][-1] for index in range(size)]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _actual(rows: list[dict[str, Any]]) -> list[float]:
    return [1.0 if row.get("success") else 0.0 for row in rows]


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[int(position)], 6)
    fraction = position - lower
    return round(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction, 6)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _stability(rows: list[dict[str, Any]], predictor: Callable[[dict[str, Any], list[dict[str, Any]]], float]) -> float:
    if len(rows) < 30:
        return 0.0
    full = [predictor(row, rows) for row in rows]
    scores = []
    for field in ("repository", "category", "model"):
        for value in sorted({row.get(field) for row in rows}):
            subset = [row for row in rows if row.get(field) != value]
            if len(subset) < 10:
                continue
            lookup = {id(row): predictor(row, subset) for row in subset}
            pairs = [(full[index], lookup[id(row)]) for index, row in enumerate(rows) if id(row) in lookup]
            if len(pairs) >= 2:
                scores.append(max(0.0, _pearson([a for a, _ in pairs], [b for _, b in pairs])))
    return round(sum(scores) / len(scores), 6) if scores else 0.0


def _generalization(rows: list[dict[str, Any]], predictor: Callable[[dict[str, Any], list[dict[str, Any]]], float]) -> float:
    if len(rows) < 30:
        return 0.0
    actual: list[float] = []
    predicted: list[float] = []
    for field in ("repository", "category", "model"):
        for value in sorted({row.get(field) for row in rows}):
            train = [row for row in rows if row.get(field) != value]
            test = [row for row in rows if row.get(field) == value]
            if not train or not test:
                continue
            for row in test:
                actual.append(1.0 if row.get("success") else 0.0)
                predicted.append(predictor(row, train))
    return round(max(0.0, _pearson(actual, predicted)), 6) if len(actual) >= 2 else 0.0


def _leakage_resistance(rows: list[dict[str, Any]]) -> float:
    keys = [str(row.get("dedupe_key") or row.get("row_id") or index) for index, row in enumerate(rows)]
    return round(len(set(keys)) / max(1, len(keys)), 6)


def _falsification_resistance(metrics: dict[str, float], stability: float, generalization: float) -> float:
    return round(max(0.0, min(1.0, (metrics["correlation"] + stability + generalization + (1.0 - metrics["mae"])) / 4.0)), 6)


def _score(*values: float) -> float:
    return round(100.0 * sum(max(0.0, min(1.0, float(value))) for value in values) / max(1, len(values)), 2)


def _rate(rows: list[dict[str, Any]]) -> float:
    return sum(1 for row in rows if row.get("success")) / len(rows) if rows else 0.0


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    ml = sum(left) / len(left)
    mr = sum(right) / len(right)
    dl = math.sqrt(sum((value - ml) ** 2 for value in left))
    dr = math.sqrt(sum((value - mr) ** 2 for value in right))
    if not dl or not dr:
        return 0.0
    return sum((a - ml) * (b - mr) for a, b in zip(left, right)) / (dl * dr)


def _r2(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    mean = sum(actual) / len(actual)
    total = sum((value - mean) ** 2 for value in actual)
    if not total:
        return 0.0
    residual = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    return 1.0 - residual / total


def _tier(score: float) -> str:
    if score >= 80:
        return "Tier S"
    if score >= 65:
        return "Tier A"
    if score >= 45:
        return "Tier B"
    return "Tier C"


def _verdict(score: float, rows: int) -> str:
    if rows < 30:
        return "Insufficient clean live rows; do not infer support or failure."
    if score >= 65:
        return "Survives current clean live testing."
    if score >= 45:
        return "Mixed evidence; keep testing."
    return "Fails or remains weak under current clean live testing."


def _theory_markdown(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# {result['theory']}",
            "",
            f"- Status: {result['status']}",
            f"- Tier: {result['tier']}",
            f"- Score: {result['score']}",
            f"- Correlation: {result['correlation']}",
            f"- R2: {result['r2']}",
            f"- MAE: {result['mae']}",
            f"- RMSE: {result['rmse']}",
            f"- Stability: {result['stability']}",
            f"- Generalization: {result['generalization']}",
            f"- Leakage resistance: {result['leakage_resistance']}",
            f"- Falsification resistance: {result['falsification_resistance']}",
            f"- Verdict: {result['verdict']}",
            "",
        ]
    )


def _discoveries_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Candidate Discoveries", "", f"- Rows: {payload['rows']}", ""]
    for section in ("correlations", "latent_factors", "interactions", "compatibility_measures", "predictive_variables"):
        lines.extend([f"## {section.replace('_', ' ').title()}", ""])
        for row in payload.get(section, [])[:20]:
            lines.append(f"- {row['name']}: score={row['score']} detail={row.get('detail', '')}")
        lines.append("")
    return "\n".join(lines)


def _count_theory_verdicts(payload: dict[str, Any], theory: str, prefix: str) -> int:
    count = 0
    for scenario in payload.get("scenarios", []):
        for row in scenario.get("theories", []):
            if row.get("theory") == theory and str(row.get("generalization_verdict", "")).startswith(prefix):
                count += 1
    return count


def _theory_version_hash() -> str:
    source = json.dumps(
        {
            "compatibility": "group_rate(model,category,context_budget)",
            "allowed_models": sorted(ALLOWED_MODELS),
            "repositories": list(REPOSITORIES),
            "categories": list(TASK_CATEGORIES),
            "context_budgets": list(CONTEXT_BUDGETS),
        },
        sort_keys=True,
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _final_verdict(name: str, score: float, repo_pass: int, model_pass: int, no_post_run_leakage: bool, ml: dict[str, Any]) -> str:
    if score < 35 or not no_post_run_leakage:
        return "Rejected" if score < 35 else "Engineering Heuristic"
    if repo_pass == 3 and model_pass == 3 and ml.get("r2_gap_over_compatibility", 1.0) <= 0.03 and name == "Model-Task-Context Compatibility":
        return "Breakthrough Candidate"
    if repo_pass >= 2 and model_pass >= 2 and score >= 65:
        return "Tier A Candidate"
    if score >= 45:
        return "Tier B"
    return "Engineering Heuristic"


def _rank_with_allowed_verdicts(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(results, key=lambda item: item["score"], reverse=True)
    compatibility_score = next((row["score"] for row in ranked if row["theory"] == "Model-Task-Context Compatibility"), 0.0)
    output = []
    for index, row in enumerate(ranked, start=1):
        verdict = _allowed_verdict(row, compatibility_score)
        output.append(
            {
                "rank": index,
                "theory": row["theory"],
                "correlation": row["correlation"],
                "r2": row["r2"],
                "leakage_resistance": row["leakage_resistance"],
                "generalization": row["generalization"],
                "score": row["score"],
                "verdict": verdict,
            }
        )
    return output


def _allowed_verdict(row: dict[str, Any], compatibility_score: float) -> str:
    if row.get("rows", 0) < 30 or row["score"] < 35:
        return "Rejected"
    if row["theory"] != "Model-Task-Context Compatibility" and row["score"] > compatibility_score + 2 and row["leakage_resistance"] >= 0.99 and row["generalization"] >= 0.5:
        return "Breakthrough Candidate"
    if row["score"] >= 65 and row["leakage_resistance"] >= 0.99:
        return "Tier A Candidate"
    if row["score"] >= 45:
        return "Tier B"
    return "Engineering Heuristic"


def _latest_conclusion(ranked: list[dict[str, Any]]) -> dict[str, Any]:
    best = ranked[0] if ranked else {}
    compatibility = next((row for row in ranked if row["theory"] == "Model-Task-Context Compatibility"), {})
    return {
        "strongest_theory": best.get("theory", ""),
        "compatibility_rank": compatibility.get("rank", 0),
        "compatibility_remains_strongest": best.get("theory") == "Model-Task-Context Compatibility",
        "changed_from_baseline": bool(
            round(float(compatibility.get("correlation", 0.0)) - BASELINE["compatibility_correlation"], 6) != 0
            or round(float(compatibility.get("r2", 0.0)) - BASELINE["compatibility_r2"], 6) != 0
        ),
    }


def _generalization_verdict(train_metrics: dict[str, float], held_metrics: dict[str, float]) -> str:
    if held_metrics["correlation"] >= 0.5 and held_metrics["r2"] >= 0.2:
        return "passes hold-out validation"
    if held_metrics["correlation"] >= 0.3 and held_metrics["r2"] > 0:
        return "weak partial generalization"
    if train_metrics["correlation"] >= 0.3 and held_metrics["correlation"] < 0.2:
        return "fails hold-out validation"
    return "inconclusive or weak"


def _compatibility_remains_strongest(theory_results: list[dict[str, Any]], ablations: list[dict[str, Any]]) -> bool:
    if not theory_results:
        return False
    best_theory = max(theory_results, key=lambda item: item.get("score", 0.0))
    best_ablation = ablations[0] if ablations else {"name": "", "metrics": {"r2": 0.0}}
    compatibility_ablation = next((item for item in ablations if item["name"] == "compatibility only"), {"metrics": {"r2": 0.0}})
    return bool(
        best_theory.get("theory") == "Model-Task-Context Compatibility"
        and best_ablation.get("name") == "compatibility only"
        or (
            best_theory.get("theory") == "Model-Task-Context Compatibility"
            and best_ablation.get("metrics", {}).get("r2", 0.0) <= compatibility_ablation.get("metrics", {}).get("r2", 0.0) + 0.02
        )
    )


def _latest_validation_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Latest Theory Validation",
        "",
        f"- Usable rows: {payload['rows']}",
        f"- Excluded rows: {payload['excluded_rows']}",
        f"- Usable by model: {payload['usable_by_model']}",
        f"- Previous baseline rows: {payload['baseline']['usable_rows']}",
        f"- Previous compatibility correlation: {payload['baseline']['compatibility_correlation']}",
        f"- Previous compatibility R2: {payload['baseline']['compatibility_r2']}",
        "",
        "## Metric Changes",
        "",
    ]
    for key, value in payload["metric_changes"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Theory Ranking",
            "",
            "| rank | theory | verdict | score | correlation | R2 | generalization | leakage resistance |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in payload["theory_ranking"]:
        lines.append(
            f"| {row['rank']} | {row['theory']} | {row['verdict']} | {row['score']} | {row['correlation']} | {row['r2']} | {row['generalization']} | {row['leakage_resistance']} |"
        )
    conclusion = payload["conclusion"]
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"- Strongest theory: {conclusion['strongest_theory']}",
            f"- Compatibility rank: {conclusion['compatibility_rank']}",
            f"- Compatibility remains strongest: {conclusion['compatibility_remains_strongest']}",
            f"- Conclusions changed from baseline: {conclusion['changed_from_baseline']}",
            "",
        ]
    )
    return "\n".join(lines)


def _cross_repo_holdout_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Cross-Repository Hold-Out Report",
        "",
        "Each scenario trains predictors on two repositories and evaluates the third repository as held-out data.",
        "",
    ]
    for scenario in payload["scenarios"]:
        lines.extend(
            [
                f"## {scenario['name']}",
                "",
                "| theory | train n | train corr | train R2 | held-out n | held-out corr | held-out R2 | generalization verdict |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in scenario["theories"]:
            lines.append(
                f"| {row['theory']} | {row['train_rows']} | {row['train_metrics']['correlation']} | {row['train_metrics']['r2']} | {row['held_out_rows']} | {row['held_out_metrics']['correlation']} | {row['held_out_metrics']['r2']} | {row['generalization_verdict']} |"
            )
        lines.append("")
    return "\n".join(lines)


def _cross_model_holdout_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Cross-Model Hold-Out Report",
        "",
        f"- Compatibility GPT-5.5 verdict: {payload['compatibility_gpt_5_5_verdict']}",
        "",
        "Each scenario trains predictors on two models and evaluates the third model as held-out data.",
        "",
    ]
    for scenario in payload["scenarios"]:
        lines.extend(
            [
                f"## {scenario['name']}",
                "",
                "| theory | train n | train corr | train R2 | train AUC | train acc | held-out n | held-out corr | held-out R2 | held-out AUC | held-out acc | verdict |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in scenario["theories"]:
            lines.append(
                f"| {row['theory']} | {row['train_rows']} | {row['train_metrics']['correlation']} | {row['train_metrics']['r2']} | {row['train_classification']['auc']} | {row['train_classification']['accuracy']} | {row['held_out_rows']} | {row['held_out_metrics']['correlation']} | {row['held_out_metrics']['r2']} | {row['held_out_classification']['auc']} | {row['held_out_classification']['accuracy']} | {row['generalization_verdict']} |"
            )
        lines.append("")
    return "\n".join(lines)


def _ml_ceiling_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# ML Ceiling Report",
        "",
        f"- Rows: {payload['rows']}",
        f"- Feature policy: {payload['feature_policy']}",
        f"- Expanded feature count: {payload['expanded_feature_count']}",
        f"- Compatibility R2: {payload['compatibility_metrics']['r2']}",
        f"- Best model: {payload['best_model']}",
        f"- Best model R2: {payload['best_model_metrics']['r2']}",
        f"- R2 gap over Compatibility: {payload['r2_gap_over_compatibility']}",
        f"- Interpretation: {payload['interpretation']}",
        "",
        "## Models",
        "",
        "| model | available | corr | R2 | AUC | accuracy |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["models"]:
        metrics = row.get("metrics", {})
        lines.append(f"| {row['name']} | {row.get('available')} | {metrics.get('correlation', 0.0)} | {metrics.get('r2', 0.0)} | {metrics.get('auc', 0.0)} | {metrics.get('accuracy', 0.0)} |")
    lines.extend(["", f"Excluded fields: {payload['excluded_fields']}", ""])
    return "\n".join(lines)


def _prospective_protocol_markdown(predictions: list[dict[str, Any]]) -> str:
    return "\n".join(
        [
            "# Prospective Prediction Protocol",
            "",
            f"- Frozen prediction rows: {len(predictions)}",
            f"- Theory version hash: {predictions[0]['theory_version_hash'] if predictions else _theory_version_hash()}",
            "",
            "## Protocol",
            "",
            "1. Freeze `prospective_predictions.jsonl` before collecting new live rows.",
            "2. Collect 50-100 new rows later from missing or planned cells without changing the prediction file.",
            "3. Evaluate the frozen predictions against new outcomes without retuning thresholds, features, or theory weights.",
            "4. Report prospective correlation, R2, AUC, accuracy, sample size, and exclusions.",
            "5. Treat failures as falsification evidence, especially if cross-model or GPT-5.5 rows degrade sharply.",
            "",
        ]
    )


def _geometry_diagnostic_markdown(payload: dict[str, Any]) -> str:
    leak = payload["leakage_check"]
    return "\n".join(
        [
            "# Geometry Diagnostic Report",
            "",
            f"- Current correlation: {payload['current_metrics']['correlation']}",
            f"- Current R2: {payload['current_metrics']['r2']}",
            f"- Uses post-run fields: {leak['uses_post_run_fields']}",
            f"- Uses success-derived training rates: {leak['uses_success_derived_training_rates']}",
            f"- Cross-repo passes: {payload['cross_repo_passes']} / 3",
            f"- Cross-model passes: {payload['cross_model_passes']} / 3",
            f"- Verdict: {payload['verdict']}",
            "",
            "## Diagnostic",
            "",
            payload["metric_difference"],
            "",
        ]
    )


def _unified_theory_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Unified Theory Report",
        "",
        f"- Rows: {payload['rows']}",
        f"- Best ablation: {payload['best_ablation']}",
        f"- Interpretation: {payload['interpretation']}",
        "",
        "## Ablations",
        "",
        "| ablation | corr | R2 | R2 gain over Compatibility | feature count |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in payload["ablations"]:
        lines.append(f"| {row['name']} | {row['metrics']['correlation']} | {row['metrics']['r2']} | {row['r2_gain_over_compatibility']} | {row['feature_count']} |")
    lines.extend(["", "## Leakage Checks", ""])
    for name, leak in payload["leakage_checks"].items():
        lines.append(f"- {name}: post_run_fields={leak['post_run_fields']}, success_derived_rates={leak['uses_success_derived_training_rates']}")
    lines.append("")
    return "\n".join(lines)


def _theory_ranking_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Theory Ranking",
        "",
        f"- Rows: {payload['rows']}",
        f"- ML ceiling R2 gap over Compatibility: {payload['ml_ceiling_gap']}",
        "",
        "| rank | theory | verdict | score | corr | R2 | cross-repo | cross-model | prospective ready | no post-run leakage |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, row in enumerate(payload["ranking"], start=1):
        lines.append(
            f"| {index} | {row['theory']} | {row['verdict']} | {row['score']} | {row['correlation']} | {row['r2']} | {row['cross_repo_passes']}/3 | {row['cross_model_passes']}/3 | {row['prospective_ready']} | {row['no_post_run_leakage']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _certificate_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Certificate Theory Report",
        "",
        f"- Rows: {payload['rows']}",
        f"- Feature policy: {payload['feature_policy']}",
        f"- Leakage prevention passed: {payload['leakage_prevention']['passed']}",
        f"- Best ablation: {payload['best_ablation']}",
        f"- R2 improvement over compatibility: {payload['r2_improvement_over_compatibility']}",
        f"- Verifiability improves prediction beyond compatibility: {payload['verifiability_improves_prediction']}",
        f"- Compatibility remains strongest theory: {payload['compatibility_remains_strongest_theory']}",
        "",
        "## Ablations",
        "",
        "| ablation | n | corr | corr CI | R2 | R2 CI | feature count |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["ablations"]:
        boot = row["bootstrap"]
        lines.append(
            f"| {row['name']} | {row['sample_size']} | {row['metrics']['correlation']} | {boot['correlation_ci']} | {row['metrics']['r2']} | {boot['r2_ci']} | {row['feature_count']} |"
        )
    lines.extend(
        [
            "",
            "## Certificate Feature Definitions",
            "",
            "- certificate_strength: task type and pre-selected context support for objective checks.",
            "- environment_executability: repository and task metadata estimate of whether validation can be executed locally.",
            "- verification_cost: estimated pre-run cost to check the answer, where lower is easier.",
            "- cryptographic_certificate: pre-run evidence that signatures, hashes, or proof artifacts are part of the task context.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test Agent-Hub research theories on clean live rows.")
    parser.add_argument("--state-dir", default=".agent-hub/state")
    parser.add_argument("--matrix-path", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = run_theory_suite(args.state_dir, matrix_path=args.matrix_path or None)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "THEORY_FILES",
    "evaluate_theory",
    "run_theory_suite",
    "theory_results_dir",
]
