from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .telemetry import research_dir


def compute_triadic_compatibility(
    context_payload: dict[str, Any],
    model_payload: dict[str, Any],
    task_payload: dict[str, Any],
    shared_payload: dict[str, Any],
    model_task_payload: dict[str, Any],
) -> dict[str, Any]:
    models = model_payload.get("models") or {}
    tasks = task_payload.get("tasks") or {}
    contexts = context_payload.get("contexts") or {}
    mt = {(row["model"], row["task"]): row for row in model_task_payload.get("interactions", [])}
    model_positions = shared_payload.get("models") or {}
    task_positions = shared_payload.get("tasks") or {}
    rows = []
    for row in context_payload.get("rows", []):
        if not row.get("model"):
            continue
        model = row["model"]
        task = row["task_key"]
        context = contexts.get(row["context_id"], {})
        context_vector = context.get("raw_vector", {})
        model_vector = (models.get(model) or {}).get("raw_vector", {})
        task_vector = (tasks.get(task) or {}).get("raw_vector", {})
        model_score = _score(model_vector.get("validation_score.overall", model_vector.get("success_rate.overall", 0.0)))
        task_score = _score(task_vector.get("mean_effective", task_vector.get("observed_validation", 0.0)))
        context_score = _context_score(context_vector)
        model_task = _model_task_score(mt.get((model, task)), model_score, task_score)
        model_context = 1.0 / (1.0 + abs(_capacity(model_vector) - _context_load(context_vector)))
        task_context = 1.0 / (1.0 + abs(_task_context_need(task_vector) - context_score))
        radial_gap_extended = _extended_radial_gap(model_positions.get(model), task_positions.get(task), context.get("embedding_3d"))
        error_risk = _error_risk(row, context_vector, model_vector)
        additive = (model_score + task_score + context_score) / 3.0
        interaction = (model_task + model_context + task_context) / 3.0
        bottleneck = min(model_score, context_score, model_task)
        reliability_adjusted = interaction * (1.0 - error_risk)
        rows.append(
            {
                "model": model,
                "task": task,
                "context_id": row["context_id"],
                "repository": row["repository"],
                "task_type": row["task_type"],
                "context_percent": row["context_percent"],
                "success": 1.0 if row["success"] else 0.0,
                "validation_score": row["validation_score"],
                "failure": 1.0 if (not row["success"] or row["error"]) else 0.0,
                "model_score": round(model_score, 8),
                "task_score": round(task_score, 8),
                "context_score": round(context_score, 8),
                "model_task": round(model_task, 8),
                "model_context": round(model_context, 8),
                "task_context": round(task_context, 8),
                "error_risk": round(error_risk, 8),
                "additive": round(additive, 8),
                "interaction": round(interaction, 8),
                "radial_gap_extended": round(radial_gap_extended, 8),
                "bottleneck": round(bottleneck, 8),
                "reliability_adjusted": round(reliability_adjusted, 8),
            }
        )
    metric_names = ["additive", "interaction", "radial_gap_extended", "bottleneck", "reliability_adjusted"]
    summaries = {metric: _metric_summary(rows, metric) for metric in metric_names}
    best = max(summaries, key=lambda metric: summaries[metric]["success_correlation"]) if summaries else ""
    return {
        "object": "agent_hub.research.triadic_compatibility_metrics",
        "interaction_count": len(rows),
        "best_metric": best,
        "metrics": summaries,
        "rows": rows,
        "notes": [
            "All candidate formulas use model, task, context, and compatibility terms only.",
            "Reliability adjustment estimates error risk from context load, retries, timeout-prone latency, and model error rate.",
        ],
    }


def export_triadic_compatibility(
    state_dir: str | Path,
    context_payload: dict[str, Any],
    model_payload: dict[str, Any],
    task_payload: dict[str, Any],
    shared_payload: dict[str, Any],
    model_task_payload: dict[str, Any],
) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = compute_triadic_compatibility(context_payload, model_payload, task_payload, shared_payload, model_task_payload)
    json_path = directory / "triadic_compatibility_metrics.json"
    md_path = directory / "triadic_compatibility_metrics.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(triadic_compatibility_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def triadic_compatibility_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Triadic Compatibility Metrics",
        "",
        f"- Interactions: {payload['interaction_count']}",
        f"- Best metric by success correlation: `{payload['best_metric']}`",
        "",
        "| metric | success corr | validation corr | failure corr |",
        "| --- | --- | --- | --- |",
    ]
    for metric, row in payload["metrics"].items():
        lines.append(f"| {metric} | {row['success_correlation']} | {row['validation_correlation']} | {row['failure_correlation']} |")
    lines.append("")
    return "\n".join(lines)


def _metric_summary(rows: list[dict[str, Any]], metric: str) -> dict[str, float]:
    values = [row[metric] for row in rows]
    return {
        "success_correlation": round(_pearson(values, [row["success"] for row in rows]), 6),
        "validation_correlation": round(_pearson(values, [row["validation_score"] for row in rows]), 6),
        "failure_correlation": round(_pearson(values, [row["failure"] for row in rows]), 6),
    }


def _model_task_score(row: dict[str, Any] | None, model_score: float, task_score: float) -> float:
    if row:
        return _score(row.get("radial_gap", 0.0), invert=True)
    return (model_score + task_score) / 2.0


def _context_score(vector: dict[str, Any]) -> float:
    density = _score(float(vector.get("average_information_density") or 0.0) * 5000.0)
    budget = 1.0 / (1.0 + abs(float(vector.get("context_budget_percent") or 0.0) - 50.0) / 50.0)
    redundancy = 1.0 - _score(vector.get("redundancy_estimate", 0.0))
    return max(0.0, min(1.0, 0.45 * density + 0.35 * budget + 0.20 * redundancy))


def _capacity(vector: dict[str, Any]) -> float:
    return _score(float(vector.get("context_tolerance") or 0.0) + float(vector.get("context.max_tokens") or 0.0) / 12000.0)


def _context_load(vector: dict[str, Any]) -> float:
    return _score(float(vector.get("context_tokens") or 0.0) / 12000.0 + float(vector.get("redundancy_estimate") or 0.0))


def _task_context_need(vector: dict[str, Any]) -> float:
    return _score(float(vector.get("performance_spread") or 0.0) + float(vector.get("mean_failure") or 0.0))


def _extended_radial_gap(model: list[float] | None, task: list[float] | None, context: list[float] | None) -> float:
    if not model or not task:
        return 0.5
    context = context or [0.0, 0.0, 0.0]
    model_norm = _norm(model)
    task_norm = _norm(task)
    context_norm = _norm(context) / 5.0
    gap = abs(model_norm - task_norm) + abs(context_norm - ((model_norm + task_norm) / 2.0))
    return 1.0 / (1.0 + gap)


def _error_risk(row: dict[str, Any], context: dict[str, Any], model: dict[str, Any]) -> float:
    model_error = float(model.get("error_rate.overall") or 0.0)
    load = _context_load(context)
    redundancy = float(context.get("redundancy_estimate") or 0.0)
    overload = max(0.0, load - 0.65)
    return max(0.0, min(1.0, 0.45 * model_error + 0.30 * overload + 0.25 * redundancy))


def _score(value: Any, *, invert: bool = False) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    numeric = 1.0 / (1.0 + math.exp(-numeric))
    return 1.0 - numeric if invert else numeric


def _norm(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    ml = sum(left) / len(left)
    mr = sum(right) / len(right)
    numerator = sum((a - ml) * (b - mr) for a, b in zip(left, right))
    denom_l = math.sqrt(sum((a - ml) ** 2 for a in left))
    denom_r = math.sqrt(sum((b - mr) ** 2 for b in right))
    return numerator / (denom_l * denom_r) if denom_l and denom_r else 0.0


__all__ = ["compute_triadic_compatibility", "export_triadic_compatibility", "triadic_compatibility_markdown"]
