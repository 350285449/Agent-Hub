from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .compatibility_v2 import (
    CompatibilityV2Row,
    build_evaluation_datasets,
    calibration_payload,
    compute_non_leaky_features,
    load_cloud_live_rows,
    load_frozen_v1_predictions,
    metrics_payload,
)
from .live_matrix_runner import live_matrix_path
from .prospective_evaluator import prospective_predictions_path
from .telemetry import research_dir


EAC_COMPONENT_DEFINITIONS = {
    "model_capability": (
        "Beta-smoothed prior success rate for the cloud model, computed from prior rows "
        "in time-aware splits and leave-one-out rows in historical splits."
    ),
    "route_reliability": (
        "Beta-smoothed accessible-route prior: 70% model-route prior plus 30% route "
        "prior, using only allowed prior rows. This represents whether raw capability "
        "can actually be reached through the configured provider route."
    ),
    "repository_evidence_accessibility": (
        "Pre-outcome evidence available to the model: 55% normalized context budget, "
        "30% log-scaled prior repository/category exposure count, and 15% category "
        "evidence affordance. It uses no current-row success or validation score."
    ),
    "task_verification_accessibility": (
        "Pre-outcome ease of checking the answer, assigned by task category from a "
        "fixed rubric. Tests and bug fixes are more directly verifiable than open-ended "
        "architecture or research analysis."
    ),
    "eac_score": (
        "model_capability * route_reliability * repository_evidence_accessibility * "
        "task_verification_accessibility."
    ),
}

VERIFICATION_ACCESSIBILITY_BY_CATEGORY = {
    "testing": 0.95,
    "bug_fix": 0.90,
    "security": 0.85,
    "performance": 0.80,
    "api_compatibility": 0.80,
    "refactor": 0.72,
    "documentation": 0.68,
    "repo-analysis": 0.58,
    "repo_analysis": 0.58,
    "architecture": 0.52,
    "research": 0.48,
}

CATEGORY_EVIDENCE_AFFORDANCE = {
    "bug_fix": 0.88,
    "testing": 0.84,
    "refactor": 0.76,
    "security": 0.72,
    "performance": 0.70,
    "api_compatibility": 0.70,
    "documentation": 0.64,
    "repo-analysis": 0.56,
    "repo_analysis": 0.56,
    "architecture": 0.50,
    "research": 0.46,
}


def eac_results_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "eac_theory_results.json"


def run_eac_theory_evaluation(state_dir: str | Path = ".agent-hub") -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = evaluate_eac_theory(state_dir)
    paths = {
        "results_json": eac_results_path(state_dir),
        "eac_theory_report": directory / "eac_theory_report.md",
        "eac_vs_compatibility": directory / "eac_vs_compatibility.md",
        "eac_mechanism_test": directory / "eac_mechanism_test.md",
    }
    paths["results_json"].write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    paths["eac_theory_report"].write_text(eac_theory_report_markdown(payload), encoding="utf-8")
    paths["eac_vs_compatibility"].write_text(eac_vs_compatibility_markdown(payload), encoding="utf-8")
    paths["eac_mechanism_test"].write_text(eac_mechanism_test_markdown(payload), encoding="utf-8")
    return paths


def evaluate_eac_theory(state_dir: str | Path = ".agent-hub") -> dict[str, Any]:
    frozen = load_frozen_v1_predictions(prospective_predictions_path(state_dir))
    live_rows = load_cloud_live_rows(live_matrix_path(state_dir), frozen)
    compatibility_datasets = build_evaluation_datasets(state_dir, live_rows, frozen, _prospective_freeze_time(state_dir))
    datasets = _requested_datasets(compatibility_datasets)
    evaluated: dict[str, Any] = {}
    for name, spec in datasets.items():
        rows = spec["rows"]
        history = spec.get("history", [])
        mode = spec["mode"]
        compatibility_features = compute_non_leaky_features(rows, history=history, mode=mode)
        eac_features = compute_eac_features(rows, history=history, mode=mode)
        evaluated[name] = evaluate_eac_dataset(compatibility_features, eac_features)

    verdict = final_scientific_verdict(evaluated)
    return {
        "object": "agent_hub.research.eac_theory_results",
        "theory": "Execution-Accessible Capability",
        "scope": "cloud_models_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "optimization_policy": "No fitted weights or prediction-first tuning; all combinations are fixed before evaluation.",
        "component_definitions": EAC_COMPONENT_DEFINITIONS,
        "formula": {
            "eac": "model_capability * route_reliability * repository_evidence_accessibility * task_verification_accessibility",
            "eac_plus_compatibility": "0.5 * EAC + 0.5 * Compatibility v2",
        },
        "datasets": evaluated,
        "scientific_verdict": verdict,
    }


def compute_eac_features(
    rows: list[CompatibilityV2Row],
    *,
    history: list[CompatibilityV2Row] | None = None,
    mode: str = "time_aware",
) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=_sort_key)
    base_history = sorted(history or [], key=_sort_key)
    features = []
    if mode == "leave_one_out":
        all_rows = base_history + ordered
        for row in ordered:
            prior_rows = [item for item in all_rows if item.row_id != row.row_id]
            features.append(_eac_feature_row(row, prior_rows, mode))
        return features

    prior_rows = list(base_history)
    for row in ordered:
        features.append(_eac_feature_row(row, prior_rows, mode))
        prior_rows.append(row)
    return features


def evaluate_eac_dataset(
    compatibility_features: list[dict[str, Any]],
    eac_features: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = _merge_feature_rows(compatibility_features, eac_features)
    actual = [row["success"] for row in rows]
    predictions = {
        "Compatibility v1": [row["compatibility_v1_score"] for row in rows],
        "Compatibility v2": [row["compatibility_v2_probability"] for row in rows],
        "EAC": [row["eac_score"] for row in rows],
        "EAC + Compatibility": [row["eac_plus_compatibility"] for row in rows],
    }
    comparisons = {
        name: {
            **metrics_payload(actual, values),
            "calibration": calibration_payload(actual, values),
        }
        for name, values in predictions.items()
    }
    mechanism = {
        "hypothesis_1": high_capability_low_accessibility(rows),
        "hypothesis_2": moderate_capability_high_accessibility(rows),
        "hypothesis_3": route_failures_reduce_accessible_capability(rows),
        "mediation": mediation_analysis(rows),
    }
    return {
        "rows": len(rows),
        "successes": int(sum(actual)),
        "failures": int(len(actual) - sum(actual)),
        "comparisons": comparisons,
        "component_correlations": component_correlations(rows),
        "mechanism_tests": mechanism,
        "sample_rows": _sample_rows(rows),
    }


def high_capability_low_accessibility(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return _empty_hypothesis()
    capability_threshold = _quantile([row["model_capability"] for row in rows], 0.75)
    accessibility_threshold = _quantile([row["accessibility"] for row in rows], 0.25)
    target = [row for row in rows if row["model_capability"] >= capability_threshold and row["accessibility"] <= accessibility_threshold]
    high_capability = [row for row in rows if row["model_capability"] >= capability_threshold]
    target_rate = _success_rate(target)
    comparison_rate = _success_rate(high_capability)
    return {
        "prediction": "High capability with low accessibility should still have low success.",
        "rows": len(target),
        "success_rate": target_rate,
        "comparison_group": "all high-capability rows",
        "comparison_rows": len(high_capability),
        "comparison_success_rate": comparison_rate,
        "effect": round(target_rate - comparison_rate, 6) if target else 0.0,
        "supports_hypothesis": bool(target and target_rate < comparison_rate),
    }


def moderate_capability_high_accessibility(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return _empty_hypothesis()
    low = _quantile([row["model_capability"] for row in rows], 0.40)
    high = _quantile([row["model_capability"] for row in rows], 0.60)
    accessibility_threshold = _quantile([row["accessibility"] for row in rows], 0.75)
    target = [row for row in rows if low <= row["model_capability"] <= high and row["accessibility"] >= accessibility_threshold]
    moderate = [row for row in rows if low <= row["model_capability"] <= high]
    target_rate = _success_rate(target)
    comparison_rate = _success_rate(moderate)
    return {
        "prediction": "Moderate capability with high accessibility should beat moderate capability overall.",
        "rows": len(target),
        "success_rate": target_rate,
        "comparison_group": "all moderate-capability rows",
        "comparison_rows": len(moderate),
        "comparison_success_rate": comparison_rate,
        "effect": round(target_rate - comparison_rate, 6) if target else 0.0,
        "supports_hypothesis": bool(target and target_rate > comparison_rate),
    }


def route_failures_reduce_accessible_capability(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return _empty_hypothesis()
    low_threshold = _quantile([row["route_reliability"] for row in rows], 0.25)
    high_threshold = _quantile([row["route_reliability"] for row in rows], 0.75)
    low_route = [row for row in rows if row["route_reliability"] <= low_threshold]
    high_route = [row for row in rows if row["route_reliability"] >= high_threshold]
    return {
        "prediction": "Low route reliability should lower accessible capability even when raw capability exists.",
        "low_route_rows": len(low_route),
        "high_route_rows": len(high_route),
        "low_route_mean_eac": _mean([row["eac_score"] for row in low_route]),
        "high_route_mean_eac": _mean([row["eac_score"] for row in high_route]),
        "low_route_accessible_capability_loss": _mean([row["model_capability"] - row["eac_score"] for row in low_route]),
        "high_route_accessible_capability_loss": _mean([row["model_capability"] - row["eac_score"] for row in high_route]),
        "low_route_success_rate": _success_rate(low_route),
        "high_route_success_rate": _success_rate(high_route),
        "supports_hypothesis": bool(low_route and high_route and _mean([row["eac_score"] for row in low_route]) < _mean([row["eac_score"] for row in high_route])),
    }


def mediation_analysis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    capability = [row["model_capability"] for row in rows]
    accessibility = [row["accessibility"] for row in rows]
    success = [row["success"] for row in rows]
    cap_to_success = _simple_slope(capability, success)
    cap_to_access = _simple_slope(capability, accessibility)
    success_on_both = _two_predictor_coefficients(capability, accessibility, success)
    access_coef = success_on_both["x2"]
    mediated_effect = cap_to_access * access_coef
    direct_effect = success_on_both["x1"]
    total = cap_to_success
    mediated_share = mediated_effect / total if abs(total) > 1e-9 else 0.0
    return {
        "claim_tested": "Capability -> Accessibility -> Success",
        "capability_success_total_effect": round(total, 6),
        "capability_accessibility_effect": round(cap_to_access, 6),
        "accessibility_success_controlling_capability": round(access_coef, 6),
        "capability_direct_effect_controlling_accessibility": round(direct_effect, 6),
        "estimated_indirect_effect": round(mediated_effect, 6),
        "mediated_share_of_total": round(mediated_share, 6),
        "supports_mediation": bool(cap_to_access > 0 and access_coef > 0 and abs(direct_effect) < abs(total)),
    }


def final_scientific_verdict(datasets: dict[str, Any]) -> dict[str, Any]:
    combined = datasets.get("combined_cloud_dataset", {})
    prospective = datasets.get("prospective", {})

    def metric(dataset: dict[str, Any], model: str, name: str) -> float:
        return float(dataset.get("comparisons", {}).get(model, {}).get(name, 0.0))

    eac_r2_gain = metric(combined, "EAC", "r2") - metric(combined, "Compatibility v2", "r2")
    eac_plus_r2_gain = metric(combined, "EAC + Compatibility", "r2") - metric(combined, "Compatibility v2", "r2")
    eac_brier_gain = metric(combined, "Compatibility v2", "brier_score") - metric(combined, "EAC", "brier_score")
    prospective_failure_gain = metric(prospective, "EAC", "brier_score") < metric(prospective, "Compatibility v2", "brier_score")
    mechanism_support = _mechanism_support_rate(datasets)
    proxy = (
        "Compatibility appears to be a partial proxy for EAC."
        if eac_plus_r2_gain > 0.01 or mechanism_support >= 0.6
        else "Compatibility is not reduced to EAC by these tests."
    )
    if eac_r2_gain > 0.02 and mechanism_support >= 0.6:
        verdict = "EAC supported as a stronger mechanism candidate than Compatibility v2."
    elif eac_plus_r2_gain > 0.02 and mechanism_support >= 0.5:
        verdict = "EAC adds complementary mechanistic signal but does not replace Compatibility."
    elif mechanism_support >= 0.5:
        verdict = "EAC has mechanistic support but weaker predictive fit."
    else:
        verdict = "EAC not supported as a better mechanism on current data."
    return {
        "verdict": verdict,
        "compatibility_proxy_answer": proxy,
        "combined_eac_r2_gain_over_v2": round(eac_r2_gain, 6),
        "combined_eac_plus_r2_gain_over_v2": round(eac_plus_r2_gain, 6),
        "combined_eac_brier_improvement_over_v2": round(eac_brier_gain, 6),
        "eac_better_explains_prospective_failures": bool(prospective_failure_gain),
        "mechanism_support_rate": round(mechanism_support, 6),
        "breakthrough_claim": False,
    }


def component_correlations(rows: list[dict[str, Any]]) -> dict[str, float]:
    success = [row["success"] for row in rows]
    return {
        field: round(_pearson([row[field] for row in rows], success), 6)
        for field in (
            "model_capability",
            "route_reliability",
            "repository_evidence_accessibility",
            "task_verification_accessibility",
            "accessibility",
            "eac_score",
        )
    }


def eac_theory_report_markdown(payload: dict[str, Any]) -> str:
    verdict = payload["scientific_verdict"]
    lines = [
        "# Execution-Accessible Capability Theory",
        "",
        f"- Scope: {payload['scope']}",
        f"- Verdict: {verdict['verdict']}",
        f"- Optimization policy: {payload['optimization_policy']}",
        "",
        "## Operational Definitions",
        "",
    ]
    for name, definition in payload["component_definitions"].items():
        lines.append(f"- `{name}`: {definition}")
    lines.extend(["", "## Dataset Metrics", "", _comparison_table(payload)])
    lines.extend(
        [
            "",
            "## Scientific Verdict",
            "",
            f"- Is Compatibility merely a proxy for EAC? {verdict['compatibility_proxy_answer']}",
            f"- Does EAC explain more variance than Compatibility v2? {verdict['combined_eac_r2_gain_over_v2'] > 0}",
            f"- Does EAC better explain prospective failures? {verdict['eac_better_explains_prospective_failures']}",
            f"- Mechanism support rate: {verdict['mechanism_support_rate']}",
        ]
    )
    return "\n".join(lines) + "\n"


def eac_vs_compatibility_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# EAC vs Compatibility",
        "",
        "This comparison keeps Compatibility v1 and v2 unchanged and treats EAC as a separate theory candidate.",
        "",
        _comparison_table(payload),
        "",
        "## Component Correlations",
        "",
        "| dataset | capability | route | repository evidence | verification | accessibility | EAC |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, data in payload["datasets"].items():
        corr = data["component_correlations"]
        lines.append(
            f"| {name} | {corr['model_capability']:.6f} | {corr['route_reliability']:.6f} | "
            f"{corr['repository_evidence_accessibility']:.6f} | {corr['task_verification_accessibility']:.6f} | "
            f"{corr['accessibility']:.6f} | {corr['eac_score']:.6f} |"
        )
    return "\n".join(lines) + "\n"


def eac_mechanism_test_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# EAC Mechanism Test",
        "",
        "## Hypothesis Summary",
        "",
        "| dataset | H1 high cap low access | H2 moderate cap high access | H3 route failures | mediation |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, data in payload["datasets"].items():
        tests = data["mechanism_tests"]
        lines.append(
            f"| {name} | {tests['hypothesis_1']['supports_hypothesis']} | "
            f"{tests['hypothesis_2']['supports_hypothesis']} | {tests['hypothesis_3']['supports_hypothesis']} | "
            f"{tests['mediation']['supports_mediation']} |"
        )
    lines.extend(["", "## Details", ""])
    for name, data in payload["datasets"].items():
        tests = data["mechanism_tests"]
        lines.extend(
            [
                f"### {name}",
                "",
                f"- H1 effect: {tests['hypothesis_1']['effect']} ({tests['hypothesis_1']['rows']} rows)",
                f"- H2 effect: {tests['hypothesis_2']['effect']} ({tests['hypothesis_2']['rows']} rows)",
                f"- H3 low-route mean EAC: {tests['hypothesis_3']['low_route_mean_eac']}; high-route mean EAC: {tests['hypothesis_3']['high_route_mean_eac']}",
                f"- Mediation indirect effect: {tests['mediation']['estimated_indirect_effect']}; mediated share: {tests['mediation']['mediated_share_of_total']}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def _requested_datasets(datasets: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    historical = datasets.get("historical_pooled", {"rows": [], "history": [], "mode": "leave_one_out"})
    prospective = datasets.get("original_prospective_frozen", {"rows": [], "history": historical.get("rows", []), "mode": "time_aware"})
    phase1 = datasets.get("deconfounded_phase1", {"rows": [], "history": historical.get("rows", []), "mode": "time_aware"})
    phase2 = datasets.get("deconfounded_phase2", {"rows": [], "history": historical.get("rows", []) + phase1.get("rows", []), "mode": "time_aware"})
    combined_rows = _dedupe_rows(historical.get("rows", []) + prospective.get("rows", []) + phase1.get("rows", []) + phase2.get("rows", []))
    return {
        "historical": historical,
        "prospective": prospective,
        "deconfounded_phase1": phase1,
        "deconfounded_phase2": phase2,
        "combined_cloud_dataset": {"rows": combined_rows, "history": [], "mode": "leave_one_out"},
    }


def _eac_feature_row(row: CompatibilityV2Row, prior_rows: list[CompatibilityV2Row], mode: str) -> dict[str, Any]:
    model = _beta_prior(prior_rows, lambda item: item.model == row.model)
    route = _beta_prior(prior_rows, lambda item: _route_key(item) == _route_key(row))
    model_route = _beta_prior(prior_rows, lambda item: item.model == row.model and _route_key(item) == _route_key(row))
    repo_category_count = sum(1 for item in prior_rows if item.repository == row.repository and item.category == row.category)
    model_capability = model["rate"]
    route_reliability = _clip01(0.70 * model_route["rate"] + 0.30 * route["rate"])
    evidence = repository_evidence_accessibility(row, repo_category_count)
    verification = task_verification_accessibility(row.category)
    accessibility = _clip01(route_reliability * evidence * verification)
    eac = _clip01(model_capability * accessibility)
    prior_timestamps = [item.timestamp for item in prior_rows if item.timestamp and row.timestamp]
    return {
        "row_id": row.row_id,
        "success": row.success,
        "model_capability": round(model_capability, 6),
        "route_reliability": round(route_reliability, 6),
        "repository_evidence_accessibility": round(evidence, 6),
        "task_verification_accessibility": round(verification, 6),
        "accessibility": round(accessibility, 6),
        "eac_score": round(eac, 6),
        "model_prior_count": model["count"],
        "route_prior_count": route["count"],
        "model_route_prior_count": model_route["count"],
        "repo_category_prior_count": repo_category_count,
        "prior_excludes_current_row": all(item.row_id != row.row_id for item in prior_rows),
        "future_rows_excluded": mode != "time_aware" or not row.timestamp or all(ts <= row.timestamp for ts in prior_timestamps),
    }


def repository_evidence_accessibility(row: CompatibilityV2Row, repo_category_prior_count: int) -> float:
    context = _context_budget_score(row.context_budget)
    prior_exposure = min(1.0, math.log1p(max(0, repo_category_prior_count)) / math.log(21))
    affordance = CATEGORY_EVIDENCE_AFFORDANCE.get(row.category, 0.60)
    return _clip01(0.55 * context + 0.30 * prior_exposure + 0.15 * affordance)


def task_verification_accessibility(category: str) -> float:
    return VERIFICATION_ACCESSIBILITY_BY_CATEGORY.get(category, 0.60)


def _merge_feature_rows(compatibility: list[dict[str, Any]], eac: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eac_by_id = {row["row_id"]: row for row in eac}
    rows = []
    for row in compatibility:
        eac_row = eac_by_id.get(row["row_id"])
        if not eac_row:
            continue
        merged = {**row, **eac_row}
        merged["eac_plus_compatibility"] = round(_clip01(0.5 * merged["eac_score"] + 0.5 * merged["compatibility_v2_probability"]), 6)
        rows.append(merged)
    return rows


def _comparison_table(payload: dict[str, Any]) -> str:
    lines = [
        "| dataset | model | n | corr | R2 | AUC | calibration | Brier |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for dataset, data in payload["datasets"].items():
        for model_name, metrics in data["comparisons"].items():
            lines.append(
                f"| {dataset} | {model_name} | {data['rows']} | {metrics['correlation']:.6f} | {metrics['r2']:.6f} | "
                f"{metrics['auc']:.6f} | {metrics['calibration_error']:.6f} | {metrics['brier_score']:.6f} |"
            )
    return "\n".join(lines)


def _sample_rows(rows: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    keys = (
        "row_id",
        "success",
        "compatibility_v1_score",
        "compatibility_v2_probability",
        "model_capability",
        "route_reliability",
        "repository_evidence_accessibility",
        "task_verification_accessibility",
        "eac_score",
    )
    return [{key: row.get(key) for key in keys} for row in rows[:limit]]


def _mechanism_support_rate(datasets: dict[str, Any]) -> float:
    flags = []
    for data in datasets.values():
        tests = data.get("mechanism_tests", {})
        for name in ("hypothesis_1", "hypothesis_2", "hypothesis_3"):
            if name in tests:
                flags.append(bool(tests[name].get("supports_hypothesis")))
        if "mediation" in tests:
            flags.append(bool(tests["mediation"].get("supports_mediation")))
    return sum(1 for flag in flags if flag) / len(flags) if flags else 0.0


def _dedupe_rows(rows: Iterable[CompatibilityV2Row]) -> list[CompatibilityV2Row]:
    seen = set()
    deduped = []
    for row in sorted(rows, key=_sort_key):
        if row.row_id in seen:
            continue
        seen.add(row.row_id)
        deduped.append(row)
    return deduped


def _beta_prior(rows: Iterable[CompatibilityV2Row], predicate: Any) -> dict[str, float | int]:
    selected = [row for row in rows if predicate(row)]
    successes = sum(row.success for row in selected)
    count = len(selected)
    return {"rate": (successes + 1.0) / (count + 2.0), "count": count}


def _context_budget_score(value: int) -> float:
    if value <= 0:
        return 0.10
    if value <= 1:
        return 0.25
    if value <= 25:
        return 0.45
    if value <= 50:
        return 0.65
    if value <= 75:
        return 0.82
    return 1.0


def _prospective_freeze_time(state_dir: str | Path) -> datetime | None:
    path = research_dir(state_dir) / "prospective_results.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        parsed = _parse_time(payload.get("freeze_time_utc"))
        if parsed:
            return parsed
    predictions = prospective_predictions_path(state_dir)
    if predictions.exists():
        return datetime.fromtimestamp(predictions.stat().st_mtime, tz=timezone.utc)
    return None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _route_key(row: CompatibilityV2Row) -> str:
    return row.route or row.provider_type or row.provider


def _sort_key(row: CompatibilityV2Row) -> tuple[str, str]:
    return ((row.timestamp or datetime.min.replace(tzinfo=timezone.utc)).isoformat(), row.row_id)


def _empty_hypothesis() -> dict[str, Any]:
    return {"rows": 0, "success_rate": 0.0, "effect": 0.0, "supports_hypothesis": False}


def _success_rate(rows: list[dict[str, Any]]) -> float:
    return round(sum(row["success"] for row in rows) / len(rows), 6) if rows else 0.0


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


def _pearson(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(set(a)) < 2 or len(set(b)) < 2:
        return 0.0
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    den_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
    den_b = math.sqrt(sum((y - mean_b) ** 2 for y in b))
    return numerator / (den_a * den_b) if den_a and den_b else 0.0


def _simple_slope(x: list[float], y: list[float]) -> float:
    if len(x) < 2:
        return 0.0
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    den = sum((value - mean_x) ** 2 for value in x)
    if den == 0:
        return 0.0
    return sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y)) / den


def _two_predictor_coefficients(x1: list[float], x2: list[float], y: list[float]) -> dict[str, float]:
    if len(y) < 3:
        return {"intercept": 0.0, "x1": 0.0, "x2": 0.0}
    mx1 = sum(x1) / len(x1)
    mx2 = sum(x2) / len(x2)
    my = sum(y) / len(y)
    s11 = sum((value - mx1) ** 2 for value in x1)
    s22 = sum((value - mx2) ** 2 for value in x2)
    s12 = sum((a - mx1) * (b - mx2) for a, b in zip(x1, x2))
    sy1 = sum((a - mx1) * (b - my) for a, b in zip(x1, y))
    sy2 = sum((a - mx2) * (b - my) for a, b in zip(x2, y))
    determinant = s11 * s22 - s12 * s12
    if abs(determinant) < 1e-12:
        return {"intercept": my, "x1": 0.0, "x2": 0.0}
    b1 = (sy1 * s22 - sy2 * s12) / determinant
    b2 = (s11 * sy2 - s12 * sy1) / determinant
    intercept = my - b1 * mx1 - b2 * mx2
    return {"intercept": intercept, "x1": b1, "x2": b2}


def _clip01(value: float) -> float:
    return max(0.001, min(0.999, float(value)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Execution-Accessible Capability as a mechanism theory.")
    parser.add_argument("--state-dir", default=".agent-hub", help="Agent-Hub state directory.")
    parser.add_argument("--json", action="store_true", help="Print output paths as JSON.")
    args = parser.parse_args(argv)
    paths = run_eac_theory_evaluation(args.state_dir)
    output = {key: str(value) for key, value in paths.items()}
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        for key, value in output.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EAC_COMPONENT_DEFINITIONS",
    "compute_eac_features",
    "eac_mechanism_test_markdown",
    "eac_results_path",
    "eac_theory_report_markdown",
    "eac_vs_compatibility_markdown",
    "evaluate_eac_dataset",
    "evaluate_eac_theory",
    "repository_evidence_accessibility",
    "run_eac_theory_evaluation",
    "task_verification_accessibility",
]
