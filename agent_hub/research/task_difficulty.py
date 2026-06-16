from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .fundamental_lab import load_research_observations
from .quantity_tests import clamp01, mean, pearson, stdev


def load_difficulty_observations(state_dir: str) -> list[dict[str, Any]]:
    allowed = {
        "runs.jsonl",
        "experiments.jsonl",
        "real_model_validation_results.jsonl",
        "multi_model_context_scaling.json",
        "dataset.csv",
    }
    return [row for row in load_research_observations(state_dir) if row.get("source") in allowed]


def task_signature(row: dict[str, Any]) -> str:
    repo = str(row.get("repo") or "unknown")
    task_type = str(row.get("task_type") or "unknown")
    raw = str(row.get("task_id") or "")
    base = re.sub(r"-(0|25|50|75|100)$", "", raw)
    base = re.sub(r"-context-\d+$", "", base)
    base = re.sub(r"-default_context-\d+$", "", base)
    if row.get("source") == "multi_model_context_scaling.json":
        context = int(float(row.get("context_percent") or 0.0))
        base = f"{repo}-{task_type}-context-{context}"
    if not raw or row.get("source") == "dataset.csv":
        bucket = int(float(row.get("context_percent") or 0.0) // 25)
        base = f"{task_type}-context-bucket-{bucket}"
    return f"{repo}::{task_type}::{base}"


def build_task_model_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        grouped[task_signature(row)][str(row.get("model") or "unknown")].append(row)
    tasks = {}
    model_totals: dict[str, list[float]] = defaultdict(list)
    for task, model_rows in sorted(grouped.items()):
        cells = {}
        for model, items in sorted(model_rows.items()):
            validation = mean(float(item.get("validation_score") or 0.0) for item in items)
            success_rate = mean(1.0 if item.get("success") else 0.0 for item in items)
            effective = 0.5 * validation + 0.5 * success_rate
            cells[model] = {
                "runs": len(items),
                "success_rate": round(success_rate, 6),
                "validation_score": round(validation, 6),
                "effective_performance": round(effective, 6),
                "failure_rate": round(1.0 - success_rate, 6),
                "validation_deficit": round(1.0 - validation, 6),
            }
            model_totals[model].append(effective)
        tasks[task] = {
            "models": cells,
            "model_count": len(cells),
            "runs": sum(cell["runs"] for cell in cells.values()),
        }
    model_strength = {model: mean(values) for model, values in model_totals.items()}
    return {
        "object": "agent_hub.research.difficulty_task_matrix",
        "tasks": tasks,
        "models": {
            model: {
                "observed_tasks": len(values),
                "mean_effective_performance": round(model_strength[model], 6),
            }
            for model, values in sorted(model_totals.items())
        },
        "multi_model_task_count": sum(1 for task in tasks.values() if task["model_count"] >= 2),
    }


def compute_candidate_difficulty_metrics(matrix: dict[str, Any]) -> dict[str, Any]:
    model_strength = {
        model: float(row.get("mean_effective_performance") or 0.0)
        for model, row in matrix.get("models", {}).items()
    }
    task_rows = {}
    for task, row in matrix.get("tasks", {}).items():
        cells = list((row.get("models") or {}).items())
        performances = [float(cell["effective_performance"]) for _, cell in cells]
        success_rates = [float(cell["success_rate"]) for _, cell in cells]
        validation_scores = [float(cell["validation_score"]) for _, cell in cells]
        adjusted = []
        for model, cell in cells:
            strength = model_strength.get(model, 0.5)
            adjusted.append(clamp01(0.5 + strength - float(cell["effective_performance"])))
        metrics = {
            "mean_failure_rate": mean(1.0 - value for value in success_rates),
            "mean_validation_deficit": mean(1.0 - value for value in validation_scores),
            "inverse_normalized_success": 1.0 - mean(success_rates),
            "model_adjusted_difficulty": mean(adjusted),
            "performance_variance": stdev(performances) ** 2,
        }
        consensus = (
            0.30 * metrics["mean_failure_rate"]
            + 0.30 * metrics["mean_validation_deficit"]
            + 0.20 * metrics["inverse_normalized_success"]
            + 0.20 * metrics["model_adjusted_difficulty"]
        )
        task_rows[task] = {
            key: round(clamp01(value), 6) for key, value in metrics.items()
        } | {
            "consensus_difficulty": round(clamp01(consensus), 6),
            "model_count": row.get("model_count", 0),
            "runs": row.get("runs", 0),
        }
    return {
        "object": "agent_hub.research.candidate_difficulty_metrics",
        "definitions": {
            "mean_failure_rate": "Average observed failure probability across models.",
            "mean_validation_deficit": "Average 1 - validation score across models.",
            "inverse_normalized_success": "Average lack of binary success across models.",
            "model_adjusted_difficulty": "Difficulty after subtracting model-level strength.",
            "consensus_difficulty": "Weighted blend of failure, validation deficit, success deficit, and model-adjusted terms.",
        },
        "tasks": task_rows,
    }


def difficulty_values(metrics: dict[str, Any], *, key: str = "consensus_difficulty", multi_model_only: bool = False) -> dict[str, float]:
    rows = metrics.get("tasks", {})
    result = {}
    for task, row in rows.items():
        if multi_model_only and int(row.get("model_count") or 0) < 2:
            continue
        result[task] = float(row.get(key) or 0.0)
    return result


def explain_variance(matrix: dict[str, Any], difficulties: dict[str, float]) -> float:
    xs = []
    ys = []
    for task, row in matrix.get("tasks", {}).items():
        if task not in difficulties:
            continue
        for cell in (row.get("models") or {}).values():
            xs.append(difficulties[task])
            ys.append(1.0 - float(cell.get("effective_performance") or 0.0))
    corr = pearson(xs, ys)
    return round(corr * corr, 6)


__all__ = [
    "build_task_model_matrix",
    "compute_candidate_difficulty_metrics",
    "difficulty_values",
    "explain_variance",
    "load_difficulty_observations",
    "task_signature",
]
