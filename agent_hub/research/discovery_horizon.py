from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


FORBIDDEN_HORIZON_FIELDS = {
    "success",
    "actual_outcome",
    "validation_score",
    "output",
    "output_preview",
    "error",
    "failure_type",
    "latency_ms",
    "tokens_used",
}

HORIZON_FILES = {
    "definition": "discovery_horizon_definition.md",
    "dataset": "discovery_horizon_dataset.json",
    "invariants": "discovery_horizon_invariants.md",
    "laws": "discovery_horizon_laws.md",
    "vs_theories": "discovery_horizon_vs_theories.md",
    "mechanism_tests": "discovery_horizon_mechanism_tests.md",
    "mediation": "discovery_horizon_mediation.md",
    "falsification": "discovery_horizon_falsification.md",
    "verdict": "discovery_horizon_verdict.md",
}


def research_dir(state_dir: str | Path = ".agent-hub") -> Path:
    root = Path(state_dir)
    return root if root.name == "research" else root / "research"


def run_discovery_horizon_research(state_dir: str | Path = ".agent-hub") -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rows = load_cloud_rows(directory)
    dataset = build_discovery_horizon_dataset(rows)
    comparisons = compare_theories(dataset["rows"])
    invariants = discover_invariants(dataset["rows"])
    laws = fit_candidate_laws(dataset["rows"])
    mechanisms = mechanism_tests(dataset["rows"])
    mediation = mediation_analysis(dataset["rows"])
    falsification = falsification_status(comparisons, laws, mechanisms)
    verdict = scientific_verdict(comparisons, laws, mechanisms, mediation, falsification)

    paths = {key: directory / filename for key, filename in HORIZON_FILES.items()}
    paths["definition"].write_text(definition_markdown(), encoding="utf-8")
    paths["dataset"].write_text(json.dumps(dataset, indent=2, sort_keys=True), encoding="utf-8")
    paths["invariants"].write_text(invariants_markdown(invariants), encoding="utf-8")
    paths["laws"].write_text(laws_markdown(laws), encoding="utf-8")
    paths["vs_theories"].write_text(comparison_markdown(comparisons), encoding="utf-8")
    paths["mechanism_tests"].write_text(mechanism_markdown(mechanisms), encoding="utf-8")
    paths["mediation"].write_text(mediation_markdown(mediation), encoding="utf-8")
    paths["falsification"].write_text(falsification_markdown(falsification), encoding="utf-8")
    paths["verdict"].write_text(verdict_markdown(verdict), encoding="utf-8")
    return paths


def load_cloud_rows(directory: Path) -> list[dict[str, Any]]:
    source = directory / "eac_compatibility_disagreements.json"
    if not source.exists():
        return []
    payload = json.loads(source.read_text(encoding="utf-8"))
    rows = []
    for row in payload.get("rows", []):
        model = str(row.get("model", "")).lower()
        provider = str(row.get("provider", "")).lower()
        route = str(row.get("route", "")).lower()
        if "local" in model or "local" in provider or "local" in route:
            continue
        rows.append(row)
    return rows


def build_discovery_horizon_dataset(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    output = []
    for index, row in enumerate(rows):
        h = compute_horizon_features(row)
        output.append(
            {
                "row_id": str(row.get("row_id") or f"row-{index}"),
                "dataset": row.get("dataset", ""),
                "model": row.get("model", ""),
                "provider": row.get("provider", ""),
                "route": row.get("route", ""),
                "repository": row.get("repository", ""),
                "category": row.get("category", ""),
                "context_budget": _number(row.get("context_budget"), 0.0),
                **h,
                "discovery_horizon": horizon_index(h),
                "compatibility_v1": _number(row.get("compatibility_v1_score"), 0.5),
                "compatibility_v2": _number(row.get("compatibility_v2_score"), 0.5),
                "eac": _number(row.get("eac_score"), 0.5),
                "route_friction": _number(row.get("route_reliability"), 0.5),
                "retrieval_selectivity": retrieval_selectivity_score(h),
                "outcome": _number(row.get("success"), 0.0),
                "measurement_mode": h["measurement_mode"],
                "non_leaky": True,
            }
        )
    return {
        "object": "agent_hub.research.discovery_horizon_dataset",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "cloud_models_only",
        "policy": {
            "no_local_models": True,
            "no_formula_tuning_after_outcomes": True,
            "compatibility_unmodified": True,
            "eac_unmodified": True,
            "discovery_horizon_v1_only": True,
            "forbidden_fields": sorted(FORBIDDEN_HORIZON_FIELDS),
        },
        "row_count": len(output),
        "rows": output,
    }


def compute_horizon_features(row: dict[str, Any]) -> dict[str, Any]:
    """Compute H1-H8 without using current-row outcome or generated-answer fields."""
    forbidden_used = sorted(FORBIDDEN_HORIZON_FIELDS.intersection(row.keys()) - {"success"})
    selected_files = _as_list(row.get("selected_files") or row.get("context_files"))
    relevant_files = _as_list(row.get("relevant_files") or row.get("expected_files") or row.get("target_files"))
    direct_rank = _first_relevant_rank(selected_files, relevant_files)
    evidence = _number(row.get("evidence_accessibility") or row.get("accessibility"), 0.5)
    verification = _number(row.get("verification_accessibility"), 0.5)
    route_reliability = _number(row.get("route_reliability"), 0.5)
    context_budget = _number(row.get("context_budget"), 0.0) / 100.0
    category = str(row.get("category") or "").lower()
    repository = str(row.get("repository") or "")

    if direct_rank is not None:
        h1 = direct_rank
        h2 = direct_rank - 1
        measurement_mode = "direct_retrieval_trace"
    else:
        h1 = _scaled_inverse(evidence, 1, 25)
        h2 = max(0.0, h1 - 1.0)
        measurement_mode = "proxy_from_frozen_metadata"

    retrieval_entropy = _retrieval_entropy(selected_files, context_budget, evidence)
    h4 = _search_iterations(category, evidence, context_budget)
    h5 = _scaled_inverse(verification, 1, 10)
    h6 = max(0.0, (1.0 - evidence) / max(0.05, evidence)) * (1.0 + context_budget)
    h7 = _repo_traversal_depth(repository, category, evidence, context_budget)
    h8 = _dependency_depth(category, evidence)

    return {
        "H1_first_relevant_file_rank": round(h1, 6),
        "H2_files_before_first_relevant": round(h2, 6),
        "H3_retrieval_entropy": round(retrieval_entropy, 6),
        "H4_search_iterations_to_decisive_evidence": round(h4, 6),
        "H5_verification_depth": round(h5, 6),
        "H6_irrelevant_to_relevant_ratio": round(h6, 6),
        "H7_repository_traversal_depth": round(h7, 6),
        "H8_dependency_traversal_depth": round(h8, 6),
        "measurement_mode": measurement_mode,
        "leakage_check": {
            "passed": True,
            "forbidden_fields_present_but_not_used": forbidden_used,
            "outcome_used_for_horizon": False,
        },
    }


def horizon_index(row: dict[str, Any]) -> float:
    values = [
        _normalize(row["H1_first_relevant_file_rank"], 1, 25),
        _normalize(row["H2_files_before_first_relevant"], 0, 24),
        _normalize(row["H3_retrieval_entropy"], 0, 5),
        _normalize(row["H4_search_iterations_to_decisive_evidence"], 1, 8),
        _normalize(row["H5_verification_depth"], 1, 10),
        _normalize(row["H6_irrelevant_to_relevant_ratio"], 0, 12),
        _normalize(row["H7_repository_traversal_depth"], 1, 10),
        _normalize(row["H8_dependency_traversal_depth"], 1, 10),
    ]
    return round(sum(values) / len(values), 6)


def retrieval_selectivity_score(horizon_row: dict[str, Any]) -> float:
    h1 = _normalize(horizon_row["H1_first_relevant_file_rank"], 1, 25)
    h6 = _normalize(horizon_row["H6_irrelevant_to_relevant_ratio"], 0, 12)
    return round(max(0.0, min(1.0, 1.0 - 0.65 * h1 - 0.35 * h6)), 6)


def compare_theories(rows: list[dict[str, Any]]) -> dict[str, Any]:
    predictors = {
        "Compatibility v1": lambda r: r["compatibility_v1"],
        "Compatibility v2": lambda r: r["compatibility_v2"],
        "EAC": lambda r: r["eac"],
        "Route Friction": lambda r: r["route_friction"],
        "Retrieval Selectivity": lambda r: r["retrieval_selectivity"],
        "Discovery Horizon": lambda r: horizon_probability(r["discovery_horizon"]),
    }
    by_dataset = _dataset_groups(rows)
    sections = {}
    for dataset_name, dataset_rows in by_dataset.items():
        sections[dataset_name] = {
            name: binary_metrics([fn(row) for row in dataset_rows], [row["outcome"] for row in dataset_rows])
            for name, fn in predictors.items()
        }
    return {
        "object": "agent_hub.research.discovery_horizon_comparison",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "datasets": sections,
        "best_by_combined_auc": _best(sections.get("combined", {}), "auc"),
        "best_by_combined_brier": _best_low(sections.get("combined", {}), "brier"),
    }


def discover_invariants(rows: list[dict[str, Any]]) -> dict[str, Any]:
    thresholds = []
    for t in [i / 20 for i in range(1, 20)]:
        low = [row for row in rows if row["discovery_horizon"] <= t]
        high = [row for row in rows if row["discovery_horizon"] > t]
        if len(low) >= 20 and len(high) >= 20:
            thresholds.append(
                {
                    "threshold": round(t, 2),
                    "low_success": round(_success_rate(low), 6),
                    "high_success": round(_success_rate(high), 6),
                    "collapse_gap": round(_success_rate(low) - _success_rate(high), 6),
                    "low_n": len(low),
                    "high_n": len(high),
                }
            )
    best = max(thresholds, key=lambda row: row["collapse_gap"]) if thresholds else {}
    model_curves = {}
    for model, group in _group(rows, "model").items():
        model_curves[model] = _horizon_bins(group, bins=5)
    return {
        "row_count": len(rows),
        "stable_threshold_candidate": best,
        "threshold_scan": thresholds,
        "model_horizon_curves": model_curves,
        "shared_curve_correlation": _shared_curve_correlation(model_curves),
    }


def fit_candidate_laws(rows: list[dict[str, Any]]) -> dict[str, Any]:
    x = [row["discovery_horizon"] for row in rows]
    y = [row["outcome"] for row in rows]
    laws = {
        "linear": _linear_fit(x, y, lambda h: h),
        "exponential": _linear_fit(
            x,
            [math.log(max(0.02, value)) for value in y],
            lambda h: h,
            inverse="exp",
            actual_y=y,
        ),
        "power": _linear_fit(
            [math.log(max(0.01, value)) for value in x],
            [math.log(max(0.02, value)) for value in y],
            lambda h: math.log(max(0.01, h)),
            inverse="power",
            actual_y=y,
        ),
        "logistic": _logistic_grid(x, y),
        "phase_transition": _phase_transition_fit(x, y),
    }
    best = min(laws.items(), key=lambda item: item[1]["aic"] if item[1]["aic"] is not None else float("inf"))
    return {
        "object": "agent_hub.research.discovery_horizon_laws",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": len(rows),
        "laws": laws,
        "best_by_aic": best[0],
    }


def mechanism_tests(rows: list[dict[str, Any]]) -> dict[str, Any]:
    horizon = [row["discovery_horizon"] for row in rows]
    success = [row["outcome"] for row in rows]
    h1 = [row["H1_first_relevant_file_rank"] for row in rows]
    retrieval = [row["retrieval_selectivity"] for row in rows]
    route = [row["route_friction"] for row in rows]
    compatibility = [row["compatibility_v2"] for row in rows]
    return {
        "prediction_A_lower_horizon_higher_success": {
            "correlation_H_success": round(_corr(horizon, success), 6),
            "supported": _corr(horizon, success) < -0.15,
        },
        "prediction_B_h1_strong_single_predictor": {
            "correlation_H1_success": round(_corr(h1, success), 6),
            "rank_among_h_metrics": _h_metric_rank(rows, "H1_first_relevant_file_rank"),
        },
        "prediction_C_retrieval_selectivity_lowers_H": {
            "correlation_retrieval_H": round(_corr(retrieval, horizon), 6),
            "supported": _corr(retrieval, horizon) < -0.4,
        },
        "prediction_D_route_friction_increases_H": {
            "correlation_route_reliability_H": round(_corr(route, horizon), 6),
            "supported": _corr(route, horizon) < -0.2,
        },
        "prediction_E_compatibility_correlates_with_H": {
            "correlation_compatibility_v2_H": round(_corr(compatibility, horizon), 6),
            "supported": abs(_corr(compatibility, horizon)) > 0.2,
        },
    }


def mediation_analysis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "Compatibility -> Discovery Horizon -> Success": _mediation(
            [row["compatibility_v2"] for row in rows],
            [row["discovery_horizon"] for row in rows],
            [row["outcome"] for row in rows],
        ),
        "Route Friction -> Discovery Horizon -> Success": _mediation(
            [row["route_friction"] for row in rows],
            [row["discovery_horizon"] for row in rows],
            [row["outcome"] for row in rows],
        ),
        "Retrieval Selectivity -> Discovery Horizon -> Success": _mediation(
            [row["retrieval_selectivity"] for row in rows],
            [row["discovery_horizon"] for row in rows],
            [row["outcome"] for row in rows],
        ),
    }


def falsification_status(comparison: dict[str, Any], laws: dict[str, Any], mechanisms: dict[str, Any]) -> dict[str, Any]:
    combined = comparison.get("datasets", {}).get("combined", {})
    dh = combined.get("Discovery Horizon", {})
    best_auc = max((row.get("auc") or 0.0) for row in combined.values()) if combined else 0.0
    killed_conditions = []
    if (dh.get("auc") or 0.0) < 0.6:
        killed_conditions.append("weak_or_absent_auc_signal")
    if (dh.get("pseudo_r2") or 0.0) <= 0.0:
        killed_conditions.append("no_positive_pseudo_r2")
    if (best_auc - (dh.get("auc") or 0.0)) > 0.05:
        killed_conditions.append("dominated_by_simpler_theory")
    if not mechanisms["prediction_A_lower_horizon_higher_success"]["supported"]:
        killed_conditions.append("lower_horizon_not_associated_with_success")
    return {
        "status": "KILLED" if killed_conditions else "SURVIVES_AS_CANDIDATE",
        "killed_conditions": killed_conditions,
        "required_future_kill_tests": [
            "No prospective relationship between H and success with 95% CI excluding meaningful effect.",
            "Relevant-file rank is not a top-third single predictor in a direct retrieval-trace dataset.",
            "Discovery Horizon is dominated by Compatibility v2, EAC, Route Friction, and Retrieval Selectivity on AUC, Brier, and calibration.",
            "Route and retrieval perturbations change success without changing H.",
        ],
        "best_law": laws.get("best_by_aic", ""),
    }


def scientific_verdict(
    comparison: dict[str, Any],
    laws: dict[str, Any],
    mechanisms: dict[str, Any],
    mediation: dict[str, Any],
    falsification: dict[str, Any],
) -> dict[str, Any]:
    combined = comparison.get("datasets", {}).get("combined", {})
    dh = combined.get("Discovery Horizon", {})
    compat = combined.get("Compatibility v2", {})
    eac = combined.get("EAC", {})
    return {
        "is_real_mechanism": bool(dh.get("auc", 0.0) >= 0.65 and mechanisms["prediction_A_lower_horizon_higher_success"]["supported"]),
        "stronger_than_compatibility": (dh.get("auc") or 0.0) > (compat.get("auc") or 0.0) and (dh.get("brier") or 1.0) < (compat.get("brier") or 1.0),
        "stronger_than_eac": (dh.get("auc") or 0.0) > (eac.get("auc") or 0.0) and (dh.get("brier") or 1.0) < (eac.get("brier") or 1.0),
        "explains_prospective_failures": _dataset_advantage(comparison, "prospective", "Discovery Horizon"),
        "explains_disagreement_datasets": bool(dh.get("auc", 0.0) >= 0.65),
        "breakthrough_candidate": bool(falsification["status"] != "KILLED" and dh.get("auc", 0.0) >= 0.75 and dh.get("pseudo_r2", 0.0) > 0.1),
        "best_fitting_law": laws.get("best_by_aic", ""),
        "mediation_summary": mediation,
        "falsification_status": falsification["status"],
    }


def horizon_probability(horizon: float) -> float:
    return round(math.exp(-1.45 * max(0.0, horizon)), 6)


def binary_metrics(predicted: list[float], actual: list[float]) -> dict[str, Any]:
    pairs = [(max(1e-6, min(1 - 1e-6, float(p))), float(a)) for p, a in zip(predicted, actual)]
    if not pairs:
        return {"n": 0}
    p = [row[0] for row in pairs]
    y = [row[1] for row in pairs]
    base = sum(y) / len(y)
    ll = -sum(a * math.log(q) + (1 - a) * math.log(1 - q) for q, a in pairs) / len(pairs)
    baseline = -sum(a * math.log(max(1e-6, min(1 - 1e-6, base))) + (1 - a) * math.log(max(1e-6, min(1 - 1e-6, 1 - base))) for a in y) / len(y)
    return {
        "n": len(pairs),
        "correlation": round(_corr(p, y), 6),
        "auc": round(_auc(p, y), 6),
        "brier": round(sum((q - a) ** 2 for q, a in pairs) / len(pairs), 6),
        "calibration": round(_calibration_error(p, y), 6),
        "pseudo_r2": round(1 - ll / baseline, 6) if baseline > 0 else 0.0,
    }


def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    return []


def _first_relevant_rank(selected: list[str], relevant: list[str]) -> int | None:
    if not selected or not relevant:
        return None
    relevant_set = {item.replace("\\", "/").lower() for item in relevant}
    for index, item in enumerate(selected, start=1):
        normalized = item.replace("\\", "/").lower()
        if normalized in relevant_set or any(part in normalized for part in relevant_set):
            return index
    return len(selected) + 1


def _scaled_inverse(score: float, low: float, high: float) -> float:
    return low + (1.0 - max(0.0, min(1.0, score))) * (high - low)


def _retrieval_entropy(selected_files: list[str], context_budget: float, evidence: float) -> float:
    if selected_files:
        dirs = defaultdict(int)
        for path in selected_files:
            parts = path.replace("\\", "/").split("/")
            dirs[parts[0] if parts else "root"] += 1
        total = sum(dirs.values())
        return -sum((count / total) * math.log(count / total, 2) for count in dirs.values() if count)
    return max(0.0, min(5.0, 1.0 + 4.0 * context_budget * (1.0 - evidence)))


def _search_iterations(category: str, evidence: float, context_budget: float) -> float:
    base = {
        "documentation": 1.4,
        "testing": 1.7,
        "bug_fix": 2.4,
        "refactor": 3.2,
        "architecture": 4.8,
        "analysis": 4.4,
        "research": 5.2,
    }.get(category, 3.2)
    return max(1.0, min(8.0, base + 2.0 * (1.0 - evidence) + context_budget))


def _repo_traversal_depth(repository: str, category: str, evidence: float, context_budget: float) -> float:
    repo_weight = 1.3 if repository == "Agent-Hub" else 1.0
    category_weight = 1.6 if category in {"architecture", "analysis", "research"} else 1.0
    return max(1.0, min(10.0, repo_weight * category_weight * (1.0 + 5.0 * (1.0 - evidence) + 2.0 * context_budget)))


def _dependency_depth(category: str, evidence: float) -> float:
    base = {
        "documentation": 1.2,
        "testing": 2.0,
        "bug_fix": 3.0,
        "refactor": 4.0,
        "architecture": 5.5,
        "analysis": 4.5,
        "research": 5.0,
    }.get(category, 3.0)
    return max(1.0, min(10.0, base + 2.0 * (1.0 - evidence)))


def _normalize(value: float, low: float, high: float) -> float:
    return max(0.0, min(1.0, (float(value) - low) / (high - low)))


def _dataset_groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {"combined": list(rows)}
    for row in rows:
        groups.setdefault(str(row.get("dataset") or "unknown"), []).append(row)
    return groups


def _best(metrics: dict[str, dict[str, Any]], key: str) -> str:
    if not metrics:
        return ""
    return max(metrics.items(), key=lambda item: item[1].get(key) or -999)[0]


def _best_low(metrics: dict[str, dict[str, Any]], key: str) -> str:
    if not metrics:
        return ""
    return min(metrics.items(), key=lambda item: item[1].get(key) if item[1].get(key) is not None else 999)[0]


def _success_rate(rows: list[dict[str, Any]]) -> float:
    return sum(row["outcome"] for row in rows) / len(rows) if rows else 0.0


def _group(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key) or "")].append(row)
    return dict(groups)


def _horizon_bins(rows: list[dict[str, Any]], bins: int) -> list[dict[str, Any]]:
    output = []
    for index in range(bins):
        lo = index / bins
        hi = (index + 1) / bins
        selected = [row for row in rows if row["discovery_horizon"] >= lo and (row["discovery_horizon"] < hi or index == bins - 1)]
        if selected:
            output.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(selected), "success_rate": round(_success_rate(selected), 6)})
    return output


def _shared_curve_correlation(curves: dict[str, list[dict[str, Any]]]) -> float:
    vectors = [[row["success_rate"] for row in curve] for curve in curves.values() if len(curve) >= 2]
    if len(vectors) < 2:
        return 0.0
    scores = []
    for i, left in enumerate(vectors):
        for right in vectors[i + 1 :]:
            n = min(len(left), len(right))
            scores.append(_corr(left[:n], right[:n]))
    return round(sum(scores) / len(scores), 6) if scores else 0.0


def _linear_fit(
    x: list[float],
    y: list[float],
    transform,
    inverse: str = "linear",
    actual_y: list[float] | None = None,
) -> dict[str, Any]:
    tx = [transform(value) for value in x]
    slope, intercept = _ols(tx, y)
    raw = [intercept + slope * value for value in tx]
    if inverse == "exp":
        predicted = [math.exp(value) for value in raw]
    elif inverse == "power":
        predicted = [math.exp(value) for value in raw]
    else:
        predicted = raw
    predicted = [max(1e-6, min(1 - 1e-6, value)) for value in predicted]
    return _fit_payload(predicted, actual_y or y, {"intercept": round(intercept, 6), "slope": round(slope, 6)})


def _logistic_grid(x: list[float], y: list[float]) -> dict[str, Any]:
    best = None
    for intercept in [i / 5 for i in range(-10, 11)]:
        for slope in [i / 5 for i in range(-30, 1)]:
            predicted = [1 / (1 + math.exp(-(intercept + slope * value))) for value in x]
            payload = _fit_payload(predicted, y, {"intercept": intercept, "slope": slope})
            if best is None or payload["log_loss"] < best["log_loss"]:
                best = payload
    return best or _fit_payload([0.5] * len(y), y, {})


def _phase_transition_fit(x: list[float], y: list[float]) -> dict[str, Any]:
    best = None
    for hc in [i / 20 for i in range(1, 20)]:
        for sharpness in [4, 8, 12, 16]:
            predicted = [1 / (1 + math.exp(sharpness * (value - hc))) for value in x]
            payload = _fit_payload(predicted, y, {"horizon_critical": hc, "sharpness": sharpness})
            if best is None or payload["log_loss"] < best["log_loss"]:
                best = payload
    return best or _fit_payload([0.5] * len(y), y, {})


def _fit_payload(predicted: list[float], actual: list[float], params: dict[str, Any]) -> dict[str, Any]:
    n = len(actual)
    k = max(1, len(params))
    ll = -sum(a * math.log(p) + (1 - a) * math.log(1 - p) for p, a in zip(predicted, actual)) / max(1, n)
    return {
        "parameters": params,
        "metrics": binary_metrics(predicted, actual),
        "log_loss": round(ll, 6),
        "aic": round(2 * k + 2 * n * ll, 6) if n else None,
        "bic": round(k * math.log(n) + 2 * n * ll, 6) if n else None,
        "confidence_intervals": "bootstrap CI required for final prospective claims; legacy fit reports point estimates only.",
    }


def _ols(x: list[float], y: list[float]) -> tuple[float, float]:
    if not x:
        return 0.0, 0.0
    mx = sum(x) / len(x)
    my = sum(y) / len(y)
    denom = sum((value - mx) ** 2 for value in x)
    if denom == 0:
        return 0.0, my
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / denom
    return slope, my - slope * mx


def _corr(x: list[float], y: list[float]) -> float:
    if len(x) < 2:
        return 0.0
    mx = sum(x) / len(x)
    my = sum(y) / len(y)
    vx = sum((value - mx) ** 2 for value in x)
    vy = sum((value - my) ** 2 for value in y)
    if vx <= 0 or vy <= 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(vx * vy)


def _auc(predicted: list[float], actual: list[float]) -> float:
    pairs = sorted(zip(predicted, actual), key=lambda item: item[0])
    pos = sum(1 for _, y in pairs if y >= 0.5)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return 0.5
    rank_sum = 0.0
    i = 0
    while i < len(pairs):
        j = i + 1
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        rank = (i + 1 + j) / 2
        rank_sum += rank * sum(1 for _, y in pairs[i:j] if y >= 0.5)
        i = j
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def _calibration_error(predicted: list[float], actual: list[float]) -> float:
    total = 0.0
    for bucket in range(10):
        lo = bucket / 10
        hi = (bucket + 1) / 10
        idx = [i for i, value in enumerate(predicted) if value >= lo and (value < hi or bucket == 9)]
        if idx:
            total += len(idx) / len(predicted) * abs(sum(predicted[i] for i in idx) / len(idx) - sum(actual[i] for i in idx) / len(idx))
    return total


def _h_metric_rank(rows: list[dict[str, Any]], metric: str) -> int:
    scores = []
    success = [row["outcome"] for row in rows]
    for key in [f"H{i}_{suffix}" for i, suffix in [
        (1, "first_relevant_file_rank"),
        (2, "files_before_first_relevant"),
        (3, "retrieval_entropy"),
        (4, "search_iterations_to_decisive_evidence"),
        (5, "verification_depth"),
        (6, "irrelevant_to_relevant_ratio"),
        (7, "repository_traversal_depth"),
        (8, "dependency_traversal_depth"),
    ]]:
        scores.append((key, abs(_corr([row[key] for row in rows], success))))
    ordered = sorted(scores, key=lambda item: item[1], reverse=True)
    return 1 + [key for key, _ in ordered].index(metric)


def _mediation(x: list[float], mediator: list[float], y: list[float]) -> dict[str, Any]:
    total = _corr(x, y)
    a = _corr(x, mediator)
    b = _corr(mediator, y)
    direct_proxy = total - a * b
    mediated = a * b
    share = mediated / total if abs(total) > 1e-9 else 0.0
    return {
        "total_effect_correlation": round(total, 6),
        "x_to_horizon": round(a, 6),
        "horizon_to_success": round(b, 6),
        "indirect_effect_proxy": round(mediated, 6),
        "direct_effect_proxy": round(direct_proxy, 6),
        "mediated_share_proxy": round(share, 6),
        "method_note": "Correlation-product mediation screen; not a causal estimate without randomized H manipulation.",
    }


def _dataset_advantage(comparison: dict[str, Any], dataset: str, theory: str) -> bool:
    metrics = comparison.get("datasets", {}).get(dataset, {})
    if theory not in metrics:
        return False
    return metrics[theory].get("auc", 0.0) >= max(row.get("auc", 0.0) for row in metrics.values()) - 0.03


def definition_markdown() -> str:
    return """# Discovery Horizon Definition

Discovery Horizon (H) is the expected search distance from task start to the first decisive piece of information. The fixed candidate law is `P(success) ~= exp(-alpha H)`.

## Measurable Quantities

- H1, rank of first relevant file: 1-indexed position of the first task-relevant file in retrieved or selected context. If no direct trace exists, use a frozen evidence-accessibility proxy and mark `measurement_mode=proxy_from_frozen_metadata`.
- H2, files inspected before first relevant file: `max(0, H1 - 1)`.
- H3, retrieval entropy: entropy over top-level directories in selected context; proxy uses context budget and evidence accessibility when file traces are absent.
- H4, search iterations before decisive evidence: fixed task-category and evidence-accessibility estimate of how many search steps are needed before decisive information appears.
- H5, verification depth: inverse of verification accessibility, scaled so directly checkable tasks have shallow depth.
- H6, irrelevant-to-relevant information ratio: `(1 - evidence_accessibility) / evidence_accessibility`, adjusted by context budget.
- H7, repository traversal depth: fixed function of repository, task category, context budget, and evidence accessibility.
- H8, dependency traversal depth: fixed function of task category and evidence accessibility.

## Leakage Risks

Forbidden fields for H computation: success, actual outcome, validation score, generated output, error text, failure type, latency, retries, and token usage. These may appear in source artifacts but are not used for H1-H8.

## Measurement Limitations

Legacy cloud rows often lack explicit retrieval traces, so H1-H4 are partly proxy measurements. Direct Discovery Horizon validation requires future cloud rows that record retrieval order and search iteration count before outcome collection.
"""


def invariants_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Discovery Horizon Invariants", "", f"- Rows: {payload['row_count']}", f"- Stable threshold candidate: {payload['stable_threshold_candidate']}", f"- Shared model curve correlation: {payload['shared_curve_correlation']}", "", "## Threshold Scan", "", "| H threshold | low-H success | high-H success | collapse gap | low n | high n |", "| --- | --- | --- | --- | --- | --- |"]
    for row in payload["threshold_scan"]:
        lines.append(f"| {row['threshold']} | {row['low_success']} | {row['high_success']} | {row['collapse_gap']} | {row['low_n']} | {row['high_n']} |")
    lines.extend(["", "## Model Curves", ""])
    for model, curve in payload["model_horizon_curves"].items():
        lines.append(f"### {model}")
        for row in curve:
            lines.append(f"- {row['bin']}: n={row['n']}, success={row['success_rate']}")
        lines.append("")
    return "\n".join(lines)


def laws_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Discovery Horizon Laws", "", f"- Rows: {payload['rows']}", f"- Best by AIC: {payload['best_by_aic']}", "", "| law | AUC | Brier | calibration | pseudo-R2 | log loss | AIC | BIC | parameters |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, row in payload["laws"].items():
        metrics = row["metrics"]
        lines.append(f"| {name} | {metrics.get('auc')} | {metrics.get('brier')} | {metrics.get('calibration')} | {metrics.get('pseudo_r2')} | {row.get('log_loss')} | {row.get('aic')} | {row.get('bic')} | {row.get('parameters')} |")
    lines.extend(["", "Confidence intervals: legacy rows report point estimates. Prospective claims require bootstrap CIs frozen before collection."])
    return "\n".join(lines)


def comparison_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Discovery Horizon vs Existing Theories", "", f"- Best combined AUC: {payload['best_by_combined_auc']}", f"- Best combined Brier: {payload['best_by_combined_brier']}", ""]
    for dataset, theories in payload["datasets"].items():
        lines.extend([f"## {dataset}", "", "| theory | n | corr | pseudo-R2 | AUC | Brier | calibration |", "| --- | --- | --- | --- | --- | --- | --- |"])
        for name, metrics in theories.items():
            lines.append(f"| {name} | {metrics.get('n')} | {metrics.get('correlation')} | {metrics.get('pseudo_r2')} | {metrics.get('auc')} | {metrics.get('brier')} | {metrics.get('calibration')} |")
        lines.append("")
    return "\n".join(lines)


def mechanism_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Discovery Horizon Mechanism Tests", ""]
    for name, row in payload.items():
        lines.append(f"## {name}")
        for key, value in row.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    return "\n".join(lines)


def mediation_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Discovery Horizon Mediation", "", "| path | total | X->H | H->success | indirect | direct | mediated share |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, row in payload.items():
        lines.append(f"| {name} | {row['total_effect_correlation']} | {row['x_to_horizon']} | {row['horizon_to_success']} | {row['indirect_effect_proxy']} | {row['direct_effect_proxy']} | {row['mediated_share_proxy']} |")
    lines.extend(["", "This is a correlation-product mediation screen, not a causal estimate."])
    return "\n".join(lines)


def falsification_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Discovery Horizon Falsification", "", f"- Status: {payload['status']}", f"- Best law: {payload['best_law']}", f"- Killed conditions: {payload['killed_conditions']}", "", "## Conditions That Would Kill Discovery Horizon", ""]
    for item in payload["required_future_kill_tests"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def verdict_markdown(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Discovery Horizon Verdict",
            "",
            f"- Is Discovery Horizon a real mechanism? {payload['is_real_mechanism']}",
            f"- Is it stronger than Compatibility? {payload['stronger_than_compatibility']}",
            f"- Is it stronger than EAC? {payload['stronger_than_eac']}",
            f"- Does it explain prospective failures? {payload['explains_prospective_failures']}",
            f"- Does it explain disagreement datasets? {payload['explains_disagreement_datasets']}",
            f"- Is it a breakthrough candidate? {payload['breakthrough_candidate']}",
            f"- Best-fitting law: {payload['best_fitting_law']}",
            f"- Falsification status: {payload['falsification_status']}",
            "",
            "Scientific verdict: Discovery Horizon is a plausible mechanism if it survives as a candidate and shows a monotonic negative H-success relationship, but it is not a breakthrough until direct retrieval-trace prospective data confirms that search distance dominates Compatibility, EAC, Route Friction, and Retrieval Selectivity.",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Discovery Horizon research artifacts.")
    parser.add_argument("--state-dir", default=".agent-hub")
    args = parser.parse_args(argv)
    paths = run_discovery_horizon_research(args.state_dir)
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
