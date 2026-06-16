from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .task_embedding import load_task_matrix
from .telemetry import research_dir


def build_shared_geometry(state_dir: str | Path, task_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    directory = research_dir(state_dir)
    model_embedding = _load_json(directory / "capability_embedding.json")
    task_payload = task_payload or _load_json(directory / "task_embedding.json")
    matrix = load_task_matrix(state_dir)
    model_positions = {model: coords[:3] for model, coords in (model_embedding.get("embedding_3d") or {}).items()}
    task_positions = _task_positions_in_model_space(matrix, model_positions, task_payload)
    interactions = _interactions(matrix, model_positions, task_positions)
    return {
        "object": "agent_hub.research.shared_geometry",
        "method": "task_barycenters_from_model_interaction_weights_in_capability_pca_space",
        "models": model_positions,
        "tasks": task_positions,
        "interaction_count": len(interactions),
        "interactions": interactions,
        "notes": [
            "Task coordinates are weighted barycenters of model coordinates using centered effective performance.",
            "This intentionally tests whether interaction geometry is useful; it is not proof that the latent axes are universal.",
        ],
    }


def compute_compatibility_metrics(shared_payload: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for row in shared_payload["interactions"]:
        model_pos = shared_payload["models"][row["model"]]
        task_pos = shared_payload["tasks"][row["task"]]
        distance = _euclidean(model_pos, task_pos)
        cosine = _cosine(model_pos, task_pos)
        projection = _projection(model_pos, task_pos)
        inverse_distance = 1.0 / (1.0 + distance)
        radial_gap = abs(_norm(model_pos) - _norm(task_pos))
        rows.append(
            {
                **row,
                "distance": round(distance, 8),
                "inverse_distance": round(inverse_distance, 8),
                "cosine_similarity": round(cosine, 8),
                "projection": round(projection, 8),
                "radial_gap": round(radial_gap, 8),
                "combined_compatibility": round((inverse_distance + ((cosine + 1.0) / 2.0) + (1.0 / (1.0 + radial_gap))) / 3.0, 8),
            }
        )
    evaluations = {
        metric: _metric_relationship(rows, metric)
        for metric in ("inverse_distance", "cosine_similarity", "projection", "radial_gap", "combined_compatibility")
    }
    return {
        "object": "agent_hub.research.compatibility_metrics",
        "metrics": evaluations,
        "best_metric": max(evaluations, key=lambda key: abs(evaluations[key]["success_correlation"])) if evaluations else "",
        "interactions": rows,
        "notes": [
            "Metrics are functions only of model position and task position.",
            "Prediction tests use these scalar compatibility metrics and do not add context, routing, or raw validation predictors.",
        ],
    }


def export_shared_geometry(state_dir: str | Path, task_payload: dict[str, Any] | None = None) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = build_shared_geometry(state_dir, task_payload)
    json_path = directory / "shared_geometry.json"
    md_path = directory / "shared_geometry.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(shared_geometry_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def export_compatibility_metrics(state_dir: str | Path, shared_payload: dict[str, Any] | None = None) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = compute_compatibility_metrics(shared_payload or build_shared_geometry(state_dir))
    json_path = directory / "compatibility_metrics.json"
    md_path = directory / "compatibility_metrics.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(compatibility_metrics_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def shared_geometry_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Shared Model-Task Geometry",
        "",
        f"- Method: `{payload['method']}`",
        f"- Models: {len(payload['models'])}",
        f"- Tasks: {len(payload['tasks'])}",
        f"- Interactions: {payload['interaction_count']}",
        "",
        "## Model Coordinates",
        "",
        "| model | x | y | z |",
        "| --- | --- | --- | --- |",
    ]
    for model, coords in payload["models"].items():
        lines.append(f"| {model} | {coords[0]} | {coords[1]} | {coords[2]} |")
    lines.extend(["", "## Task Coordinates", "", "| task | x | y | z |", "| --- | --- | --- | --- |"])
    for task, coords in list(payload["tasks"].items())[:80]:
        lines.append(f"| {task} | {coords[0]} | {coords[1]} | {coords[2]} |")
    if len(payload["tasks"]) > 80:
        lines.append(f"| ... | ... | ... | {len(payload['tasks']) - 80} more tasks omitted |")
    lines.append("")
    return "\n".join(lines)


def compatibility_metrics_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Compatibility Metrics",
        "",
        f"- Best metric by absolute success correlation: `{payload['best_metric']}`",
        "",
        "| metric | success correlation | validation correlation | MAE if thresholded |",
        "| --- | --- | --- | --- |",
    ]
    for metric, row in payload["metrics"].items():
        lines.append(f"| {metric} | {row['success_correlation']} | {row['validation_correlation']} | {row['threshold_mae']} |")
    lines.append("")
    return "\n".join(lines)


def _task_positions_in_model_space(
    matrix: dict[str, Any],
    model_positions: dict[str, list[float]],
    task_payload: dict[str, Any],
) -> dict[str, list[float]]:
    positions: dict[str, list[float]] = {}
    for task, payload in (matrix.get("tasks") or {}).items():
        rows = payload.get("models") or {}
        performances = [float(row.get("effective_performance") or row.get("validation_score") or 0.0) for row in rows.values()]
        mean_perf = sum(performances) / len(performances) if performances else 0.0
        weighted = [0.0, 0.0, 0.0]
        total = 0.0
        for model, row in rows.items():
            if model not in model_positions:
                continue
            weight = float(row.get("effective_performance") or row.get("validation_score") or 0.0) - mean_perf
            if weight <= 0:
                continue
            total += weight
            for dim in range(3):
                weighted[dim] += model_positions[model][dim] * weight
        if total:
            positions[task] = [round(value / total, 6) for value in weighted]
        else:
            fallback = (task_payload.get("tasks") or {}).get(task, {}).get("embedding_3d") or [0.0, 0.0, 0.0]
            positions[task] = [round(float(value), 6) for value in fallback[:3]]
    return positions


def _interactions(
    matrix: dict[str, Any],
    model_positions: dict[str, list[float]],
    task_positions: dict[str, list[float]],
) -> list[dict[str, Any]]:
    rows = []
    for task, payload in (matrix.get("tasks") or {}).items():
        for model, result in (payload.get("models") or {}).items():
            if model in model_positions and task in task_positions:
                rows.append(
                    {
                        "task": task,
                        "model": model,
                        "success": float(result.get("success_rate") or 0.0),
                        "validation_score": float(result.get("validation_score") or 0.0),
                        "effective_performance": float(result.get("effective_performance") or 0.0),
                        "runs": int(result.get("runs") or 0),
                    }
                )
    return rows


def _metric_relationship(rows: list[dict[str, Any]], metric: str) -> dict[str, float]:
    xs = [float(row[metric]) for row in rows]
    ys = [float(row["success"]) for row in rows]
    validation = [float(row["validation_score"]) for row in rows]
    threshold = sorted(xs)[len(xs) // 2] if xs else 0.0
    if metric == "radial_gap":
        preds = [1.0 if x <= threshold else 0.0 for x in xs]
    else:
        preds = [1.0 if x >= threshold else 0.0 for x in xs]
    return {
        "success_correlation": round(_pearson(xs, ys), 6),
        "validation_correlation": round(_pearson(xs, validation), 6),
        "threshold_mae": round(_mae(ys, preds), 6),
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _euclidean(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def _norm(value: list[float]) -> float:
    return math.sqrt(sum(item * item for item in value))


def _cosine(left: list[float], right: list[float]) -> float:
    denom = _norm(left) * _norm(right)
    return sum(a * b for a, b in zip(left, right)) / denom if denom else 0.0


def _projection(left: list[float], right: list[float]) -> float:
    denom = _norm(right)
    return sum(a * b for a, b in zip(left, right)) / denom if denom else 0.0


def _mae(actual: list[float], predicted: list[float]) -> float:
    return sum(abs(a - b) for a, b in zip(actual, predicted)) / len(actual) if actual else 0.0


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    ml = sum(left) / len(left)
    mr = sum(right) / len(right)
    numerator = sum((a - ml) * (b - mr) for a, b in zip(left, right))
    denom_l = math.sqrt(sum((a - ml) ** 2 for a in left))
    denom_r = math.sqrt(sum((b - mr) ** 2 for b in right))
    return numerator / (denom_l * denom_r) if denom_l and denom_r else 0.0


__all__ = [
    "build_shared_geometry",
    "compute_compatibility_metrics",
    "export_compatibility_metrics",
    "export_shared_geometry",
]
