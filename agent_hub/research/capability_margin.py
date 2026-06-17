from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
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
from .eac_theory import compute_eac_features
from .live_matrix_runner import live_matrix_path
from .prospective_evaluator import prospective_predictions_path
from .telemetry import research_dir


EPSILON = 1e-6
MARGIN_FILES = {
    "dataset": "capability_margin_dataset.json",
    "results": "capability_margin_results.json",
    "report": "capability_margin_report.md",
    "theory_graph": "capability_margin_theory_graph.md",
    "novelty": "capability_margin_novelty.md",
    "verdict": "capability_margin_verdict.md",
}

TASK_DEMAND_BY_CATEGORY = {
    "testing": 0.42,
    "bug_fix": 0.48,
    "api_compatibility": 0.56,
    "documentation": 0.58,
    "refactor": 0.62,
    "performance": 0.66,
    "security": 0.70,
    "repo-analysis": 0.74,
    "repo_analysis": 0.74,
    "architecture": 0.82,
    "research": 0.86,
}

FEATURE_DEFINITIONS = {
    "K": "Model capability: Beta-smoothed prior success rate for this model. Historical split uses leave-one-out; prospective/deconfounded splits use only earlier cloud rows.",
    "rho": "Specialization: Beta-smoothed prior success rate for this model and task category, computed with the same non-leaky history rule.",
    "A": "Accessible evidence: EAC repository_evidence_accessibility, a fixed pre-outcome mix of context budget, prior repo/category exposure, and category evidence affordance.",
    "V": "Verification strength: fixed category-level task_verification_accessibility from the EAC rubric.",
    "B": "Execution budget: fixed context-budget score from the row context budget; higher values mean more execution/context budget available before outcome.",
    "D": "Task demand: fixed category demand, increased when there is little prior repository/category exposure. It uses category and prior-count metadata only.",
    "M": "Capability Margin: log(K * rho * A * V * B + epsilon) - log(D + epsilon).",
    "outcome": "Binary success label, used only as the target after all features are computed.",
}


def capability_margin_dataset_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / MARGIN_FILES["dataset"]


def run_capability_margin_validation(state_dir: str | Path = ".agent-hub") -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    dataset = build_capability_margin_dataset(state_dir)
    results = evaluate_capability_margin(dataset["rows"])
    graph = theory_graph(results)
    novelty = novelty_analysis()
    verdict = final_verdict(results)

    paths = {key: directory / filename for key, filename in MARGIN_FILES.items()}
    paths["dataset"].write_text(json.dumps(dataset, indent=2, sort_keys=True), encoding="utf-8")
    paths["results"].write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    paths["report"].write_text(report_markdown(dataset, results), encoding="utf-8")
    paths["theory_graph"].write_text(theory_graph_markdown(graph), encoding="utf-8")
    paths["novelty"].write_text(novelty_markdown(novelty), encoding="utf-8")
    paths["verdict"].write_text(verdict_markdown(verdict), encoding="utf-8")
    return paths


def build_capability_margin_dataset(state_dir: str | Path = ".agent-hub") -> dict[str, Any]:
    frozen = load_frozen_v1_predictions(prospective_predictions_path(state_dir))
    live_rows = load_cloud_live_rows(live_matrix_path(state_dir), frozen)
    split_specs = build_evaluation_datasets(state_dir, live_rows, frozen, _prospective_freeze_time(state_dir))
    requested = _requested_datasets(split_specs)
    rows = []
    for dataset_name, spec in requested.items():
        if dataset_name == "combined":
            continue
        feature_rows = compute_margin_features(spec["rows"], history=spec.get("history", []), mode=spec["mode"], dataset_name=dataset_name)
        rows.extend(feature_rows)
    return {
        "object": "agent_hub.research.capability_margin_dataset",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "cloud_models_only",
        "policy": {
            "compatibility_v1_frozen": True,
            "compatibility_v2_frozen": True,
            "eac_frozen": True,
            "route_friction_frozen": True,
            "retrieval_selectivity_frozen": True,
            "existing_datasets_modified": False,
            "existing_predictions_modified": False,
            "optimization_policy": "No fitted weights or threshold tuning; all candidate laws are fixed transforms.",
        },
        "epsilon": EPSILON,
        "feature_definitions": FEATURE_DEFINITIONS,
        "row_count": len(rows),
        "rows": rows,
    }


def compute_margin_features(
    rows: list[CompatibilityV2Row],
    *,
    history: list[CompatibilityV2Row] | None = None,
    mode: str = "time_aware",
    dataset_name: str,
) -> list[dict[str, Any]]:
    compatibility = compute_non_leaky_features(rows, history=history, mode=mode)
    eac = compute_eac_features(rows, history=history, mode=mode)
    eac_by_id = {row["row_id"]: row for row in eac}
    original_by_id = {row.row_id: row for row in rows}
    output = []
    for c in compatibility:
        e = eac_by_id.get(c["row_id"])
        original = original_by_id.get(c["row_id"])
        if not e or not original:
            continue
        k = _clip01(e["model_capability"])
        rho = _clip01(c["task_category_condition"])
        a = _clip01(e["repository_evidence_accessibility"])
        v = _clip01(e["task_verification_accessibility"])
        b = execution_budget_score(original.context_budget)
        d = task_demand(original.category, int(e.get("repo_category_prior_count", 0) or 0))
        product = k * rho * a * v * b
        margin = math.log(product + EPSILON) - math.log(d + EPSILON)
        output.append(
            {
                "row_id": c["row_id"],
                "dataset": dataset_name,
                "model": c["model"],
                "provider": c.get("provider", ""),
                "route": c["route"],
                "repository": original.repository,
                "category": c["category"],
                "context_budget": original.context_budget,
                "K": round(k, 6),
                "rho": round(rho, 6),
                "A": round(a, 6),
                "V": round(v, 6),
                "B": round(b, 6),
                "D": round(d, 6),
                "M": round(margin, 6),
                "capability_margin_probability": round(sigmoid(margin), 6),
                "numerator": round(product, 9),
                "outcome": c["success"],
                "compatibility_v1": c["compatibility_v1_score"],
                "compatibility_v2": c["compatibility_v2_probability"],
                "eac": e["eac_score"],
                "route_friction": e["route_reliability"],
                "retrieval_selectivity": retrieval_selectivity_proxy(a, original.context_budget),
                "prior_counts": {
                    "model": e.get("model_prior_count", 0),
                    "model_route": e.get("model_route_prior_count", 0),
                    "repo_category": e.get("repo_category_prior_count", 0),
                },
                "non_leaky": bool(c["prior_excludes_current_row"] and c["future_rows_excluded"] and e["prior_excludes_current_row"] and e["future_rows_excluded"]),
                "feature_definition_version": "capability_margin_v1_fixed_no_fit",
            }
        )
    return output


def evaluate_capability_margin(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = _dataset_groups(rows)
    comparisons = {}
    for dataset, items in groups.items():
        comparisons[dataset] = compare_predictors(items)
    transitions = {dataset: phase_transition_summary(items) for dataset, items in groups.items()}
    alternatives = {dataset: compare_alternative_laws(items) for dataset, items in groups.items()}
    compression = compression_analysis(groups.get("combined", rows))
    conserved = conserved_quantity_search(groups.get("combined", rows))
    falsification = falsification_tests(comparisons, transitions, alternatives, compression)
    return {
        "object": "agent_hub.research.capability_margin_results",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "comparisons": comparisons,
        "phase_transitions": transitions,
        "alternative_laws": alternatives,
        "theory_compression": compression,
        "conserved_quantities": conserved,
        "falsification": falsification,
    }


def compare_predictors(rows: list[dict[str, Any]]) -> dict[str, Any]:
    predictors = {
        "Compatibility v1": "compatibility_v1",
        "Compatibility v2": "compatibility_v2",
        "EAC": "eac",
        "Route Friction": "route_friction",
        "Retrieval Selectivity": "retrieval_selectivity",
        "Capability Margin": "capability_margin_probability",
    }
    actual = [row["outcome"] for row in rows]
    return {name: metrics_payload(actual, [row[field] for row in rows]) for name, field in predictors.items()}


def compare_alternative_laws(rows: list[dict[str, Any]]) -> dict[str, Any]:
    actual = [row["outcome"] for row in rows]
    predictions = {
        "M_log_product_minus_demand": [row["capability_margin_probability"] for row in rows],
        "M1_additive": [sigmoid(row["K"] + row["rho"] + row["A"] + row["V"] + row["B"] - row["D"] - 2.0) for row in rows],
        "M2_ratio": [sigmoid(math.log((row["numerator"] + EPSILON) / (row["D"] + EPSILON))) for row in rows],
        "M3_min_bottleneck": [sigmoid(math.log((min(row["K"], row["rho"], row["A"], row["V"], row["B"]) + EPSILON) / (row["D"] + EPSILON))) for row in rows],
        "M4_information_bottleneck": [sigmoid(math.log((row["A"] * row["V"] * row["B"] + EPSILON) / (row["D"] + EPSILON))) for row in rows],
        "M5_free_energy": [sigmoid((row["K"] * row["rho"] * row["A"] * row["V"] * row["B"]) - row["D"]) for row in rows],
        "M6_phase_threshold": [0.85 if row["numerator"] >= row["D"] else 0.15 for row in rows],
    }
    metrics = {name: metrics_payload(actual, values) for name, values in predictions.items()}
    best_auc = max(metrics, key=lambda name: metrics[name]["auc"]) if metrics else ""
    best_brier = min(metrics, key=lambda name: metrics[name]["brier_score"]) if metrics else ""
    return {"metrics": metrics, "best_by_auc": best_auc, "best_by_brier": best_brier}


def phase_transition_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bins = [
        ("M < -2", -math.inf, -2.0),
        ("-2 <= M < -1", -2.0, -1.0),
        ("-1 <= M < 0", -1.0, 0.0),
        ("0 <= M < 1", 0.0, 1.0),
        ("1 <= M < 2", 1.0, 2.0),
        ("M >= 2", 2.0, math.inf),
    ]
    summaries = []
    for label, low, high in bins:
        bucket = [row for row in rows if low <= row["M"] < high]
        success = _mean(row["outcome"] for row in bucket)
        uncertainty = _mean(row["capability_margin_probability"] * (1 - row["capability_margin_probability"]) for row in bucket)
        summaries.append({"bin": label, "rows": len(bucket), "success_rate": round(success, 6), "mean_uncertainty": round(uncertainty, 6), "mean_M": round(_mean(row["M"] for row in bucket), 6)})
    near = [row for row in rows if -0.5 <= row["M"] <= 0.5]
    outside = [row for row in rows if row["M"] < -1.0 or row["M"] > 1.0]
    jumps = [
        summaries[index + 1]["success_rate"] - summaries[index]["success_rate"]
        for index in range(len(summaries) - 1)
        if summaries[index]["rows"] and summaries[index + 1]["rows"]
    ]
    boundary_low = [row for row in rows if -1.0 <= row["M"] < 0.0]
    boundary_high = [row for row in rows if 0.0 <= row["M"] < 1.0]
    boundary_jump = _success_rate(boundary_high) - _success_rate(boundary_low) if boundary_low and boundary_high else 0.0
    return {
        "bins": summaries,
        "max_adjacent_success_jump": round(max([abs(jump) for jump in jumps] + [0.0]), 6),
        "boundary_jump_at_zero": round(boundary_jump, 6),
        "near_zero_rows": len(near),
        "near_zero_uncertainty": round(_mean(row["capability_margin_probability"] * (1 - row["capability_margin_probability"]) for row in near), 6),
        "outside_uncertainty": round(_mean(row["capability_margin_probability"] * (1 - row["capability_margin_probability"]) for row in outside), 6),
        "evidence_of_threshold_behavior": bool(abs(boundary_jump) >= 0.25 and len(boundary_low) >= 10 and len(boundary_high) >= 10),
    }


def compression_analysis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fields = {
        "K": "K",
        "rho": "rho",
        "A": "A",
        "V": "V",
        "B": "B",
        "D": "D",
        "Compatibility v1": "compatibility_v1",
        "Compatibility v2": "compatibility_v2",
        "EAC": "eac",
        "Route Friction": "route_friction",
        "Retrieval Selectivity": "retrieval_selectivity",
    }
    correlations = {
        left: {
            right: round(_corr([row[left_field] for row in rows], [row[right_field] for row in rows]), 6)
            for right, right_field in fields.items()
            if right != left
        }
        for left, left_field in fields.items()
    }
    theory_mapping = {
        "Compatibility v1": _best_component(correlations["Compatibility v1"], ("K", "rho", "A", "V", "B", "D")),
        "Compatibility v2": _best_component(correlations["Compatibility v2"], ("K", "rho", "A", "V", "B", "D")),
        "EAC": _best_component(correlations["EAC"], ("K", "rho", "A", "V", "B", "D")),
        "Route Friction": _best_component(correlations["Route Friction"], ("K", "rho", "A", "V", "B", "D")),
        "Retrieval Selectivity": _best_component(correlations["Retrieval Selectivity"], ("K", "rho", "A", "V", "B", "D")),
    }
    collapse_flags = {
        theory: abs(info["correlation"]) >= 0.85
        for theory, info in theory_mapping.items()
    }
    return {
        "correlations": correlations,
        "theory_to_margin_component": theory_mapping,
        "collapse_flags": collapse_flags,
        "collapsed_theories": [theory for theory, collapsed in collapse_flags.items() if collapsed],
        "independent_theories": [theory for theory, collapsed in collapse_flags.items() if not collapsed],
    }


def conserved_quantity_search(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = {
        "accessible_capability_over_task_demand": [row["numerator"] / max(EPSILON, row["D"]) for row in rows],
        "information_acquired_over_required": [(row["A"] * row["B"]) / max(EPSILON, row["D"]) for row in rows],
        "verification_over_construction_cost": [row["V"] / max(EPSILON, row["D"] / max(EPSILON, row["K"] * row["rho"])) for row in rows],
        "discovery_cost_over_solution_volume": [row["D"] / max(EPSILON, row["A"] * row["rho"]) for row in rows],
        "signal_to_noise_margin": [(row["K"] * row["rho"] * row["A"]) / max(EPSILON, (1 - row["V"]) + row["D"]) for row in rows],
        "free_energy_surplus": [(row["K"] * row["rho"] * row["A"] * row["V"] * row["B"]) - row["D"] for row in rows],
    }
    actual = [row["outcome"] for row in rows]
    scored = {}
    for name, values in candidates.items():
        normalized = _rank01(values)
        scored[name] = {
            **metrics_payload(actual, normalized),
            "raw_correlation": round(_corr(values, actual), 6),
            "interpretation": _quantity_interpretation(name),
        }
    best = max(scored, key=lambda name: (scored[name]["auc"], scored[name]["pseudo_r2"])) if scored else ""
    return {"candidates": scored, "strongest_candidate": best}


def falsification_tests(
    comparisons: dict[str, Any],
    transitions: dict[str, Any],
    alternatives: dict[str, Any],
    compression: dict[str, Any],
) -> dict[str, Any]:
    combined = comparisons.get("combined", {})
    margin = combined.get("Capability Margin", {})
    best_existing_auc = max((metrics.get("auc", 0.0) for name, metrics in combined.items() if name != "Capability Margin"), default=0.0)
    best_existing_brier = min((metrics.get("brier_score", 1.0) for name, metrics in combined.items() if name != "Capability Margin"), default=1.0)
    alt_combined = alternatives.get("combined", {}).get("metrics", {})
    best_alt = alternatives.get("combined", {}).get("best_by_brier", "")
    best_alt_brier = alt_combined.get(best_alt, {}).get("brier_score", 1.0) if best_alt else 1.0
    phase = transitions.get("combined", {})
    killed = []
    if not phase.get("evidence_of_threshold_behavior"):
        killed.append("no_phase_boundary_at_M_zero")
    if margin.get("auc", 0.0) + 0.02 < best_existing_auc:
        killed.append("no_prospective_or_combined_advantage_over_existing_theories")
    if best_alt and best_alt != "M_log_product_minus_demand" and best_alt_brier <= margin.get("brier_score", 1.0) + 0.005:
        killed.append("simpler_or_alternative_law_performs_equally_well")
    if len(compression.get("collapsed_theories", [])) >= 3:
        killed.append("reduces_to_existing_theory_components")
    return {
        "status": "KILLED" if killed else "SURVIVES_AS_ENGINEERING_CANDIDATE",
        "killed_conditions": killed,
        "combined_margin_auc": margin.get("auc", 0.0),
        "best_existing_auc": best_existing_auc,
        "combined_margin_brier": margin.get("brier_score", 0.0),
        "best_existing_brier": best_existing_brier,
        "best_alternative_by_brier": best_alt,
        "best_alternative_brier": best_alt_brier,
    }


def theory_graph(results: dict[str, Any]) -> dict[str, Any]:
    mapping = results.get("theory_compression", {}).get("theory_to_margin_component", {})
    return {
        "nodes": ["K capability", "rho specialization", "A accessible evidence", "V verification", "B execution budget", "D task demand", "Capability Margin", *mapping.keys()],
        "edges": [
            ("K capability", "Capability Margin", "numerator"),
            ("rho specialization", "Capability Margin", "numerator"),
            ("A accessible evidence", "Capability Margin", "numerator"),
            ("V verification", "Capability Margin", "numerator"),
            ("B execution budget", "Capability Margin", "numerator"),
            ("D task demand", "Capability Margin", "denominator"),
            *[(theory, info["component"], f"corr={info['correlation']}") for theory, info in mapping.items()],
        ],
    }


def novelty_analysis() -> dict[str, Any]:
    return {
        "scaling_laws": ("EXTENSION", "Uses a scale-like capability/demand ratio, but row-level task success is not a new scaling law."),
        "information_bottleneck": ("EXTENSION", "A and D resemble accessible versus required information; the form is a direct extension."),
        "predictive_coding": ("KNOWN", "Margin as error/surplus is analogous to prediction error, not novel."),
        "free_energy_principle": ("EXTENSION", "Accessible capability minus demand parallels free-energy surplus, without a formal variational derivation."),
        "transformer_circuits": ("KNOWN", "No circuit-level mechanism is tested."),
        "criticality": ("POTENTIALLY NOVEL", "A measurable M=0 boundary for agent success would be interesting if it survived prospective falsification."),
        "cryptographic_verification": ("EXTENSION", "V borrows the asymmetry between construction and verification, but applies it empirically to agent tasks."),
    }


def final_verdict(results: dict[str, Any]) -> dict[str, Any]:
    falsification = results["falsification"]
    phase = results["phase_transitions"].get("combined", {})
    conserved = results["conserved_quantities"]
    compression = results["theory_compression"]
    alternatives = results["alternative_laws"].get("combined", {})
    status = falsification["status"]
    return {
        "does_capability_margin_survive": status != "KILLED",
        "classification": "C. another engineering predictor" if status != "KILLED" else "B/C rejected as latent law; compressed engineering predictor at best",
        "phase_boundary_evidence": bool(phase.get("evidence_of_threshold_behavior")),
        "conserved_quantity_evidence": conserved.get("strongest_candidate", ""),
        "fundamental_variables": _fundamental_variables(compression),
        "theories_collapsing_into_margin": compression.get("collapsed_theories", []),
        "strongest_alternative_law": alternatives.get("best_by_brier", ""),
        "potentially_novel_direction": "Only the phase-transition claim would be potentially novel; current evidence must show a real M=0 boundary before a new direction is justified.",
        "kill_reasons": falsification.get("killed_conditions", []),
    }


def report_markdown(dataset: dict[str, Any], results: dict[str, Any]) -> str:
    lines = [
        "# Capability Margin Validation",
        "",
        f"- Scope: {dataset['scope']}",
        f"- Rows: {dataset['row_count']}",
        f"- Falsification status: `{results['falsification']['status']}`",
        "- Policy: no existing theory, dataset, or prediction artifact was modified.",
        "",
        "## Feature Definitions",
        "",
        *[f"- `{key}`: {value}" for key, value in dataset["feature_definitions"].items()],
        "",
        "## Theory Comparison",
        "",
    ]
    for dataset_name, comparisons in results["comparisons"].items():
        lines.extend([f"### {dataset_name}", "", "| theory | AUC | Brier | calibration | pseudo-R2 | correlation |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
        for name, metrics in comparisons.items():
            lines.append(
                f"| {name} | {metrics['auc']:.6f} | {metrics['brier_score']:.6f} | {metrics['calibration_error']:.6f} | {metrics['pseudo_r2']:.6f} | {metrics['correlation']:.6f} |"
            )
        lines.append("")
    lines.extend(["## Phase Transition Search", "", _phase_table(results["phase_transitions"].get("combined", {})), "", "## Alternative Laws", "", _alternative_table(results["alternative_laws"].get("combined", {})), ""])
    return "\n".join(lines)


def theory_graph_markdown(graph: dict[str, Any]) -> str:
    lines = ["# Capability Margin Theory Graph", "", "```text"]
    for source, target, label in graph["edges"]:
        lines.append(f"{source} --[{label}]--> {target}")
    lines.extend(["```", ""])
    return "\n".join(lines)


def novelty_markdown(rows: dict[str, Any]) -> str:
    lines = ["# Capability Margin Novelty", "", "| comparison area | classification | reason |", "| --- | --- | --- |"]
    for area, (classification, reason) in rows.items():
        lines.append(f"| {area} | {classification} | {reason} |")
    lines.append("")
    return "\n".join(lines)


def verdict_markdown(verdict: dict[str, Any]) -> str:
    kill_lines = [f"- {reason}" for reason in verdict["kill_reasons"]] if verdict["kill_reasons"] else ["- None triggered."]
    return "\n".join(
        [
            "# Capability Margin Verdict",
            "",
            f"1. Does Capability Margin survive? {verdict['does_capability_margin_survive']} ({verdict['classification']}).",
            f"2. Is there evidence for a phase boundary? {verdict['phase_boundary_evidence']}.",
            f"3. Is there evidence for a conserved quantity? Strongest candidate: `{verdict['conserved_quantity_evidence']}`.",
            f"4. Which variables appear fundamental? {', '.join(verdict['fundamental_variables']) or 'not established'}.",
            f"5. Which theories collapse into Margin? {', '.join(verdict['theories_collapsing_into_margin']) or 'none under the strict threshold'}.",
            f"6. What is the strongest alternative law? `{verdict['strongest_alternative_law']}`.",
            f"7. Is anything potentially novel enough for a new research direction? {verdict['potentially_novel_direction']}",
            "",
            "## Kill Reasons",
            "",
            *kill_lines,
            "",
        ]
    )


def execution_budget_score(context_budget: int | float) -> float:
    value = float(context_budget or 0.0)
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


def task_demand(category: str, repo_category_prior_count: int) -> float:
    base = TASK_DEMAND_BY_CATEGORY.get(category, 0.68)
    novelty_penalty = 0.12 * (1.0 - min(1.0, math.log1p(max(0, repo_category_prior_count)) / math.log(21)))
    return _clip01(base + novelty_penalty)


def retrieval_selectivity_proxy(accessible_evidence: float, context_budget: int | float) -> float:
    budget = execution_budget_score(context_budget)
    dilution = max(0.0, budget - accessible_evidence)
    return round(_clip01(accessible_evidence - 0.25 * dilution), 6)


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


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
        "combined": {"rows": combined_rows, "history": [], "mode": "leave_one_out"},
    }


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


def _dedupe_rows(rows: Iterable[CompatibilityV2Row]) -> list[CompatibilityV2Row]:
    seen = set()
    deduped = []
    for row in sorted(rows, key=lambda item: ((item.timestamp or datetime.min.replace(tzinfo=timezone.utc)).isoformat(), item.row_id)):
        if row.row_id in seen:
            continue
        seen.add(row.row_id)
        deduped.append(row)
    return deduped


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


def _best_component(correlations: dict[str, float], components: tuple[str, ...]) -> dict[str, Any]:
    component = max(components, key=lambda name: abs(correlations.get(name, 0.0)))
    return {"component": component, "correlation": correlations.get(component, 0.0)}


def _fundamental_variables(compression: dict[str, Any]) -> list[str]:
    mapping = compression.get("theory_to_margin_component", {})
    counts: dict[str, int] = defaultdict(int)
    for info in mapping.values():
        if abs(info.get("correlation", 0.0)) >= 0.35:
            counts[info.get("component", "")] += 1
    return [name for name, _count in sorted(counts.items(), key=lambda item: item[1], reverse=True) if name]


def _phase_table(payload: dict[str, Any]) -> str:
    lines = ["| M bin | rows | success | uncertainty | mean M |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in payload.get("bins", []):
        lines.append(f"| {row['bin']} | {row['rows']} | {row['success_rate']:.6f} | {row['mean_uncertainty']:.6f} | {row['mean_M']:.6f} |")
    lines.append(f"\nEvidence of threshold behavior: `{payload.get('evidence_of_threshold_behavior', False)}`.")
    return "\n".join(lines)


def _alternative_table(payload: dict[str, Any]) -> str:
    lines = ["| law | AUC | Brier | calibration | pseudo-R2 |", "| --- | ---: | ---: | ---: | ---: |"]
    for name, metrics in payload.get("metrics", {}).items():
        lines.append(f"| {name} | {metrics['auc']:.6f} | {metrics['brier_score']:.6f} | {metrics['calibration_error']:.6f} | {metrics['pseudo_r2']:.6f} |")
    lines.append(f"\nBest by Brier: `{payload.get('best_by_brier', '')}`.")
    return "\n".join(lines)


def _quantity_interpretation(name: str) -> str:
    return {
        "accessible_capability_over_task_demand": "Closest to the proposed conserved ratio: usable capability divided by demand.",
        "information_acquired_over_required": "Information bottleneck analogue.",
        "verification_over_construction_cost": "Cryptographic-style verification advantage proxy.",
        "discovery_cost_over_solution_volume": "Search/discovery cost proxy; lower raw values should be better, rank normalization tests monotonic association only.",
        "signal_to_noise_margin": "Signal-to-noise analogue combining capability and evidence against uncertainty/demand.",
        "free_energy_surplus": "Free-energy-style surplus of accessible work over demand.",
    }.get(name, "")


def _rank01(values: list[float]) -> list[float]:
    if not values:
        return []
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [0.0] * len(values)
    denom = max(1, len(values) - 1)
    for rank, (_value, index) in enumerate(ordered):
        ranks[index] = rank / denom
    return ranks


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


def _clip01(value: float) -> float:
    return max(0.001, min(0.999, float(value)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Capability Margin against cloud research rows.")
    parser.add_argument("--state-dir", default=".agent-hub", help="Agent-Hub state directory.")
    parser.add_argument("--json", action="store_true", help="Print output paths as JSON.")
    args = parser.parse_args(argv)
    paths = run_capability_margin_validation(args.state_dir)
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
    "FEATURE_DEFINITIONS",
    "build_capability_margin_dataset",
    "capability_margin_dataset_path",
    "compare_alternative_laws",
    "compute_margin_features",
    "evaluate_capability_margin",
    "phase_transition_summary",
    "run_capability_margin_validation",
]
