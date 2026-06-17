from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .capability_margin import (
    EPSILON,
    build_capability_margin_dataset,
    retrieval_selectivity_proxy,
    sigmoid,
)
from .compatibility_v2 import calibration_payload, metrics_payload
from .telemetry import research_dir


ACCESS_FILES = {
    "dataset": "compensatory_access_dataset.json",
    "results": "compensatory_access_results.json",
    "report": "compensatory_access_report.md",
    "verdict": "compensatory_access_verdict.md",
    "compensation_matrix": "compensation_matrix.md",
    "bottleneck_vs_surplus": "bottleneck_vs_surplus.md",
    "thresholds": "compensatory_access_thresholds.md",
    "theory_compression": "compensatory_access_theory_compression.md",
}

DEFAULT_WEIGHTS = {
    "K": 1.0,
    "rho": 1.0,
    "A": 1.0,
    "V": 1.0,
    "B": 1.0,
    "D": 1.0,
    "intercept": -2.0,
}

FEATURE_DEFINITIONS = {
    "K": "Capability: copied from the fixed non-leaky Capability Margin feature set.",
    "rho": "Specialization: copied from the fixed non-leaky Capability Margin feature set.",
    "A": "Accessible evidence: copied from the fixed non-leaky Capability Margin feature set.",
    "V": "Verification strength: copied from the fixed non-leaky Capability Margin feature set.",
    "B": "Execution budget: copied from the fixed non-leaky Capability Margin feature set.",
    "D": "Task demand: copied from the fixed non-leaky Capability Margin feature set.",
    "S": "Additive compensatory surplus: K + rho + A + V + B - D with the fixed unit-weight law.",
    "outcome": "Binary success label; never used to define features.",
}


def run_compensatory_access_validation(state_dir: str | Path = ".agent-hub") -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    dataset = build_compensatory_access_dataset(state_dir)
    results = evaluate_compensatory_access(dataset["rows"])
    verdict = final_verdict(results)

    paths = {key: directory / filename for key, filename in ACCESS_FILES.items()}
    paths["dataset"].write_text(json.dumps(dataset, indent=2, sort_keys=True), encoding="utf-8")
    paths["results"].write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    paths["report"].write_text(report_markdown(dataset, results), encoding="utf-8")
    paths["verdict"].write_text(verdict_markdown(verdict), encoding="utf-8")
    paths["compensation_matrix"].write_text(compensation_matrix_markdown(results["compensation"]), encoding="utf-8")
    paths["bottleneck_vs_surplus"].write_text(bottleneck_vs_surplus_markdown(results["bottleneck_vs_surplus"]), encoding="utf-8")
    paths["thresholds"].write_text(thresholds_markdown(results["thresholds"]), encoding="utf-8")
    paths["theory_compression"].write_text(theory_compression_markdown(results["theory_compression"]), encoding="utf-8")
    return paths


def build_compensatory_access_dataset(state_dir: str | Path = ".agent-hub") -> dict[str, Any]:
    margin = build_capability_margin_dataset(state_dir)
    rows = [compensatory_row(row) for row in margin["rows"]]
    return {
        "object": "agent_hub.research.compensatory_access_dataset",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "cloud_models_only",
        "policy": {
            "compatibility_v1_frozen": True,
            "compatibility_v2_frozen": True,
            "eac_frozen": True,
            "route_friction_frozen": True,
            "retrieval_selectivity_frozen": True,
            "capability_margin_artifacts_modified": False,
            "existing_datasets_modified": False,
            "existing_predictions_modified": False,
            "feature_source": "capability_margin_v1_fixed_non_leaky_features",
            "weights": "fixed unit weights; no outcome-tuned feature definitions",
        },
        "weights": DEFAULT_WEIGHTS,
        "feature_definitions": FEATURE_DEFINITIONS,
        "row_count": len(rows),
        "rows": rows,
    }


def compensatory_row(row: dict[str, Any]) -> dict[str, Any]:
    k = float(row["K"])
    rho = float(row["rho"])
    a = float(row["A"])
    v = float(row["V"])
    b = float(row["B"])
    d = float(row["D"])
    surplus = additive_surplus(k, rho, a, v, b, d)
    product_margin = math.log((k * rho * a * v * b) + EPSILON) - math.log(d + EPSILON)
    return {
        "row_id": row["row_id"],
        "dataset": row["dataset"],
        "model": row.get("model", ""),
        "provider": row.get("provider", ""),
        "route": row.get("route", ""),
        "repository": row.get("repository", ""),
        "category": row.get("category", ""),
        "context_budget": row.get("context_budget", 0),
        "K": round(k, 6),
        "rho": round(rho, 6),
        "A": round(a, 6),
        "V": round(v, 6),
        "B": round(b, 6),
        "D": round(d, 6),
        "S": round(surplus, 6),
        "additive_surplus_probability": round(sigmoid(surplus + DEFAULT_WEIGHTS["intercept"]), 6),
        "multiplicative_margin": round(product_margin, 6),
        "multiplicative_margin_probability": round(sigmoid(product_margin), 6),
        "minimum_bottleneck_score": round(min(k, rho, a, v, b) - d, 6),
        "minimum_bottleneck_probability": round(sigmoid(4.0 * (min(k, rho, a, v, b) - d)), 6),
        "max_rescue_score": round(max(k, rho, a, v, b) - d, 6),
        "max_rescue_probability": round(sigmoid(4.0 * (max(k, rho, a, v, b) - d)), 6),
        "pairwise_compensation_score": round(pairwise_compensation(k, rho, a, v, b, d), 6),
        "pairwise_compensation_probability": round(sigmoid(pairwise_compensation(k, rho, a, v, b, d) - 1.0), 6),
        "outcome": float(row["outcome"]),
        "compatibility_v1": float(row.get("compatibility_v1", 0.5)),
        "compatibility_v2": float(row.get("compatibility_v2", 0.5)),
        "eac": float(row.get("eac", 0.5)),
        "route_friction": float(row.get("route_friction", 0.5)),
        "retrieval_selectivity": float(row.get("retrieval_selectivity", retrieval_selectivity_proxy(a, row.get("context_budget", 0)))),
        "non_leaky": bool(row.get("non_leaky", False)),
        "source_feature_definition_version": row.get("feature_definition_version", ""),
        "feature_definition_version": "compensatory_access_v1_fixed_unit_weights",
    }


def additive_surplus(k: float, rho: float, a: float, v: float, b: float, d: float) -> float:
    return k + rho + a + v + b - d


def pairwise_compensation(k: float, rho: float, a: float, v: float, b: float, d: float) -> float:
    return (k * rho) + (k * a) + (rho * a) + (a * v) + (v * b) - d


def evaluate_compensatory_access(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = _dataset_groups(rows)
    laws = {dataset: compare_laws(items) for dataset, items in groups.items()}
    compensation = compensation_structure(groups)
    bottleneck = bottleneck_vs_surplus(groups)
    thresholds = threshold_search(groups)
    compression = theory_compression(groups.get("combined", rows))
    falsification = falsification_tests(laws, compensation, bottleneck, compression)
    return {
        "object": "agent_hub.research.compensatory_access_results",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "laws": laws,
        "compensation": compensation,
        "bottleneck_vs_surplus": bottleneck,
        "thresholds": thresholds,
        "theory_compression": compression,
        "falsification": falsification,
    }


def compare_laws(rows: list[dict[str, Any]]) -> dict[str, Any]:
    actual = [row["outcome"] for row in rows]
    predictions = {
        "A_multiplicative_margin": [row["multiplicative_margin_probability"] for row in rows],
        "B_additive_surplus": [row["additive_surplus_probability"] for row in rows],
        "C_minimum_bottleneck": [row["minimum_bottleneck_probability"] for row in rows],
        "D_max_rescue": [row["max_rescue_probability"] for row in rows],
        "E_pairwise_compensation": [row["pairwise_compensation_probability"] for row in rows],
        "model_identity_K_only": [row["K"] for row in rows],
        "Compatibility_v2": [row["compatibility_v2"] for row in rows],
    }
    metrics = {name: metrics_payload(actual, values) for name, values in predictions.items()}
    calibration = {name: calibration_payload(actual, values) for name, values in predictions.items()}
    candidate_names = [name for name in predictions if name[:2] in {"A_", "B_", "C_", "D_", "E_"}]
    best_auc = max(candidate_names, key=lambda name: metrics[name]["auc"]) if candidate_names else ""
    best_brier = min(candidate_names, key=lambda name: metrics[name]["brier_score"]) if candidate_names else ""
    best_overall_brier = min(metrics, key=lambda name: metrics[name]["brier_score"]) if metrics else ""
    return {
        "rows": len(rows),
        "success_rate": round(_mean(actual), 6),
        "metrics": metrics,
        "calibration": calibration,
        "best_by_auc": best_auc,
        "best_by_brier": best_brier,
        "best_overall_by_brier_including_falsification_baselines": best_overall_brier,
    }


def compensation_structure(groups: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    combined = groups.get("combined", [])
    pairs = {
        "high_rho_rescues_low_A": ("rho", "A"),
        "high_K_rescues_low_V": ("K", "V"),
        "high_A_rescues_low_K": ("A", "K"),
        "high_V_rescues_low_B": ("V", "B"),
        "high_B_rescues_low_V": ("B", "V"),
    }
    matrix = {name: rescue_effect(combined, rescuer, weak) for name, (rescuer, weak) in pairs.items()}
    by_dataset = {
        dataset: {name: rescue_effect(rows, rescuer, weak) for name, (rescuer, weak) in pairs.items()}
        for dataset, rows in groups.items()
        if dataset != "combined"
    }
    variable_limits = {name: low_variable_limit(combined, name) for name in ("K", "rho", "A", "V", "B", "D")}
    dominance = demand_dominance(combined)
    stable = compensation_stability(matrix, by_dataset)
    return {
        "matrix": matrix,
        "by_dataset": by_dataset,
        "variable_limits": variable_limits,
        "demand_dominance": dominance,
        "stable_compensation_patterns": stable,
        "non_compensable_variables": [
            variable for variable, payload in variable_limits.items() if payload["hard_bottleneck_evidence"]
        ],
    }


def rescue_effect(rows: list[dict[str, Any]], rescuer: str, weak: str) -> dict[str, Any]:
    if len(rows) < 4:
        return _empty_rescue(rescuer, weak)
    rescuer_high = _quantile([row[rescuer] for row in rows], 0.75)
    rescuer_low = _quantile([row[rescuer] for row in rows], 0.25)
    weak_low = _quantile([row[weak] for row in rows], 0.25)
    rescued = [row for row in rows if row[weak] <= weak_low and row[rescuer] >= rescuer_high]
    unrescued = [row for row in rows if row[weak] <= weak_low and row[rescuer] <= rescuer_low]
    normal = [row for row in rows if row[weak] > weak_low]
    lift = _success_rate(rescued) - _success_rate(unrescued)
    exists = len(rescued) >= 5 and len(unrescued) >= 5 and lift >= 0.10
    return {
        "rescuer": rescuer,
        "weak_component": weak,
        "rescued_rows": len(rescued),
        "unrescued_rows": len(unrescued),
        "rescued_success_rate": round(_success_rate(rescued), 6),
        "unrescued_success_rate": round(_success_rate(unrescued), 6),
        "baseline_without_weak_component_rows": len(normal),
        "baseline_without_weak_component_success_rate": round(_success_rate(normal), 6),
        "lift": round(lift, 6),
        "compensation_exists": exists,
    }


def low_variable_limit(rows: list[dict[str, Any]], variable: str) -> dict[str, Any]:
    if len(rows) < 4:
        return {"low_threshold": 0.0, "low_rows": 0, "best_rescued_success_rate": 0.0, "hard_bottleneck_evidence": False}
    if variable == "D":
        threshold = _quantile([row[variable] for row in rows], 0.75)
        vulnerable = [row for row in rows if row[variable] >= threshold]
        direction = "high"
    else:
        threshold = _quantile([row[variable] for row in rows], 0.25)
        vulnerable = [row for row in rows if row[variable] <= threshold]
        direction = "low"
    other_vars = [name for name in ("K", "rho", "A", "V", "B") if name != variable]
    rescued_rates = []
    for other in other_vars:
        high = _quantile([row[other] for row in rows], 0.75)
        rescued_rates.append(_success_rate([row for row in vulnerable if row.get(other, 0.0) >= high]))
    best = max(rescued_rates + [0.0])
    return {
        "risk_direction": direction,
        "threshold": round(threshold, 6),
        "rows": len(vulnerable),
        "success_rate": round(_success_rate(vulnerable), 6),
        "best_rescued_success_rate": round(best, 6),
        "hard_bottleneck_evidence": len(vulnerable) >= 10 and best < 0.45,
    }


def demand_dominance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcome = [row["outcome"] for row in rows]
    correlations = {name: round(_corr([row[name] for row in rows], outcome), 6) for name in ("K", "rho", "A", "V", "B", "D", "S")}
    strongest = max(correlations, key=lambda name: abs(correlations[name])) if correlations else ""
    high_d = _quantile([row["D"] for row in rows], 0.75) if rows else 0.0
    high_d_rows = [row for row in rows if row["D"] >= high_d]
    return {
        "correlations_with_success": correlations,
        "strongest_variable": strongest,
        "high_D_threshold": round(high_d, 6),
        "high_D_success_rate": round(_success_rate(high_d_rows), 6),
        "D_dominates_everything": strongest == "D" and correlations.get("D", 0.0) < 0.0,
    }


def compensation_stability(matrix: dict[str, Any], by_dataset: dict[str, dict[str, Any]]) -> bool:
    stable = 0
    checked = 0
    for name, combined in matrix.items():
        if not combined["compensation_exists"]:
            continue
        checked += 1
        supporting = sum(1 for dataset in by_dataset.values() if dataset.get(name, {}).get("lift", 0.0) > 0.0)
        if supporting >= 2:
            stable += 1
    return checked == 0 or stable / checked >= 0.5


def bottleneck_vs_surplus(groups: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    output = {}
    for dataset, rows in groups.items():
        actual = [row["outcome"] for row in rows]
        weakest = [min(row["K"], row["rho"], row["A"], row["V"], row["B"]) - row["D"] for row in rows]
        surplus = [row["S"] for row in rows]
        weakest_metrics = metrics_payload(actual, _rank01(weakest))
        surplus_metrics = metrics_payload(actual, [row["additive_surplus_probability"] for row in rows])
        failures = [row for row in rows if row["outcome"] <= 0.0]
        weak_failures = [row for row in failures if min(row["K"], row["rho"], row["A"], row["V"], row["B"]) <= _quantile([r[min_variable(r)] for r in rows], 0.25)]
        surplus_failures = [row for row in failures if row["S"] <= _quantile(surplus, 0.25)]
        output[dataset] = {
            "weakest_component_auc": weakest_metrics["auc"],
            "weakest_component_brier": weakest_metrics["brier_score"],
            "additive_surplus_auc": surplus_metrics["auc"],
            "additive_surplus_brier": surplus_metrics["brier_score"],
            "failure_rows": len(failures),
            "failures_explained_by_weak_component": len(weak_failures),
            "failures_explained_by_low_surplus": len(surplus_failures),
            "verdict": "surplus" if surplus_metrics["auc"] >= weakest_metrics["auc"] and surplus_metrics["brier_score"] <= weakest_metrics["brier_score"] else "bottleneck",
        }
    return output


def threshold_search(groups: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {dataset: surplus_threshold_summary(rows) for dataset, rows in groups.items()}


def surplus_threshold_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"bins": [], "best_threshold": None, "max_success_jump": 0.0, "threshold_evidence": False}
    values = [row["S"] for row in rows]
    candidates = sorted(set(_quantile(values, q / 10.0) for q in range(1, 10)))
    best = None
    best_jump = 0.0
    for threshold in candidates:
        low = [row for row in rows if row["S"] < threshold]
        high = [row for row in rows if row["S"] >= threshold]
        if len(low) < 5 or len(high) < 5:
            continue
        jump = _success_rate(high) - _success_rate(low)
        if abs(jump) > abs(best_jump):
            best_jump = jump
            best = threshold
    bins = []
    for index in range(5):
        low = _quantile(values, index / 5.0)
        high = _quantile(values, (index + 1) / 5.0)
        bucket = [row for row in rows if low <= row["S"] <= high] if index == 4 else [row for row in rows if low <= row["S"] < high]
        bins.append({"bin": f"q{index + 1}", "low": round(low, 6), "high": round(high, 6), "rows": len(bucket), "success_rate": round(_success_rate(bucket), 6)})
    return {
        "bins": bins,
        "best_threshold": round(best, 6) if best is not None else None,
        "max_success_jump": round(best_jump, 6),
        "threshold_evidence": best is not None and abs(best_jump) >= 0.25,
    }


def theory_compression(rows: list[dict[str, Any]]) -> dict[str, Any]:
    components = ("K", "rho", "A", "V", "B", "D", "S")
    theories = {
        "Compatibility v2": "compatibility_v2",
        "EAC": "eac",
        "Route Friction": "route_friction",
        "Retrieval Selectivity": "retrieval_selectivity",
        "Capability Margin": "multiplicative_margin_probability",
    }
    mapping = {}
    for theory, field in theories.items():
        correlations = {component: round(_corr([row[component] for row in rows], [row[field] for row in rows]), 6) for component in components}
        best = max(correlations, key=lambda name: abs(correlations[name])) if correlations else ""
        mapping[theory] = {
            "best_component": best,
            "best_correlation": correlations.get(best, 0.0),
            "component_correlations": correlations,
            "collapses_into_additive_surplus": abs(correlations.get("S", 0.0)) >= 0.85,
        }
    return {
        "theory_mapping": mapping,
        "collapsed_theories": [name for name, payload in mapping.items() if payload["collapses_into_additive_surplus"]],
        "is_just_compatibility_v2": abs(mapping.get("Compatibility v2", {}).get("component_correlations", {}).get("S", 0.0)) >= 0.90,
    }


def falsification_tests(
    laws: dict[str, Any],
    compensation: dict[str, Any],
    bottleneck: dict[str, Any],
    compression: dict[str, Any],
) -> dict[str, Any]:
    killed = []
    combined = laws.get("combined", {}).get("metrics", {})
    additive = combined.get("B_additive_surplus", {})
    multiplicative = combined.get("A_multiplicative_margin", {})
    simpler = {name: metrics for name, metrics in combined.items() if name in {"C_minimum_bottleneck", "D_max_rescue", "model_identity_K_only"}}
    if additive.get("brier_score", 1.0) >= multiplicative.get("brier_score", 1.0) and additive.get("auc", 0.0) <= multiplicative.get("auc", 0.0):
        killed.append("does_not_outperform_multiplicative_margin")
    for dataset in ("prospective", "deconfounded_phase1", "deconfounded_phase2"):
        metrics = laws.get(dataset, {}).get("metrics", {}).get("B_additive_surplus", {})
        if laws.get(dataset, {}).get("rows", 0) and (metrics.get("auc", 0.0) < 0.60 or metrics.get("brier_score", 1.0) > 0.30):
            killed.append(f"fails_{dataset}")
    if any(m.get("brier_score", 1.0) <= additive.get("brier_score", 1.0) + 0.005 and m.get("auc", 0.0) >= additive.get("auc", 0.0) for m in simpler.values()):
        killed.append("dominated_by_simpler_theory")
    if not compensation.get("stable_compensation_patterns", False):
        killed.append("compensation_patterns_unstable")
    if compression.get("is_just_compatibility_v2"):
        killed.append("reduces_to_compatibility_v2")
    if combined.get("model_identity_K_only", {}).get("brier_score", 1.0) <= additive.get("brier_score", 1.0) + 0.005:
        killed.append("reduces_to_model_identity")
    return {
        "status": "KILLED" if killed else "SURVIVES",
        "tier": "killed" if killed else ("Tier A" if additive.get("auc", 0.0) >= 0.80 and compensation.get("stable_compensation_patterns", False) else "Tier B"),
        "kill_reasons": killed,
        "best_law_combined_auc": laws.get("combined", {}).get("best_by_auc", ""),
        "best_law_combined_brier": laws.get("combined", {}).get("best_by_brier", ""),
        "bottleneck_vs_surplus_combined": bottleneck.get("combined", {}).get("verdict", ""),
    }


def final_verdict(results: dict[str, Any]) -> dict[str, Any]:
    laws = results["laws"].get("combined", {})
    metrics = laws.get("metrics", {})
    additive = metrics.get("B_additive_surplus", {})
    multiplicative = metrics.get("A_multiplicative_margin", {})
    compensation = results["compensation"]
    matrix = compensation["matrix"]
    return {
        "does_additive_surplus_outperform_multiplicative_margin": additive.get("brier_score", 1.0) < multiplicative.get("brier_score", 1.0) or additive.get("auc", 0.0) > multiplicative.get("auc", 0.0),
        "does_compensation_exist": any(row["compensation_exists"] for row in matrix.values()),
        "compensating_pairs": [name for name, row in matrix.items() if row["compensation_exists"]],
        "hard_bottlenecks": compensation["non_compensable_variables"],
        "is_just_compatibility_v2": results["theory_compression"]["is_just_compatibility_v2"],
        "best_law": laws.get("best_by_brier", ""),
        "bottleneck_vs_surplus": results["bottleneck_vs_surplus"].get("combined", {}).get("verdict", ""),
        "scientific_status": results["falsification"]["tier"],
        "kill_reasons": results["falsification"]["kill_reasons"],
    }


def report_markdown(dataset: dict[str, Any], results: dict[str, Any]) -> str:
    lines = [
        "# Compensatory Access Theory",
        "",
        f"- Scope: {dataset['scope']}",
        f"- Rows: {dataset['row_count']}",
        f"- Status: `{results['falsification']['status']}` / `{results['falsification']['tier']}`",
        "- Policy: isolated theory; no existing theory, dataset, prediction, or Capability Margin artifact was modified.",
        "",
        "## Feature Definitions",
        "",
        *[f"- `{key}`: {value}" for key, value in dataset["feature_definitions"].items()],
        "",
        "## Law Comparison",
        "",
    ]
    for dataset_name, payload in results["laws"].items():
        lines.extend([f"### {dataset_name}", "", "| law | AUC | Brier | calibration | pseudo-R2 | correlation |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
        for law, metrics in payload["metrics"].items():
            lines.append(f"| {law} | {metrics['auc']:.6f} | {metrics['brier_score']:.6f} | {metrics['calibration_error']:.6f} | {metrics['pseudo_r2']:.6f} | {metrics['correlation']:.6f} |")
        lines.append("")
    return "\n".join(lines)


def verdict_markdown(verdict: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Compensatory Access Verdict",
            "",
            f"1. Does additive surplus outperform multiplicative Margin? {verdict['does_additive_surplus_outperform_multiplicative_margin']}.",
            f"2. Does compensation exist? {verdict['does_compensation_exist']}.",
            f"3. Which variables compensate? {', '.join(verdict['compensating_pairs']) or 'none detected'}.",
            f"4. Which variables are hard bottlenecks? {', '.join(verdict['hard_bottlenecks']) or 'none under the strict rescue test'}.",
            f"5. Is this just Compatibility v2? {verdict['is_just_compatibility_v2']}.",
            f"6. Best law: `{verdict['best_law']}`.",
            f"7. Bottleneck vs surplus verdict: `{verdict['bottleneck_vs_surplus']}`.",
            f"8. Scientific status: `{verdict['scientific_status']}`.",
            "",
            "## Kill Reasons",
            "",
            *([f"- {reason}" for reason in verdict["kill_reasons"]] or ["- None triggered."]),
            "",
        ]
    )


def compensation_matrix_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Compensation Matrix",
        "",
        "| question | rescued success | unrescued success | lift | compensation? |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for name, row in payload["matrix"].items():
        lines.append(f"| {name} | {row['rescued_success_rate']:.6f} | {row['unrescued_success_rate']:.6f} | {row['lift']:.6f} | `{row['compensation_exists']}` |")
    lines.extend(
        [
            "",
            f"- Does D dominate everything? `{payload['demand_dominance']['D_dominates_everything']}`.",
            f"- Non-compensable variables: {', '.join(payload['non_compensable_variables']) or 'none under strict test'}.",
            f"- Stable compensation patterns: `{payload['stable_compensation_patterns']}`.",
            "",
        ]
    )
    return "\n".join(lines)


def bottleneck_vs_surplus_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Bottleneck vs Surplus", "", "| dataset | weakest AUC | surplus AUC | weakest Brier | surplus Brier | verdict |", "| --- | ---: | ---: | ---: | ---: | --- |"]
    for dataset, row in payload.items():
        lines.append(f"| {dataset} | {row['weakest_component_auc']:.6f} | {row['additive_surplus_auc']:.6f} | {row['weakest_component_brier']:.6f} | {row['additive_surplus_brier']:.6f} | `{row['verdict']}` |")
    lines.append("")
    return "\n".join(lines)


def thresholds_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Compensatory Access Thresholds", ""]
    for dataset, row in payload.items():
        lines.extend([f"## {dataset}", "", f"- Best S threshold: `{row['best_threshold']}`", f"- Max success jump: `{row['max_success_jump']}`", f"- Threshold evidence: `{row['threshold_evidence']}`", ""])
    return "\n".join(lines)


def theory_compression_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Compensatory Access Theory Compression", "", "| theory | best component | corr(best) | corr(S) | collapses into S? |", "| --- | --- | ---: | ---: | --- |"]
    for theory, row in payload["theory_mapping"].items():
        lines.append(f"| {theory} | {row['best_component']} | {row['best_correlation']:.6f} | {row['component_correlations']['S']:.6f} | `{row['collapses_into_additive_surplus']}` |")
    lines.extend(["", f"- Is this just Compatibility v2? `{payload['is_just_compatibility_v2']}`.", ""])
    return "\n".join(lines)


def min_variable(row: dict[str, Any]) -> str:
    return min(("K", "rho", "A", "V", "B"), key=lambda name: row[name])


def _dataset_groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["dataset"])].append(row)
    combined = []
    seen = set()
    for row in rows:
        if row["row_id"] in seen:
            continue
        seen.add(row["row_id"])
        combined.append({**row, "dataset": "combined"})
    grouped["combined"] = combined
    return dict(grouped)


def _empty_rescue(rescuer: str, weak: str) -> dict[str, Any]:
    return {
        "rescuer": rescuer,
        "weak_component": weak,
        "rescued_rows": 0,
        "unrescued_rows": 0,
        "rescued_success_rate": 0.0,
        "unrescued_success_rate": 0.0,
        "baseline_without_weak_component_rows": 0,
        "baseline_without_weak_component_success_rate": 0.0,
        "lift": 0.0,
        "compensation_exists": False,
    }


def _rank01(values: list[float]) -> list[float]:
    if not values:
        return []
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [0.0] * len(values)
    denom = max(1, len(values) - 1)
    for rank, (_value, index) in enumerate(ordered):
        ranks[index] = rank / denom
    return ranks


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def _success_rate(rows: list[dict[str, Any]]) -> float:
    return _mean(row["outcome"] for row in rows)


def _mean(values: Iterable[float]) -> float:
    materialized = [float(value) for value in values]
    return sum(materialized) / len(materialized) if materialized else 0.0


def _corr(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(set(a)) < 2 or len(set(b)) < 2:
        return 0.0
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    den_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
    den_b = math.sqrt(sum((y - mean_b) ** 2 for y in b))
    return numerator / (den_a * den_b) if den_a and den_b else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Compensatory Access Theory against cloud research rows.")
    parser.add_argument("--state-dir", default=".agent-hub", help="Agent-Hub state directory.")
    parser.add_argument("--json", action="store_true", help="Print output paths as JSON.")
    args = parser.parse_args(argv)
    paths = run_compensatory_access_validation(args.state_dir)
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
    "ACCESS_FILES",
    "DEFAULT_WEIGHTS",
    "additive_surplus",
    "build_compensatory_access_dataset",
    "compare_laws",
    "compensatory_row",
    "evaluate_compensatory_access",
    "pairwise_compensation",
    "run_compensatory_access_validation",
    "surplus_threshold_summary",
]
