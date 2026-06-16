from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .quantity_tests import mean, pearson, stdev
from .task_difficulty import build_task_model_matrix, compute_candidate_difficulty_metrics, difficulty_values, explain_variance


def rank_stability(base: dict[str, float], variant: dict[str, float]) -> dict[str, float]:
    shared = sorted(set(base) & set(variant))
    if len(shared) < 2:
        return {"task_count": len(shared), "correlation": 0.0, "rank_stability": 0.0, "variance": 0.0}
    base_ranks = _ranks([base[key] for key in shared])
    variant_ranks = _ranks([variant[key] for key in shared])
    corr = pearson(base_ranks, variant_ranks)
    deltas = [abs(a - b) / max(1, len(shared) - 1) for a, b in zip(base_ranks, variant_ranks)]
    return {
        "task_count": len(shared),
        "correlation": round(corr, 6),
        "rank_stability": round(1.0 - mean(deltas), 6),
        "variance": round(stdev([base[key] - variant[key] for key in shared]) ** 2, 6),
    }


def independence_test(matrix: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    base_metrics = compute_candidate_difficulty_metrics(matrix)
    base = difficulty_values(base_metrics, multi_model_only=True)
    results = {}
    for model in sorted(matrix.get("models", {})):
        filtered = [row for row in rows if str(row.get("model") or "unknown") != model]
        variant_matrix = build_task_model_matrix(filtered)
        variant_metrics = compute_candidate_difficulty_metrics(variant_matrix)
        variant = difficulty_values(variant_metrics, multi_model_only=True)
        results[model] = rank_stability(base, variant)
    correlations = [row["correlation"] for row in results.values() if row["task_count"] >= 2]
    return {
        "object": "agent_hub.research.difficulty_independence",
        "leave_one_model_out": results,
        "mean_rank_correlation": round(mean(correlations), 6),
        "mean_rank_stability": round(mean(row["rank_stability"] for row in results.values() if row["task_count"] >= 2), 6),
        "mean_variance": round(mean(row["variance"] for row in results.values() if row["task_count"] >= 2), 6),
        "stable_under_model_removal": mean(correlations) >= 0.7 if correlations else False,
    }


def prediction_test(matrix: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = {}
    all_errors = []
    all_squared = []
    all_pred = []
    all_actual = []
    for model in sorted(matrix.get("models", {})):
        train_rows = [row for row in rows if str(row.get("model") or "unknown") != model]
        train_matrix = build_task_model_matrix(train_rows)
        metrics = compute_candidate_difficulty_metrics(train_matrix)
        difficulty = difficulty_values(metrics)
        model_cells = []
        for task, task_row in matrix.get("tasks", {}).items():
            cell = (task_row.get("models") or {}).get(model)
            if not cell or task not in difficulty:
                continue
            predicted = 1.0 - difficulty[task]
            actual = float(cell.get("effective_performance") or 0.0)
            model_cells.append((predicted, actual))
        errors = [abs(pred - actual) for pred, actual in model_cells]
        squared = [(pred - actual) ** 2 for pred, actual in model_cells]
        all_errors.extend(errors)
        all_squared.extend(squared)
        all_pred.extend(pred for pred, _ in model_cells)
        all_actual.extend(actual for _, actual in model_cells)
        results[model] = {
            "tasks": len(model_cells),
            "mae": round(mean(errors), 6),
            "rmse": round(math.sqrt(mean(squared)), 6) if squared else 0.0,
            "correlation": round(pearson([pred for pred, _ in model_cells], [actual for _, actual in model_cells]), 6),
        }
    return {
        "object": "agent_hub.research.difficulty_prediction",
        "held_out_models": results,
        "overall": {
            "mae": round(mean(all_errors), 6),
            "rmse": round(math.sqrt(mean(all_squared)), 6) if all_squared else 0.0,
            "correlation": round(pearson(all_pred, all_actual), 6),
            "predictions": len(all_errors),
        },
    }


def difficulty_hierarchy(metrics: dict[str, Any]) -> dict[str, Any]:
    values = difficulty_values(metrics)
    ordered = sorted(values.items(), key=lambda item: item[1])
    buckets = {"easy": [], "moderate": [], "hard": [], "extreme": []}
    for task, value in ordered:
        if value < 0.25:
            buckets["easy"].append(task)
        elif value < 0.50:
            buckets["moderate"].append(task)
        elif value < 0.75:
            buckets["hard"].append(task)
        else:
            buckets["extreme"].append(task)
    return {
        "object": "agent_hub.research.difficulty_hierarchy",
        "thresholds": {"easy": "<0.25", "moderate": "0.25-0.50", "hard": "0.50-0.75", "extreme": ">=0.75"},
        "counts": {key: len(value) for key, value in buckets.items()},
        "tasks": buckets,
    }


def falsification_report(matrix: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    model_strength = {
        model: float(row.get("mean_effective_performance") or 0.0)
        for model, row in matrix.get("models", {}).items()
    }
    flips = []
    weak_beats_strong = []
    dramatic_changes = []
    for task, task_row in matrix.get("tasks", {}).items():
        cells = task_row.get("models") or {}
        if len(cells) < 2:
            continue
        performances = {model: float(cell.get("effective_performance") or 0.0) for model, cell in cells.items()}
        spread = max(performances.values()) - min(performances.values())
        if spread >= 0.35:
            dramatic_changes.append({"task": task, "performance_spread": round(spread, 6), "models": performances})
        sorted_by_strength = sorted(performances, key=lambda model: model_strength.get(model, 0.0))
        for weak in sorted_by_strength:
            for strong in sorted_by_strength:
                if model_strength.get(weak, 0.0) + 0.05 < model_strength.get(strong, 0.0) and performances[weak] > performances[strong] + 0.05:
                    weak_beats_strong.append(
                        {
                            "task": task,
                            "weak_model": weak,
                            "strong_model": strong,
                            "weak_performance": round(performances[weak], 6),
                            "strong_performance": round(performances[strong], 6),
                        }
                    )
        task_difficulty = metrics.get("tasks", {}).get(task, {})
        variance = float(task_difficulty.get("performance_variance") or 0.0)
        if variance >= 0.05:
            flips.append({"task": task, "variance": round(variance, 6), "models": performances})
    return {
        "task_ranking_flips": flips,
        "weak_models_outperform_strong_models": weak_beats_strong,
        "dramatic_difficulty_changes": dramatic_changes,
    }


def evaluation_score(
    *,
    matrix: dict[str, Any],
    metrics: dict[str, Any],
    independence: dict[str, Any],
    prediction: dict[str, Any],
    falsification: dict[str, Any],
) -> dict[str, Any]:
    explained = explain_variance(matrix, difficulty_values(metrics))
    stability = max(0.0, float(independence.get("mean_rank_correlation") or 0.0))
    predictive = max(0.0, float(prediction.get("overall", {}).get("correlation") or 0.0))
    mae = float(prediction.get("overall", {}).get("mae") or 1.0)
    multi_model_tasks = max(1, int(matrix.get("multi_model_task_count") or 0))
    dramatic_ratio = len(falsification["dramatic_difficulty_changes"]) / multi_model_tasks
    flip_ratio = len(falsification["task_ranking_flips"]) / multi_model_tasks
    weak_beats_ratio = len(falsification["weak_models_outperform_strong_models"]) / multi_model_tasks
    falsification_penalty = min(
        0.60,
        0.30 * dramatic_ratio + 0.20 * flip_ratio + 0.10 * weak_beats_ratio,
    )
    score = 100.0 * (
        0.30 * stability
        + 0.25 * predictive
        + 0.20 * max(0.0, 1.0 - mae)
        + 0.15 * explained
        + 0.10 * max(0.0, 1.0 - falsification_penalty)
    )
    return {
        "score": round(max(0.0, min(100.0, score)), 3),
        "stable": stability >= 0.7,
        "predictive": predictive >= 0.4 and mae <= 0.25,
        "generalizes_across_models": bool(independence.get("stable_under_model_removal")),
        "survives_falsification": falsification_penalty < 0.2,
        "explained_variance": explained,
        "falsification_penalty": round(falsification_penalty, 6),
    }


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def independence_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Difficulty Independence Test",
        "",
        "| removed model | shared tasks | rank correlation | rank stability | variance |",
        "| --- | --- | --- | --- | --- |",
    ]
    for model, row in payload["leave_one_model_out"].items():
        lines.append(f"| {model} | {row['task_count']} | {row['correlation']} | {row['rank_stability']} | {row['variance']} |")
    lines.extend(
        [
            "",
            f"Mean rank correlation: {payload['mean_rank_correlation']}.",
            f"Stable under model removal: {payload['stable_under_model_removal']}.",
            "",
        ]
    )
    return "\n".join(lines)


def prediction_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Difficulty Prediction Test",
        "",
        "| held-out model | tasks | MAE | RMSE | correlation |",
        "| --- | --- | --- | --- | --- |",
    ]
    for model, row in payload["held_out_models"].items():
        lines.append(f"| {model} | {row['tasks']} | {row['mae']} | {row['rmse']} | {row['correlation']} |")
    overall = payload["overall"]
    lines.extend(
        [
            "",
            f"Overall MAE: {overall['mae']}.",
            f"Overall RMSE: {overall['rmse']}.",
            f"Overall correlation: {overall['correlation']}.",
            "",
        ]
    )
    return "\n".join(lines)


def hierarchy_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Difficulty Hierarchy",
        "",
        "| level | threshold | task count |",
        "| --- | --- | --- |",
    ]
    for level in ("easy", "moderate", "hard", "extreme"):
        lines.append(f"| {level} | {payload['thresholds'][level]} | {payload['counts'][level]} |")
    lines.append("")
    return "\n".join(lines)


def falsification_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Agent Difficulty Falsification",
        "",
        f"- Tasks that flip or show high model variance: {len(payload['task_ranking_flips'])}",
        f"- Cases where weak models outperform strong models: {len(payload['weak_models_outperform_strong_models'])}",
        f"- Tasks whose difficulty changes dramatically across models: {len(payload['dramatic_difficulty_changes'])}",
        "",
        "## Examples",
    ]
    for title, key in [
        ("Ranking flips / high variance", "task_ranking_flips"),
        ("Weak beats strong", "weak_models_outperform_strong_models"),
        ("Dramatic changes", "dramatic_difficulty_changes"),
    ]:
        lines.extend(["", f"### {title}"])
        rows = payload[key][:10]
        if not rows:
            lines.append("No examples found.")
        for row in rows:
            lines.append(f"- `{row['task']}`: {json.dumps(row, sort_keys=True)}")
    lines.append("")
    return "\n".join(lines)


def evaluation_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Agent Difficulty Fundamental Quantity Evaluation",
        "",
        f"Score: {payload['score']} / 100",
        "",
        "| criterion | result |",
        "| --- | --- |",
        f"| Remains stable? | {payload['stable']} |",
        f"| Predicts performance? | {payload['predictive']} |",
        f"| Generalizes across models? | {payload['generalizes_across_models']} |",
        f"| Survives falsification? | {payload['survives_falsification']} |",
        f"| Explains variance? | {payload['explained_variance']} |",
        "",
    ]
    return "\n".join(lines)


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        rank = (index + end - 1) / 2.0
        for _, original in ordered[index:end]:
            ranks[original] = rank
        index = end
    return ranks


__all__ = [
    "difficulty_hierarchy",
    "evaluation_markdown",
    "evaluation_score",
    "falsification_markdown",
    "falsification_report",
    "hierarchy_markdown",
    "independence_markdown",
    "independence_test",
    "prediction_markdown",
    "prediction_test",
    "rank_stability",
    "write_json",
]
