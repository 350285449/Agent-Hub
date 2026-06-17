from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .capability_margin import retrieval_selectivity_proxy, sigmoid
from .compatibility_v2 import metrics_payload
from .primitive_variable_analysis import (
    _clamp01,
    _corr,
    _linear_fit_predict,
    _log_norm,
    _mean,
    _r2,
    attach_primitive_variables,
    build_payload,
    load_cloud_rows,
    theory_score_table,
)
from .telemetry import research_dir


EVIDENCE_FILES = {
    "dataset": "evidence_access_dataset.json",
    "report": "evidence_access_report.md",
    "old_vs_new": "oldA_vs_newA.md",
    "primitive_reanalysis": "primitive_reanalysis_with_evidence_access.md",
    "theory_impact": "evidence_access_theory_impact.md",
    "verdict": "evidence_access_measurement_verdict.md",
}

COMPONENT_WEIGHTS = {
    "E1": 0.18,
    "E2": 0.12,
    "E3": 0.10,
    "E4": 0.12,
    "E5": 0.12,
    "E6": 0.10,
    "E7": 0.08,
    "E8": 0.06,
    "E9": 0.08,
    "context_efficiency": 0.04,
}

PATH_RE = re.compile(r"(?:(?:\.agent-hub|agent_hub|tests|benchmarks|docs|scripts|sdk|vscode-extension|[\w.-]+/)[\w./-]+\.[A-Za-z0-9]+)")
ACTION_WORDS = ("patch", "edit", "fix", "implement", "change", "update", "test", "verify", "regression", "validation")


def run_evidence_access_measurement(state_dir: str | Path = ".agent-hub") -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    dataset = build_evidence_access_dataset(state_dir)
    old_new = compare_old_new_access(dataset["rows"])
    primitive_payload = primitive_reanalysis_payload(state_dir, dataset["rows"])
    theory_impact = evidence_access_theory_impact_payload(state_dir, dataset["rows"])
    verdict = measurement_verdict(dataset, old_new, primitive_payload)

    paths = {key: directory / filename for key, filename in EVIDENCE_FILES.items()}
    paths["dataset"].write_text(json.dumps(dataset, indent=2, sort_keys=True), encoding="utf-8")
    paths["report"].write_text(evidence_access_report_markdown(dataset), encoding="utf-8")
    paths["old_vs_new"].write_text(old_vs_new_markdown(old_new), encoding="utf-8")
    paths["primitive_reanalysis"].write_text(primitive_reanalysis_markdown(primitive_payload), encoding="utf-8")
    paths["theory_impact"].write_text(theory_impact_markdown(theory_impact), encoding="utf-8")
    paths["verdict"].write_text(measurement_verdict_markdown(verdict), encoding="utf-8")
    return paths


def build_evidence_access_dataset(state_dir: str | Path = ".agent-hub") -> dict[str, Any]:
    rows = attach_primitive_variables(load_cloud_rows(state_dir))
    labels = load_benchmark_labels(state_dir)
    max_tokens = max([float(row.get("context_tokens") or 0.0) for row in rows] + [1.0])
    max_files = max([float(row.get("selected_file_count") or row.get("file_count") or 0.0) for row in rows] + [1.0])
    measured = [measure_evidence_access_row(row, labels, max_tokens=max_tokens, max_files=max_files) for row in rows]
    return {
        "object": "agent_hub.research.evidence_access_dataset",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "cloud_models_only",
        "policy": {
            "theory_formulas_modified": False,
            "prediction_metrics_tuned": False,
            "K_unchanged": True,
            "rho_unchanged": True,
            "old_A_replaced_only_for_measurement_reanalysis": True,
            "gold_patch_files_are_benchmark_side_labels": True,
            "model_output_used_only_for_noticed_and_actionability_proxies": True,
        },
        "component_weights": COMPONENT_WEIGHTS,
        "row_count": len(measured),
        "summary": summarize_evidence_rows(measured),
        "rows": measured,
    }


def measure_evidence_access_row(row: dict[str, Any], labels: dict[str, dict[str, Any]], *, max_tokens: float, max_files: float) -> dict[str, Any]:
    selected = _path_list(row.get("selected_files") or row.get("context_files") or [])
    selected_scores = _score_map(row, selected)
    selected_reasons = _reason_map(row, selected)
    task_id = str(row.get("task_id") or row.get("task") or "")
    label = labels.get(task_id, {})
    expected = _path_list(_first_present(row, "benchmark_expected_files", "expected_files", "focus_files") or label.get("expected_files") or [])
    relevant = _path_list(_first_present(row, "benchmark_relevant_files", "relevant_files") or label.get("relevant_files") or expected)
    gold = _path_list(_first_present(row, "gold_patch_files", "benchmark_gold_patch_files") or label.get("gold_patch_files") or [])
    decisive = _dedupe(expected or gold or relevant)
    edited = _path_list(_first_present(row, "files_actually_edited", "edited_files", "files_edited", "modified_files", "patch_files") or [])
    referenced = _path_list(_first_present(row, "files_referenced_in_output", "referenced_files", "output_referenced_files") or [])
    referenced = _dedupe(referenced + _paths_from_output(row.get("output_preview", ""), selected + decisive + relevant))
    verifiers = _path_list(_first_present(row, "tests_or_verifiers_triggered", "tests_triggered", "verifiers_triggered", "commands_run") or [])
    verifiers = _dedupe(verifiers + _path_list(label.get("tests") or []))
    token_counts = _context_token_counts(row, selected)

    components = compute_components(
        selected=selected,
        decisive=decisive,
        relevant=relevant,
        edited=edited,
        referenced=referenced,
        verifiers=verifiers,
        token_counts=token_counts["by_file"],
        output=str(row.get("output_preview") or ""),
    )
    new_a = aggregate_evidence_access(components)
    old_a = old_accessibility_proxy(row, max_tokens=max_tokens, max_files=max_files)
    trace = {
        "row_id": str(row.get("row_id") or row.get("dedupe_key") or ""),
        "model": str(row.get("model") or ""),
        "provider": str(row.get("provider") or row.get("provider_type") or ""),
        "repository": str(row.get("repository") or ""),
        "task_id": task_id,
        "ordered_selected_files": selected,
        "selected_file_scores": selected_scores,
        "selected_file_reasons": selected_reasons,
        "context_token_counts": token_counts,
        "benchmark_expected_files": expected,
        "benchmark_relevant_files": relevant,
        "gold_patch_files_if_available": gold,
        "gold_patch_label_source": "benchmark_side" if gold else "unavailable",
        "files_actually_edited": edited,
        "files_referenced_in_output_if_available": referenced,
        "tests_or_verifiers_triggered": verifiers,
        "success": bool(row.get("success")),
    }
    return {
        **trace,
        "source": str(row.get("source") or ""),
        "category": str(row.get("task_type") or row.get("category") or ""),
        "context_budget": float(row.get("context_budget") or 0.0),
        "context_tokens": float(row.get("context_tokens") or 0.0),
        "selected_file_count": len(selected),
        "old_accessibility_proxy": round(old_a, 6),
        "new_evidence_access_A": round(new_a, 6),
        "K": round(float(row.get("K") or 0.0), 6),
        "rho": round(float(row.get("rho") or 0.0), 6),
        "components": components,
        "component_availability": {key: value is not None for key, value in components.items()},
        "label_source": "benchmark_task" if label else ("row" if decisive or relevant else "unavailable"),
        "non_leaky_labels": True,
    }


def compute_components(
    *,
    selected: list[str],
    decisive: list[str],
    relevant: list[str],
    edited: list[str],
    referenced: list[str],
    verifiers: list[str],
    token_counts: dict[str, float],
    output: str,
) -> dict[str, float | None]:
    selected_set = set(selected)
    decisive_set = set(decisive)
    relevant_set = set(relevant)
    decisive_hits = selected_set & decisive_set
    relevant_hits = selected_set & relevant_set
    e1 = _safe_ratio(len(decisive_hits), len(decisive)) if decisive else None
    e2 = _first_rank_score(selected, decisive_set) if decisive else None
    e3 = _token_share(decisive_hits, token_counts) if decisive and selected else None
    e4 = _safe_ratio(len(relevant_hits), len(selected)) if selected and relevant else None
    e5 = _safe_ratio(len(relevant_hits), len(relevant)) if relevant else None
    noticed_decisive = decisive_hits & set(referenced)
    e6 = _safe_ratio(len(noticed_decisive), len(decisive_hits)) if decisive_hits else None
    e7 = _distance_score(selected, decisive_hits, set(edited)) if decisive_hits and edited else None
    e8 = _distance_score(selected, decisive_hits, set(verifiers)) if decisive_hits and verifiers else None
    action_cues = _action_cue_score(output, verifiers)
    available_action_parts = [value for value in (e6, e7, e8, action_cues) if value is not None]
    e9 = _mean(available_action_parts) if available_action_parts else None
    e10 = 1.0 - e4 if e4 is not None else (0.0 if not selected else None)
    return {
        "E1": _round_or_none(e1),
        "E2": _round_or_none(e2),
        "E3": _round_or_none(e3),
        "E4": _round_or_none(e4),
        "E5": _round_or_none(e5),
        "E6": _round_or_none(e6),
        "E7": _round_or_none(e7),
        "E8": _round_or_none(e8),
        "E9": _round_or_none(e9),
        "E10": _round_or_none(e10),
    }


def aggregate_evidence_access(components: dict[str, float | None]) -> float:
    weighted = []
    for name, weight in COMPONENT_WEIGHTS.items():
        if name == "context_efficiency":
            value = components.get("E10")
            score = None if value is None else 1.0 - float(value)
        else:
            value = components.get(name)
            score = None if value is None else float(value)
        if score is not None:
            weighted.append((weight, _clamp01(score)))
    if not weighted:
        return 0.0
    score = _clamp01(sum(weight * score for weight, score in weighted) / sum(weight for weight, _score in weighted))
    grounded = any(components.get(name) is not None for name in ("E1", "E4", "E5"))
    return score if grounded else min(score, 0.35)


def load_benchmark_labels(state_dir: str | Path) -> dict[str, dict[str, Any]]:
    root = _workspace_root(state_dir)
    labels: dict[str, dict[str, Any]] = {}
    research_tasks = research_dir(state_dir) / "benchmark_tasks.json"
    if research_tasks.exists():
        try:
            payload = json.loads(research_tasks.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = []
        for task in payload if isinstance(payload, list) else []:
            task_id = str(task.get("task_id") or task.get("id") or "")
            if task_id:
                labels[task_id] = {
                    "expected_files": _path_list(task.get("focus_files") or task.get("expected_files") or []),
                    "relevant_files": _path_list(task.get("relevant_files") or task.get("focus_files") or []),
                    "tests": _path_list(task.get("tests") or []),
                    "gold_patch_files": _path_list(task.get("gold_patch_files") or []),
                }
    benchmark_dir = root / "benchmarks"
    for path in benchmark_dir.glob("*/*.jsonl") if benchmark_dir.exists() else []:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    task = json.loads(line)
                except json.JSONDecodeError:
                    continue
                task_id = str(task.get("task_id") or task.get("id") or "")
                if not task_id:
                    continue
                labels.setdefault(task_id, {})
                labels[task_id].update(
                    {
                        "expected_files": _path_list(task.get("expected_files") or task.get("focus_files") or []),
                        "relevant_files": _path_list(task.get("relevant_files") or task.get("expected_files") or task.get("focus_files") or []),
                        "tests": _path_list(task.get("tests") or []),
                        "gold_patch_files": _path_list(task.get("gold_patch_files") or []),
                    }
                )
    return labels


def compare_old_new_access(rows: list[dict[str, Any]]) -> dict[str, Any]:
    old = [float(row["old_accessibility_proxy"]) for row in rows]
    new = [float(row["new_evidence_access_A"]) for row in rows]
    success = [1.0 if row["success"] else 0.0 for row in rows]
    disagreement = []
    for row in rows:
        delta = float(row["old_accessibility_proxy"]) - float(row["new_evidence_access_A"])
        if abs(delta) >= 0.35:
            disagreement.append(
                {
                    "row_id": row["row_id"],
                    "model": row["model"],
                    "task_id": row["task_id"],
                    "old_A": row["old_accessibility_proxy"],
                    "new_A": row["new_evidence_access_A"],
                    "delta_old_minus_new": round(delta, 6),
                    "selected_files": row["selected_file_count"],
                    "decisive_coverage": row["components"].get("E1"),
                    "success": row["success"],
                }
            )
    disagreement.sort(key=lambda item: abs(item["delta_old_minus_new"]), reverse=True)
    high_old_low_new = [item for item in disagreement if item["old_A"] >= 0.65 and item["new_A"] <= 0.35]
    low_old_high_new = [item for item in disagreement if item["old_A"] <= 0.35 and item["new_A"] >= 0.65]
    return {
        "rows": len(rows),
        "old_new_correlation": round(_corr(old, new), 6),
        "old_A_success_correlation": round(_corr(old, success), 6),
        "new_A_success_correlation": round(_corr(new, success), 6),
        "old_A_r2": round(max(0.0, _r2(success, _linear_fit_predict([[value] for value in old], success))), 6),
        "new_A_r2": round(max(0.0, _r2(success, _linear_fit_predict([[value] for value in new], success))), 6),
        "mean_old_A": round(_mean(old), 6),
        "mean_new_A": round(_mean(new), 6),
        "disagreement_cases": disagreement[:20],
        "high_old_low_new": high_old_low_new[:10],
        "low_old_high_new": low_old_high_new[:10],
    }


def primitive_reanalysis_payload(state_dir: str | Path, evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    base = attach_primitive_variables(load_cloud_rows(state_dir))
    by_id = {row["row_id"]: row for row in evidence_rows if row.get("row_id")}
    replaced = []
    for row in base:
        item = dict(row)
        evidence = by_id.get(str(row.get("row_id") or ""))
        if evidence:
            item["old_A"] = item["A"]
            item["A"] = evidence["new_evidence_access_A"]
        replaced.append(item)
    payload = build_payload(replaced, theory_score_table(replaced))
    old_payload = build_payload(base, theory_score_table(base))
    payload["old_primitive_outcome_r2"] = old_payload["primitive_outcome_r2"]
    payload["old_full_observed_outcome_r2"] = old_payload["full_observed_outcome_r2"]
    payload["old_missing"] = old_payload["missing"]
    payload["delta_primitive_r2"] = round(payload["primitive_outcome_r2"] - old_payload["primitive_outcome_r2"], 6)
    payload["delta_explainable_residual"] = round(
        payload["missing"]["explainable_residual_after_primitives"] - old_payload["missing"]["explainable_residual_after_primitives"],
        6,
    )
    return payload


def evidence_access_theory_impact_payload(state_dir: str | Path, evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    margin_path = research_dir(state_dir) / "capability_margin_dataset.json"
    by_id = {row["row_id"]: row for row in evidence_rows if row.get("row_id")}
    if not margin_path.exists():
        return {"rows": 0, "available": False, "reason": "capability_margin_dataset.json unavailable"}
    try:
        payload = json.loads(margin_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"rows": 0, "available": False, "reason": "capability_margin_dataset.json invalid"}
    rows = []
    for row in payload.get("rows", []):
        evidence = by_id.get(str(row.get("row_id") or ""))
        if not evidence:
            continue
        old_a = max(1e-6, float(row.get("A") or evidence.get("old_accessibility_proxy") or 0.0))
        new_a = float(evidence["new_evidence_access_A"])
        old_eac = float(row.get("eac", 0.0))
        old_margin = float(row.get("capability_margin_probability", 0.0))
        old_retrieval = float(row.get("retrieval_selectivity", 0.0))
        new_eac = _clamp01(old_eac * (new_a / old_a))
        new_margin = sigmoid(math.log((float(row.get("K", 0.0)) * float(row.get("rho", 0.0)) * new_a * float(row.get("V", 0.0)) * float(row.get("B", 0.0)) + 1e-6) / (float(row.get("D", 0.0)) + 1e-6)))
        new_retrieval = retrieval_selectivity_proxy(new_a, row.get("context_budget", 0))
        outcome = float(row.get("outcome", 0.0))
        rows.append(
            {
                "row_id": row.get("row_id", ""),
                "outcome": outcome,
                "old_A": round(old_a, 6),
                "new_A": round(new_a, 6),
                "EAC_old": round(old_eac, 6),
                "EAC_newA_substitution": round(new_eac, 6),
                "Retrieval_Selectivity_old": round(old_retrieval, 6),
                "Retrieval_Selectivity_newA_substitution": round(new_retrieval, 6),
                "Route_Friction_unchanged": round(float(row.get("route_friction", 0.0)), 6),
                "Compatibility_v2_unchanged": round(float(row.get("compatibility_v2", 0.0)), 6),
                "Capability_Margin_old": round(old_margin, 6),
                "Capability_Margin_newA_substitution": round(new_margin, 6),
            }
        )
    actual = [row["outcome"] for row in rows]
    comparisons = {}
    for label, field in (
        ("EAC old", "EAC_old"),
        ("EAC new A substitution", "EAC_newA_substitution"),
        ("Retrieval Selectivity old", "Retrieval_Selectivity_old"),
        ("Retrieval Selectivity new A substitution", "Retrieval_Selectivity_newA_substitution"),
        ("Route Friction unchanged", "Route_Friction_unchanged"),
        ("Compatibility v2 unchanged", "Compatibility_v2_unchanged"),
        ("Capability Margin old", "Capability_Margin_old"),
        ("Capability Margin new A substitution", "Capability_Margin_newA_substitution"),
    ):
        comparisons[label] = metrics_payload(actual, [row[field] for row in rows]) if rows else {}
    residual_old = [a - p for a, p in zip(actual, _linear_fit_predict([[row["Compatibility_v2_unchanged"]] for row in rows], actual))]
    residual_new_a_corr = _corr([row["new_A"] for row in rows], residual_old)
    return {
        "available": True,
        "rows": len(rows),
        "policy": "Existing formulas are not modified in source; this is a substitution audit for measurement impact only.",
        "comparisons": comparisons,
        "compatibility_residual_correlation_with_new_A": round(residual_new_a_corr, 6),
        "sample_rows": rows[:20],
    }


def summarize_evidence_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    success = [1.0 if row["success"] else 0.0 for row in rows]
    new_a = [float(row["new_evidence_access_A"]) for row in rows]
    components = {}
    for name in [f"E{i}" for i in range(1, 11)]:
        values = [float(row["components"][name]) for row in rows if row["components"].get(name) is not None]
        components[name] = {
            "available_rows": len(values),
            "mean": round(_mean(values), 6),
            "success_correlation": round(_corr(values, [success[i] for i, row in enumerate(rows) if row["components"].get(name) is not None]), 6) if values else 0.0,
        }
    strongest = max(components, key=lambda name: abs(components[name]["success_correlation"])) if components else ""
    return {
        "rows": len(rows),
        "labeled_rows": sum(1 for row in rows if row["label_source"] != "unavailable"),
        "success_rate": round(_mean(success), 6),
        "new_A_mean": round(_mean(new_a), 6),
        "new_A_success_correlation": round(_corr(new_a, success), 6),
        "components": components,
        "strongest_component_by_abs_success_correlation": strongest,
    }


def old_accessibility_proxy(row: dict[str, Any], *, max_tokens: float, max_files: float) -> float:
    access_budget = _clamp01(float(row.get("context_budget") or row.get("context_percent") or 0.0) / 100.0)
    access_tokens = _log_norm(float(row.get("context_tokens") or 0.0), max_tokens)
    access_files = _log_norm(float(row.get("selected_file_count") or row.get("file_count") or 0.0), max_files)
    return _clamp01(0.50 * access_budget + 0.35 * access_tokens + 0.15 * access_files)


def measurement_verdict(dataset: dict[str, Any], old_new: dict[str, Any], primitive: dict[str, Any]) -> dict[str, Any]:
    components = dataset["summary"]["components"]
    strongest = dataset["summary"]["strongest_component_by_abs_success_correlation"]
    residual_shrinks = primitive["missing"]["explainable_residual_after_primitives"] < primitive["old_missing"]["explainable_residual_after_primitives"]
    new_better = old_new["new_A_r2"] > old_new["old_A_r2"] or abs(old_new["new_A_success_correlation"]) > abs(old_new["old_A_success_correlation"])
    return {
        "old_A_mostly_context_volume": True,
        "direct_evidence_access_explains_more_variance": bool(new_better),
        "residual_X_shrinks": bool(residual_shrinks),
        "strongest_evidence_access_component": strongest,
        "strongest_component_success_correlation": components.get(strongest, {}).get("success_correlation", 0.0),
        "A_better_primitive_candidate": bool(new_better or residual_shrinks),
        "weakest_remaining_measurement": "A" if dataset["summary"]["labeled_rows"] < dataset["summary"]["rows"] * 0.75 else "K/rho need prospective non-outcome priors",
        "new_K_rho_A_explained_variance": primitive["primitive_outcome_r2"],
        "old_K_rho_A_explained_variance": primitive["old_primitive_outcome_r2"],
    }


def evidence_access_report_markdown(dataset: dict[str, Any]) -> str:
    summary = dataset["summary"]
    lines = [
        "# Evidence Access Measurement",
        "",
        f"- Scope: {dataset['scope']}",
        f"- Rows: {summary['rows']}",
        f"- Rows with benchmark-side labels: {summary['labeled_rows']}",
        f"- New A mean: {summary['new_A_mean']}",
        f"- New A success correlation: {summary['new_A_success_correlation']}",
        f"- Strongest component: `{summary['strongest_component_by_abs_success_correlation']}`",
        "",
        "| component | available rows | mean | success corr |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, row in summary["components"].items():
        lines.append(f"| {name} | {row['available_rows']} | {row['mean']} | {row['success_correlation']} |")
    lines.extend(["", "Gold patch labels, when present, are marked as benchmark-side labels and are not inferred from output.", ""])
    return "\n".join(lines)


def old_vs_new_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Old A vs New Evidence-Access A",
        "",
        f"- Rows: {payload['rows']}",
        f"- Old/new A correlation: {payload['old_new_correlation']}",
        f"- Old A success correlation: {payload['old_A_success_correlation']}",
        f"- New A success correlation: {payload['new_A_success_correlation']}",
        f"- Old A linear R2: {payload['old_A_r2']}",
        f"- New A linear R2: {payload['new_A_r2']}",
        f"- Mean old A: {payload['mean_old_A']}",
        f"- Mean new A: {payload['mean_new_A']}",
        "",
        "## High Old A, Low New A",
        "",
        _case_table(payload["high_old_low_new"]),
        "",
        "## Low Old A, High New A",
        "",
        _case_table(payload["low_old_high_new"]),
        "",
        "## Largest Disagreements",
        "",
        _case_table(payload["disagreement_cases"][:10]),
        "",
    ]
    return "\n".join(lines)


def primitive_reanalysis_markdown(payload: dict[str, Any]) -> str:
    m = payload["missing"]
    return "\n".join(
        [
            "# Primitive Reanalysis With Evidence Access",
            "",
            "K and rho are unchanged. Old A is replaced by direct evidence-access A for this measurement audit only.",
            "",
            f"- Old K+rho+A explained variance: {payload['old_primitive_outcome_r2']}",
            f"- New K+rho+A explained variance: {payload['primitive_outcome_r2']}",
            f"- Delta explained variance: {payload['delta_primitive_r2']}",
            f"- Old explainable residual beyond primitives: {payload['old_missing']['explainable_residual_after_primitives']}",
            f"- New explainable residual beyond primitives: {m['explainable_residual_after_primitives']}",
            f"- Residual X remains necessary by threshold: {m['fourth_primitive_required']}",
            "",
            "## Information Accounting",
            "",
            "| variables | normalized MI | linear R2 | correlation |",
            "| --- | ---: | ---: | ---: |",
            *[f"| {row['variables']} | {row['normalized_mi']} | {row['r2']} | {row['correlation']} |" for row in payload["information_accounting"]],
            "",
        ]
    )


def theory_impact_markdown(payload: dict[str, Any]) -> str:
    if not payload.get("available"):
        return f"# Evidence Access Theory Impact\n\nUnavailable: {payload.get('reason', 'unknown')}.\n"
    lines = [
        "# Evidence Access Theory Impact",
        "",
        f"- Rows: {payload['rows']}",
        f"- Policy: {payload['policy']}",
        f"- Compatibility residual correlation with new A: {payload['compatibility_residual_correlation_with_new_A']}",
        "",
        "| score | AUC | Brier | R2 | corr |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, metrics in payload["comparisons"].items():
        lines.append(f"| {name} | {metrics.get('auc', 0.0):.6f} | {metrics.get('brier_score', 0.0):.6f} | {metrics.get('r2', 0.0):.6f} | {metrics.get('correlation', 0.0):.6f} |")
    lines.append("")
    return "\n".join(lines)


def measurement_verdict_markdown(verdict: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Evidence Access Measurement Verdict",
            "",
            f"1. Was old A mostly measuring context volume? {verdict['old_A_mostly_context_volume']}.",
            f"2. Does direct evidence access explain more variance? {verdict['direct_evidence_access_explains_more_variance']}.",
            f"3. Does residual X shrink? {verdict['residual_X_shrinks']}.",
            f"4. Which evidence-access component is strongest? `{verdict['strongest_evidence_access_component']}` (corr={verdict['strongest_component_success_correlation']}).",
            f"5. Is A now a better primitive candidate? {verdict['A_better_primitive_candidate']}.",
            f"6. What remaining measurement is weakest: K, rho, or A? {verdict['weakest_remaining_measurement']}.",
            "",
            f"- Old K+rho+A explained variance: {verdict['old_K_rho_A_explained_variance']}",
            f"- New K+rho+A explained variance: {verdict['new_K_rho_A_explained_variance']}",
            "",
        ]
    )


def _context_token_counts(row: dict[str, Any], selected: list[str]) -> dict[str, Any]:
    raw = row.get("context_token_counts") or row.get("file_token_counts") or {}
    if isinstance(raw, dict) and any(isinstance(value, (int, float)) for value in raw.values()):
        by_file = {path: float(raw.get(path, raw.get(path.replace("/", "\\"), 0.0)) or 0.0) for path in selected}
        total = sum(by_file.values()) or float(row.get("context_tokens") or 0.0)
        return {"total": round(total, 6), "by_file": by_file}
    total = float(row.get("context_tokens") or row.get("context_token_count") or 0.0)
    each = total / len(selected) if selected else 0.0
    return {"total": round(total, 6), "by_file": {path: round(each, 6) for path in selected}}


def _score_map(row: dict[str, Any], selected: list[str]) -> dict[str, float]:
    raw = row.get("selected_file_scores") or row.get("file_scores") or {}
    if isinstance(raw, dict):
        return {path: float(raw.get(path, raw.get(path.replace("/", "\\"), 0.0)) or 0.0) for path in selected}
    return {path: round(1.0 - (index / max(1, len(selected))), 6) for index, path in enumerate(selected)}


def _reason_map(row: dict[str, Any], selected: list[str]) -> dict[str, list[str]]:
    raw = row.get("selected_file_reasons") or row.get("file_reasons") or {}
    if isinstance(raw, dict):
        return {path: [str(reason) for reason in _as_list(raw.get(path, raw.get(path.replace("/", "\\"), [])))] for path in selected}
    return {path: [] for path in selected}


def _first_rank_score(selected: list[str], targets: set[str]) -> float:
    for index, path in enumerate(selected):
        if path in targets:
            if len(selected) <= 1:
                return 1.0
            return _clamp01(1.0 - index / (len(selected) - 1))
    return 0.0


def _token_share(targets: set[str], token_counts: dict[str, float]) -> float:
    total = sum(token_counts.values())
    if total <= 0.0:
        return _safe_ratio(len(targets), len(token_counts))
    return _safe_ratio(sum(token_counts.get(path, 0.0) for path in targets), total)


def _distance_score(selected: list[str], evidence: set[str], action_files: set[str]) -> float:
    if evidence & action_files:
        return 1.0
    rank = {path: index for index, path in enumerate(selected)}
    evidence_ranks = [rank[path] for path in evidence if path in rank]
    action_ranks = [rank[path] for path in action_files if path in rank]
    if not evidence_ranks or not action_ranks:
        return 0.0
    distance = min(abs(a - b) for a in evidence_ranks for b in action_ranks)
    return _clamp01(1.0 - distance / max(1, len(selected) - 1))


def _action_cue_score(output: str, verifiers: list[str]) -> float:
    text = output.lower()
    cue_hits = sum(1 for word in ACTION_WORDS if word in text)
    verifier_bonus = 1 if verifiers else 0
    return _clamp01((cue_hits + verifier_bonus) / 6.0)


def _paths_from_output(output: Any, candidates: list[str]) -> list[str]:
    text = str(output or "")
    found = {_norm_path(match.group(0)) for match in PATH_RE.finditer(text)}
    for path in candidates:
        if path and path in text.replace("\\", "/"):
            found.add(path)
    return sorted(found)


def _case_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No cases under the configured thresholds."
    lines = ["| row | model | task | old A | new A | delta | E1 | success |", "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |"]
    for row in rows:
        lines.append(f"| {row['row_id']} | {row['model']} | {row['task_id']} | {row['old_A']} | {row['new_A']} | {row['delta_old_minus_new']} | {row['decisive_coverage']} | `{row['success']}` |")
    return "\n".join(lines)


def _workspace_root(state_dir: str | Path) -> Path:
    path = Path(state_dir)
    if path.name == ".agent-hub":
        return path.parent if str(path.parent) else Path(".")
    return path


def _path_list(value: Any) -> list[str]:
    return _dedupe(_norm_path(item) for item in _as_list(value) if str(item or "").strip())


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if isinstance(value, str):
        if not value.strip():
            return []
        return [part.strip() for part in value.split(",")] if "," in value else [value.strip()]
    return [value]


def _norm_path(value: Any) -> str:
    return str(value).strip().replace("\\", "/").lstrip("./")


def _dedupe(values: Iterable[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) not in (None, "", []):
            return row.get(key)
    return None


def _safe_ratio(numerator: float, denominator: float) -> float:
    return _clamp01(float(numerator) / float(denominator)) if denominator else 0.0


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(_clamp01(float(value)), 6)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure direct evidence access for cloud model research rows.")
    parser.add_argument("--state-dir", default=".agent-hub", help="Agent-Hub state directory.")
    parser.add_argument("--json", action="store_true", help="Print output paths as JSON.")
    args = parser.parse_args(argv)
    paths = run_evidence_access_measurement(args.state_dir)
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
    "EVIDENCE_FILES",
    "aggregate_evidence_access",
    "build_evidence_access_dataset",
    "compare_old_new_access",
    "compute_components",
    "evidence_access_theory_impact_payload",
    "load_benchmark_labels",
    "measure_evidence_access_row",
    "primitive_reanalysis_payload",
    "run_evidence_access_measurement",
]
