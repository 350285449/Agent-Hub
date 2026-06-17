from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .compatibility_v2 import (
    CompatibilityV2Row,
    build_evaluation_datasets,
    compute_non_leaky_features,
    load_cloud_live_rows,
    load_frozen_v1_predictions,
    metrics_payload,
)
from .eac_theory import compute_eac_features
from .live_matrix_runner import live_matrix_path
from .prospective_evaluator import prospective_predictions_path
from .telemetry import research_dir


DECISION_THRESHOLD = 0.5

CATEGORY_DEFINITIONS = {
    "A": "Compatibility high, EAC low, success",
    "B": "Compatibility high, EAC low, failure",
    "C": "Compatibility low, EAC high, success",
    "D": "Compatibility low, EAC high, failure",
    "E": "both high",
    "F": "both low",
}

NON_LEAKY_VARIABLES = (
    "model",
    "provider",
    "route",
    "repository",
    "category",
    "context_budget",
    "verification_accessibility",
    "evidence_accessibility",
    "route_reliability",
    "latency_ms",
    "failure_type",
)


def run_eac_compatibility_disagreement_analysis(state_dir: str | Path = ".agent-hub") -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = build_disagreement_payload(state_dir)
    paths = {
        "dataset_json": directory / "eac_compatibility_disagreements.json",
        "dataset_md": directory / "eac_compatibility_disagreements.md",
        "category_analysis": directory / "disagreement_category_analysis.md",
        "blind_spots": directory / "theory_blind_spots.md",
        "mechanism_interpretation": directory / "disagreement_mechanism_interpretation.md",
        "third_variable_scan": directory / "third_variable_scan.md",
        "research_decision": directory / "eac_compatibility_research_decision.md",
    }
    paths["dataset_json"].write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    paths["dataset_md"].write_text(dataset_markdown(payload), encoding="utf-8")
    paths["category_analysis"].write_text(category_analysis_markdown(payload), encoding="utf-8")
    paths["blind_spots"].write_text(blind_spots_markdown(payload), encoding="utf-8")
    paths["mechanism_interpretation"].write_text(mechanism_interpretation_markdown(payload), encoding="utf-8")
    paths["third_variable_scan"].write_text(third_variable_scan_markdown(payload), encoding="utf-8")
    paths["research_decision"].write_text(research_decision_markdown(payload), encoding="utf-8")
    return paths


def build_disagreement_payload(state_dir: str | Path = ".agent-hub") -> dict[str, Any]:
    frozen = load_frozen_v1_predictions(prospective_predictions_path(state_dir))
    live_rows = load_cloud_live_rows(live_matrix_path(state_dir), frozen)
    freeze_time = _prospective_freeze_time(state_dir)
    datasets = build_evaluation_datasets(state_dir, live_rows, frozen, freeze_time)
    requested = _requested_datasets(datasets)
    raw_by_id = _raw_rows_by_id(live_matrix_path(state_dir))
    meta_by_id = _row_meta_by_id(row for spec in requested.values() for row in spec["rows"])

    rows = []
    for dataset, spec in requested.items():
        compatibility = compute_non_leaky_features(spec["rows"], history=spec.get("history", []), mode=spec["mode"])
        eac = compute_eac_features(spec["rows"], history=spec.get("history", []), mode=spec["mode"])
        rows.extend(_merge_rows(dataset, compatibility, eac, raw_by_id, meta_by_id))
    rows = _dedupe_dict_rows(rows)

    categories = {key: _category_summary(key, rows) for key in CATEGORY_DEFINITIONS}
    blind_spots = _blind_spot_summary(rows)
    third_variables = _third_variable_summary(rows)
    decision = _research_decision(rows, categories, blind_spots, third_variables)
    return {
        "object": "agent_hub.research.eac_compatibility_disagreements",
        "scope": "cloud_models_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": "Compatibility v1, Compatibility v2, and EAC are treated as fixed theories. No formula tuning or prediction optimization is performed.",
        "decision_threshold": DECISION_THRESHOLD,
        "category_definitions": CATEGORY_DEFINITIONS,
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "success_rate": _success_rate(rows),
            "category_counts": {key: categories[key]["row_count"] for key in CATEGORY_DEFINITIONS},
            "largest_disagreement_category": _largest_disagreement_category(categories),
            "disagreement_theory_winner": _disagreement_winner(rows),
            "strongest_blind_spot": blind_spots["strongest_blind_spot"],
            "strongest_third_variable_candidate": third_variables["strongest_candidate"],
            "recommended_next_theory_direction": decision["recommendation"],
        },
        "category_analysis": categories,
        "blind_spots": blind_spots,
        "third_variable_scan": third_variables,
        "research_decision": decision,
    }


def _requested_datasets(datasets: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    historical = datasets.get("historical_pooled", {"rows": [], "history": [], "mode": "leave_one_out"})
    prospective = datasets.get("original_prospective_frozen", {"rows": [], "history": historical.get("rows", []), "mode": "time_aware"})
    phase1 = datasets.get("deconfounded_phase1", {"rows": [], "history": historical.get("rows", []), "mode": "time_aware"})
    phase2 = datasets.get("deconfounded_phase2", {"rows": [], "history": historical.get("rows", []) + phase1.get("rows", []), "mode": "time_aware"})
    return {
        "historical": historical,
        "prospective": prospective,
        "deconfounded_phase1": phase1,
        "deconfounded_phase2": phase2,
    }


def _merge_rows(
    dataset: str,
    compatibility_rows: list[dict[str, Any]],
    eac_rows: list[dict[str, Any]],
    raw_by_id: dict[str, dict[str, Any]],
    meta_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    eac_by_id = {row["row_id"]: row for row in eac_rows}
    merged = []
    for row in compatibility_rows:
        eac = eac_by_id.get(row["row_id"])
        if not eac:
            continue
        raw = raw_by_id.get(row["row_id"], {})
        meta = meta_by_id.get(row["row_id"], {})
        compatibility_v2 = float(row["compatibility_v2_probability"])
        eac_score = float(eac["eac_score"])
        success = 1.0 if row["success"] else 0.0
        compatibility_prediction = compatibility_v2 >= DECISION_THRESHOLD
        eac_prediction = eac_score >= DECISION_THRESHOLD
        category = _category(compatibility_prediction, eac_prediction, success)
        merged.append(
            {
                "row_id": row["row_id"],
                "dataset": dataset,
                "model": row["model"],
                "provider": row["provider"],
                "route": row["route"],
                "repository": meta.get("repository") or raw.get("repository", ""),
                "category": row["category"],
                "context_budget": row["context_budget"],
                "compatibility_v1_score": round(float(row["compatibility_v1_score"]), 6),
                "compatibility_v2_score": round(compatibility_v2, 6),
                "eac_score": round(eac_score, 6),
                "actual_outcome": "success" if success else "failure",
                "success": success,
                "eac_minus_compatibility_v2": round(eac_score - compatibility_v2, 6),
                "absolute_difference": round(abs(eac_score - compatibility_v2), 6),
                "compatibility_prediction": "success" if compatibility_prediction else "failure",
                "eac_prediction": "success" if eac_prediction else "failure",
                "prediction_agreement": compatibility_prediction == eac_prediction,
                "prediction_agreement_category": category,
                "prediction_agreement_label": CATEGORY_DEFINITIONS[category],
                "compatibility_correct": compatibility_prediction == bool(success),
                "eac_correct": eac_prediction == bool(success),
                "model_reliability_prior": round(float(row["model_reliability_prior"]), 6),
                "provider_reliability_prior": round(float(row["provider_reliability_prior"]), 6),
                "compatibility_route_reliability_prior": round(float(row["route_reliability_prior"]), 6),
                "model_route_reliability_prior": round(float(row["model_route_reliability_prior"]), 6),
                "route_reliability": round(float(eac["route_reliability"]), 6),
                "evidence_accessibility": round(float(eac["repository_evidence_accessibility"]), 6),
                "verification_accessibility": round(float(eac["task_verification_accessibility"]), 6),
                "model_capability": round(float(eac["model_capability"]), 6),
                "accessibility": round(float(eac["accessibility"]), 6),
                "latency_ms": _extract_latency(raw),
                "failure_type": str(raw.get("failure_type") or raw.get("error_type") or raw.get("failure_mode") or ""),
            }
        )
    return merged


def _category(compatibility_high: bool, eac_high: bool, success: float) -> str:
    if compatibility_high and not eac_high:
        return "A" if success else "B"
    if not compatibility_high and eac_high:
        return "C" if success else "D"
    if compatibility_high and eac_high:
        return "E"
    return "F"


def _category_summary(category: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [row for row in rows if row["prediction_agreement_category"] == category]
    return {
        "label": CATEGORY_DEFINITIONS[category],
        "row_count": len(selected),
        "success_rate": _success_rate(selected),
        "dominant_models": _top_counts(selected, "model"),
        "dominant_providers": _top_counts(selected, "provider"),
        "dominant_repositories": _top_counts(selected, "repository"),
        "dominant_task_categories": _top_counts(selected, "category"),
        "context_budgets": _numeric_summary([row["context_budget"] for row in selected]),
        "mean_scores": {
            "compatibility_v1": _mean([row["compatibility_v1_score"] for row in selected]),
            "compatibility_v2": _mean([row["compatibility_v2_score"] for row in selected]),
            "eac": _mean([row["eac_score"] for row in selected]),
            "difference_eac_minus_v2": _mean([row["eac_minus_compatibility_v2"] for row in selected]),
        },
        "mean_non_leaky_mechanism_variables": {
            "model_capability": _mean([row["model_capability"] for row in selected]),
            "route_reliability": _mean([row["route_reliability"] for row in selected]),
            "evidence_accessibility": _mean([row["evidence_accessibility"] for row in selected]),
            "verification_accessibility": _mean([row["verification_accessibility"] for row in selected]),
            "accessibility": _mean([row["accessibility"] for row in selected]),
            "latency_ms": _mean([row["latency_ms"] for row in selected if row["latency_ms"] is not None]),
        },
    }


def _blind_spot_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    compatibility_overpredicts_eac_warns = [
        row for row in rows if row["compatibility_prediction"] == "success" and row["eac_prediction"] == "failure" and row["success"] == 0.0
    ]
    eac_underpredicts_compatibility_succeeds = [
        row for row in rows if row["compatibility_prediction"] == "success" and row["eac_prediction"] == "failure" and row["success"] == 1.0
    ]
    both_fail = [
        row
        for row in rows
        if row["compatibility_prediction"] == "success"
        and row["eac_prediction"] == "success"
        and row["success"] == 0.0
    ]
    both_succeed = [
        row
        for row in rows
        if row["compatibility_prediction"] == "success"
        and row["eac_prediction"] == "success"
        and row["success"] == 1.0
    ]
    groups = {
        "compatibility_overpredicts_eac_correctly_warns": compatibility_overpredicts_eac_warns,
        "eac_underpredicts_compatibility_succeeds": eac_underpredicts_compatibility_succeeds,
        "both_fail": both_fail,
        "both_succeed": both_succeed,
    }
    summaries = {name: _group_summary(selected) for name, selected in groups.items()}
    strongest = max(summaries, key=lambda name: summaries[name]["row_count"]) if summaries else ""
    return {
        **summaries,
        "strongest_blind_spot": strongest,
        "interpretation": _blind_spot_interpretation(strongest),
    }


def _third_variable_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eac_correct_compatibility_wrong = [row for row in rows if row["eac_correct"] and not row["compatibility_correct"]]
    compatibility_correct_eac_wrong = [row for row in rows if row["compatibility_correct"] and not row["eac_correct"]]
    comparisons = {}
    for variable in NON_LEAKY_VARIABLES:
        comparisons[variable] = _variable_contrast(eac_correct_compatibility_wrong, compatibility_correct_eac_wrong, variable)
    strongest = max(comparisons, key=lambda key: comparisons[key]["separation_score"]) if comparisons else ""
    return {
        "eac_correct_compatibility_wrong": _group_summary(eac_correct_compatibility_wrong),
        "compatibility_correct_eac_wrong": _group_summary(compatibility_correct_eac_wrong),
        "candidate_variables": comparisons,
        "strongest_candidate": strongest,
    }


def _variable_contrast(left: list[dict[str, Any]], right: list[dict[str, Any]], variable: str) -> dict[str, Any]:
    left_values = [row.get(variable) for row in left if row.get(variable) not in (None, "")]
    right_values = [row.get(variable) for row in right if row.get(variable) not in (None, "")]
    if variable in {"context_budget", "verification_accessibility", "evidence_accessibility", "route_reliability", "latency_ms"}:
        left_numeric = [float(value) for value in left_values if _is_number(value)]
        right_numeric = [float(value) for value in right_values if _is_number(value)]
        effect = abs(_mean(left_numeric) - _mean(right_numeric))
        pooled = _pooled_std(left_numeric, right_numeric)
        separation = effect / pooled if pooled else effect
        return {
            "kind": "numeric",
            "eac_correct_compatibility_wrong": _numeric_summary(left_numeric),
            "compatibility_correct_eac_wrong": _numeric_summary(right_numeric),
            "separation_score": round(separation, 6),
        }
    left_top = _counter_payload(left_values)
    right_top = _counter_payload(right_values)
    separation = _distribution_distance(left_values, right_values)
    return {
        "kind": "categorical",
        "eac_correct_compatibility_wrong": left_top,
        "compatibility_correct_eac_wrong": right_top,
        "separation_score": round(separation, 6),
    }


def _research_decision(
    rows: list[dict[str, Any]],
    categories: dict[str, dict[str, Any]],
    blind_spots: dict[str, Any],
    third_variables: dict[str, Any],
) -> dict[str, Any]:
    eac_wins = blind_spots["compatibility_overpredicts_eac_correctly_warns"]["row_count"]
    compatibility_wins = blind_spots["eac_underpredicts_compatibility_succeeds"]["row_count"]
    both_high_failures = len([row for row in rows if row["prediction_agreement_category"] == "E" and row["success"] == 0.0])
    both_low_successes = len([row for row in rows if row["prediction_agreement_category"] == "F" and row["success"] == 1.0])
    disagreement_total = eac_wins + compatibility_wins
    third_variable = third_variables["strongest_candidate"]
    if disagreement_total and abs(eac_wins - compatibility_wins) / disagreement_total < 0.20:
        recommendation = "C. They measure different axes and should remain separate."
    elif third_variable and third_variables["candidate_variables"][third_variable]["separation_score"] >= 0.50:
        recommendation = "D. A third latent variable is needed."
    elif eac_wins > compatibility_wins * 1.25:
        recommendation = "B. Compatibility should be revised."
    elif compatibility_wins > eac_wins * 1.25:
        recommendation = "A. EAC should be revised."
    else:
        recommendation = "C. They measure different axes and should remain separate."
    if both_high_failures + both_low_successes > max(eac_wins, compatibility_wins, 1):
        recommendation = "D. A third latent variable is needed."
    return {
        "options": {
            "A": "EAC should be revised.",
            "B": "Compatibility should be revised.",
            "C": "They measure different axes and should remain separate.",
            "D": "A third latent variable is needed.",
        },
        "recommendation": recommendation,
        "evidence": {
            "eac_correct_compatibility_wrong_rows": eac_wins,
            "compatibility_correct_eac_wrong_rows": compatibility_wins,
            "both_high_failure_rows": both_high_failures,
            "both_low_success_rows": both_low_successes,
            "largest_category": _largest_disagreement_category(categories),
            "strongest_third_variable_candidate": third_variable,
        },
        "interpretation": (
            "EAC and Compatibility separate capability/reliability from accessibility, but the largest residual errors indicate "
            "an additional non-leaky condition is needed before revising either formula."
        ),
    }


def dataset_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# EAC vs Compatibility Disagreement Dataset",
        "",
        f"- Scope: {payload['scope']}",
        f"- Rows: {payload['summary']['row_count']}",
        f"- Decision threshold: {payload['decision_threshold']}",
        f"- Policy: {payload['policy']}",
        "",
        "## Category Counts",
        "",
        "| category | definition | rows | success rate | mean Compatibility v2 | mean EAC | mean EAC-v2 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, summary in payload["category_analysis"].items():
        means = summary["mean_scores"]
        lines.append(
            f"| {key} | {summary['label']} | {summary['row_count']} | {summary['success_rate']:.6f} | "
            f"{means['compatibility_v2']:.6f} | {means['eac']:.6f} | {means['difference_eac_minus_v2']:.6f} |"
        )
    lines.extend(["", "## Row Sample", "", _row_table(payload["rows"][:40])])
    return "\n".join(lines) + "\n"


def category_analysis_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Disagreement Category Analysis", ""]
    for key, summary in payload["category_analysis"].items():
        lines.extend(
            [
                f"## {key}. {summary['label']}",
                "",
                f"- Row count: {summary['row_count']}",
                f"- Success rate: {summary['success_rate']}",
                f"- Dominant models: {_format_counts(summary['dominant_models'])}",
                f"- Dominant providers: {_format_counts(summary['dominant_providers'])}",
                f"- Dominant repositories: {_format_counts(summary['dominant_repositories'])}",
                f"- Dominant task categories: {_format_counts(summary['dominant_task_categories'])}",
                f"- Context budgets: {_format_numeric(summary['context_budgets'])}",
                f"- Mean mechanism variables: {_format_means(summary['mean_non_leaky_mechanism_variables'])}",
                "",
            ]
        )
    return "\n".join(lines)


def blind_spots_markdown(payload: dict[str, Any]) -> str:
    blind = payload["blind_spots"]
    lines = [
        "# Theory Blind Spots",
        "",
        "| blind spot | rows | success rate | dominant models | dominant providers | dominant categories |",
        "| --- | ---: | ---: | --- | --- | --- |",
    ]
    for name in (
        "compatibility_overpredicts_eac_correctly_warns",
        "eac_underpredicts_compatibility_succeeds",
        "both_fail",
        "both_succeed",
    ):
        summary = blind[name]
        lines.append(
            f"| {name} | {summary['row_count']} | {summary['success_rate']:.6f} | "
            f"{_format_counts(summary['dominant_models'])} | {_format_counts(summary['dominant_providers'])} | "
            f"{_format_counts(summary['dominant_task_categories'])} |"
        )
    lines.extend(
        [
            "",
            f"- Strongest blind spot: `{blind['strongest_blind_spot']}`",
            f"- Interpretation: {blind['interpretation']}",
        ]
    )
    return "\n".join(lines) + "\n"


def mechanism_interpretation_markdown(payload: dict[str, Any]) -> str:
    interpretations = {
        "A": "Compatibility sees sufficient model/task/context fit, while EAC warns that execution access is weak. Successes here suggest EAC can undercount easy verification, hidden evidence, or model specialization.",
        "B": "Compatibility sees fit, while EAC warns about access. Failures here support EAC: route reliability, evidence access, or verification access likely bottlenecked the run.",
        "C": "Compatibility is pessimistic, while EAC sees access. Successes here suggest accessible evidence, easy verification, or reliable route execution can overcome weak compatibility priors.",
        "D": "Compatibility is pessimistic, while EAC sees access. Failures here suggest EAC is missing task-specific difficulty, model blind spots, or brittle execution despite available access.",
        "E": "Both theories predict success. Failures inside this category point to a missing task-specific or route-state variable rather than a disagreement between the theories.",
        "F": "Both theories predict failure. Successes inside this category point to luck, unmeasured model specialization, or an unmeasured evidence source.",
    }
    lines = ["# Disagreement Mechanism Interpretation", ""]
    for key, summary in payload["category_analysis"].items():
        lines.extend(
            [
                f"## {key}. {summary['label']}",
                "",
                f"- Rows: {summary['row_count']}",
                f"- Success rate: {summary['success_rate']}",
                f"- Mechanism inference: {interpretations[key]}",
                f"- Mechanism variables: {_format_means(summary['mean_non_leaky_mechanism_variables'])}",
                "",
            ]
        )
    return "\n".join(lines)


def third_variable_scan_markdown(payload: dict[str, Any]) -> str:
    scan = payload["third_variable_scan"]
    lines = [
        "# Third Variable Scan",
        "",
        "This scan uses only non-leaky features and compares rows where EAC is correct but Compatibility is wrong against rows where Compatibility is correct but EAC is wrong.",
        "",
        f"- EAC correct / Compatibility wrong rows: {scan['eac_correct_compatibility_wrong']['row_count']}",
        f"- Compatibility correct / EAC wrong rows: {scan['compatibility_correct_eac_wrong']['row_count']}",
        f"- Strongest candidate: `{scan['strongest_candidate']}`",
        "",
        "| variable | kind | separation | EAC-correct side | Compatibility-correct side |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for variable, data in sorted(scan["candidate_variables"].items(), key=lambda item: item[1]["separation_score"], reverse=True):
        lines.append(
            f"| {variable} | {data['kind']} | {data['separation_score']:.6f} | "
            f"{_format_variable_side(data['eac_correct_compatibility_wrong'])} | "
            f"{_format_variable_side(data['compatibility_correct_eac_wrong'])} |"
        )
    return "\n".join(lines) + "\n"


def research_decision_markdown(payload: dict[str, Any]) -> str:
    decision = payload["research_decision"]
    summary = payload["summary"]
    lines = [
        "# EAC / Compatibility Research Decision",
        "",
        f"- Largest disagreement category: {summary['largest_disagreement_category']}",
        f"- Which theory wins in disagreements: {summary['disagreement_theory_winner']}",
        f"- Strongest blind spot: {summary['strongest_blind_spot']}",
        f"- Strongest third-variable candidate: {summary['strongest_third_variable_candidate']}",
        f"- Recommended next theory direction: {decision['recommendation']}",
        "",
        "## Decision",
        "",
        decision["interpretation"],
        "",
        "## Evidence",
        "",
    ]
    for key, value in decision["evidence"].items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def _row_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| row | dataset | model | provider | repo | task | ctx | v1 | v2 | EAC | actual | category | diff |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['row_id']} | {row['dataset']} | {row['model']} | {row['provider']} | {row['repository']} | "
            f"{row['category']} | {row['context_budget']} | {row['compatibility_v1_score']:.6f} | "
            f"{row['compatibility_v2_score']:.6f} | {row['eac_score']:.6f} | {row['actual_outcome']} | "
            f"{row['prediction_agreement_category']} | {row['eac_minus_compatibility_v2']:.6f} |"
        )
    return "\n".join(lines)


def _group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "row_count": len(rows),
        "success_rate": _success_rate(rows),
        "dominant_models": _top_counts(rows, "model"),
        "dominant_providers": _top_counts(rows, "provider"),
        "dominant_repositories": _top_counts(rows, "repository"),
        "dominant_task_categories": _top_counts(rows, "category"),
        "context_budgets": _numeric_summary([row["context_budget"] for row in rows]),
        "mean_scores": {
            "compatibility_v2": _mean([row["compatibility_v2_score"] for row in rows]),
            "eac": _mean([row["eac_score"] for row in rows]),
            "difference_eac_minus_v2": _mean([row["eac_minus_compatibility_v2"] for row in rows]),
        },
    }


def _raw_rows_by_id(path: str | Path) -> dict[str, dict[str, Any]]:
    raw = {}
    file = Path(path)
    if not file.exists():
        return raw
    for index, line in enumerate(file.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            row_id = str(row.get("row_id") or row.get("dedupe_key") or f"live-{index}")
            raw[row_id] = row
    return raw


def _row_meta_by_id(rows: Iterable[CompatibilityV2Row]) -> dict[str, dict[str, Any]]:
    return {
        row.row_id: {
            "repository": row.repository,
            "provider_type": row.provider_type,
            "timestamp": row.timestamp.isoformat() if row.timestamp else "",
        }
        for row in rows
    }


def _extract_latency(row: dict[str, Any]) -> float | None:
    for key in ("latency_ms", "duration_ms", "elapsed_ms", "response_time_ms"):
        if _is_number(row.get(key)):
            return round(float(row[key]), 6)
    return None


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


def _dedupe_dict_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for row in rows:
        if row["row_id"] in seen:
            continue
        seen.add(row["row_id"])
        deduped.append(row)
    return deduped


def _largest_disagreement_category(categories: dict[str, dict[str, Any]]) -> str:
    disagreement = {key: data for key, data in categories.items() if key in {"A", "B", "C", "D"}}
    if not disagreement:
        return ""
    key = max(disagreement, key=lambda item: disagreement[item]["row_count"])
    return f"{key}. {disagreement[key]['label']} ({disagreement[key]['row_count']} rows)"


def _disagreement_winner(rows: list[dict[str, Any]]) -> str:
    eac = sum(1 for row in rows if row["eac_correct"] and not row["compatibility_correct"])
    compatibility = sum(1 for row in rows if row["compatibility_correct"] and not row["eac_correct"])
    if eac > compatibility:
        return f"EAC ({eac} vs {compatibility})"
    if compatibility > eac:
        return f"Compatibility v2 ({compatibility} vs {eac})"
    return f"tie ({eac} vs {compatibility})"


def _blind_spot_interpretation(name: str) -> str:
    return {
        "compatibility_overpredicts_eac_correctly_warns": "Compatibility's main blind spot is treating model/task fit as enough when execution access is weak.",
        "eac_underpredicts_compatibility_succeeds": "EAC's main blind spot is undercounting successes from easy verification, accessible evidence, or unmeasured specialization.",
        "both_fail": "Both theories miss a failure mechanism inside nominally high-confidence rows.",
        "both_succeed": "Both theories agree on the easiest high-confidence region.",
    }.get(name, "No dominant blind spot found.")


def _top_counts(rows: list[dict[str, Any]], key: str, limit: int = 5) -> list[dict[str, Any]]:
    return _counter_payload([row.get(key, "") for row in rows if row.get(key, "")], limit=limit)


def _counter_payload(values: Iterable[Any], limit: int = 5) -> list[dict[str, Any]]:
    counter = Counter(str(value) for value in values if value not in (None, ""))
    total = sum(counter.values())
    return [
        {"value": value, "count": count, "share": round(count / total, 6) if total else 0.0}
        for value, count in counter.most_common(limit)
    ]


def _distribution_distance(left: list[Any], right: list[Any]) -> float:
    left_counter = Counter(str(value) for value in left if value not in (None, ""))
    right_counter = Counter(str(value) for value in right if value not in (None, ""))
    left_total = sum(left_counter.values())
    right_total = sum(right_counter.values())
    if not left_total or not right_total:
        return 0.0
    keys = set(left_counter) | set(right_counter)
    return 0.5 * sum(abs(left_counter[key] / left_total - right_counter[key] / right_total) for key in keys)


def _numeric_summary(values: list[float | int]) -> dict[str, float | int]:
    numeric = [float(value) for value in values if _is_number(value)]
    if not numeric:
        return {"count": 0, "mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
    ordered = sorted(numeric)
    midpoint = len(ordered) // 2
    median = ordered[midpoint] if len(ordered) % 2 else (ordered[midpoint - 1] + ordered[midpoint]) / 2
    return {
        "count": len(numeric),
        "mean": round(sum(numeric) / len(numeric), 6),
        "median": round(median, 6),
        "min": round(min(numeric), 6),
        "max": round(max(numeric), 6),
    }


def _pooled_std(left: list[float], right: list[float]) -> float:
    values = left + right
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _success_rate(rows: list[dict[str, Any]]) -> float:
    return round(sum(row["success"] for row in rows) / len(rows), 6) if rows else 0.0


def _mean(values: list[float]) -> float:
    numeric = [float(value) for value in values if _is_number(value)]
    return round(sum(numeric) / len(numeric), 6) if numeric else 0.0


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _format_counts(items: list[dict[str, Any]]) -> str:
    return ", ".join(f"{item['value']} ({item['count']})" for item in items) if items else "none"


def _format_numeric(summary: dict[str, Any]) -> str:
    return f"n={summary['count']}, mean={summary['mean']}, median={summary['median']}, min={summary['min']}, max={summary['max']}"


def _format_means(summary: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in summary.items())


def _format_variable_side(value: Any) -> str:
    if isinstance(value, list):
        return _format_counts(value)
    if isinstance(value, dict):
        return _format_numeric(value)
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze fixed EAC vs Compatibility theory disagreements.")
    parser.add_argument("--state-dir", default=".agent-hub", help="Agent-Hub state directory.")
    parser.add_argument("--json", action="store_true", help="Print output paths as JSON.")
    args = parser.parse_args(argv)
    paths = run_eac_compatibility_disagreement_analysis(args.state_dir)
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
    "CATEGORY_DEFINITIONS",
    "DECISION_THRESHOLD",
    "build_disagreement_payload",
    "run_eac_compatibility_disagreement_analysis",
]
