from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .model_distance import load_model_observations, normalize_vectors
from .telemetry import research_dir


def load_task_matrix(state_dir: str | Path) -> dict[str, Any]:
    path = research_dir(state_dir) / "difficulty_task_matrix.json"
    if not path.exists():
        return {"tasks": {}, "models": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"tasks": {}, "models": {}}


def build_task_embeddings(state_dir: str | Path, observations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    observations = observations if observations is not None else load_model_observations(state_dir)
    matrix = load_task_matrix(state_dir)
    vectors = _task_vectors_from_matrix(matrix)
    vectors.update(_task_vectors_from_observations(observations, vectors))
    normalized = normalize_vectors(vectors)
    coords = _classical_mds(_distance_matrix(normalized), dimensions=3)
    tasks = sorted(vectors)
    clusters = _cluster_tasks(tasks, coords)
    return {
        "object": "agent_hub.research.task_embedding",
        "task_count": len(tasks),
        "feature_count": len({feature for vector in vectors.values() for feature in vector}),
        "tasks": {
            task: {
                "raw_vector": vectors[task],
                "normalized_vector": normalized[task],
                "embedding_2d": [round(value, 6) for value in coords[task][:2]],
                "embedding_3d": [round(value, 6) for value in coords[task][:3]],
                "cluster": clusters["assignments"].get(task, ""),
            }
            for task in tasks
        },
        "clusters": clusters,
        "notes": [
            "Task vectors include success, validation, failure, latency, and per-model interaction patterns.",
            "Clusters are tested with agglomerative clustering over task embeddings; labels are inferred after clustering.",
        ],
    }


def export_task_embeddings(state_dir: str | Path, observations: list[dict[str, Any]] | None = None) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = build_task_embeddings(state_dir, observations)
    json_path = directory / "task_embedding.json"
    md_path = directory / "task_embedding.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(task_embedding_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def task_embedding_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Task Embedding",
        "",
        f"- Tasks: {payload['task_count']}",
        f"- Features: {payload['feature_count']}",
        f"- Selected clusters: {payload['clusters']['selected_k']}",
        "",
        "## Clusters",
        "",
    ]
    for cluster_id, row in payload["clusters"]["clusters"].items():
        examples = ", ".join(row["examples"][:6])
        lines.append(f"- {cluster_id}: {row['label']} ({row['size']} tasks). Examples: {examples}")
    lines.extend(["", "## Task Coordinates", "", "| task | cluster | x | y | z |", "| --- | --- | --- | --- | --- |"])
    for task, row in list(payload["tasks"].items())[:100]:
        x, y, z = row["embedding_3d"]
        lines.append(f"| {task} | {row['cluster']} | {x} | {y} | {z} |")
    if len(payload["tasks"]) > 100:
        lines.append(f"| ... | ... | ... | ... | {len(payload['tasks']) - 100} more tasks omitted |")
    lines.append("")
    return "\n".join(lines)


def _task_vectors_from_matrix(matrix: dict[str, Any]) -> dict[str, dict[str, float]]:
    vectors: dict[str, dict[str, float]] = {}
    for task, payload in (matrix.get("tasks") or {}).items():
        models = payload.get("models") or {}
        vector: dict[str, float] = {
            "model_count": float(payload.get("model_count") or len(models)),
            "mean_success": _avg((row.get("success_rate") or 0.0) for row in models.values()),
            "mean_validation": _avg((row.get("validation_score") or 0.0) for row in models.values()),
            "mean_failure": _avg((row.get("failure_rate") or 0.0) for row in models.values()),
            "mean_effective": _avg((row.get("effective_performance") or 0.0) for row in models.values()),
            "performance_spread": _spread((row.get("effective_performance") or 0.0) for row in models.values()),
        }
        for model, row in models.items():
            vector[f"model_success.{model}"] = float(row.get("success_rate") or 0.0)
            vector[f"model_validation.{model}"] = float(row.get("validation_score") or 0.0)
            vector[f"model_failure.{model}"] = float(row.get("failure_rate") or 0.0)
        vectors[task] = vector
    return vectors


def _task_vectors_from_observations(observations: list[dict[str, Any]], existing: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        grouped[_task_key(row)].append(row)
    vectors = dict(existing)
    for task, rows in grouped.items():
        vector = dict(vectors.get(task, {}))
        vector.update(
            {
                "observed_runs": float(len(rows)),
                "observed_success": _avg(1.0 if row["success"] else 0.0 for row in rows),
                "observed_validation": _avg(row["validation_score"] for row in rows),
                "observed_failure": _avg(0.0 if row["success"] else 1.0 for row in rows),
                "latency_mean_ms": _avg(row["latency_ms"] for row in rows),
                "latency_spread_ms": _spread(row["latency_ms"] for row in rows),
                "response_tokens_mean": _avg(row.get("output_tokens", 0.0) for row in rows),
                "response_length_mean": _avg(row.get("response_length", 0.0) for row in rows),
                "retry_mean": _avg(row["retry_count"] for row in rows),
            }
        )
        for model, model_rows in _group_by(rows, "model").items():
            vector[f"observed_model_success.{model}"] = _avg(1.0 if row["success"] else 0.0 for row in model_rows)
            vector[f"observed_model_latency.{model}"] = _avg(row["latency_ms"] for row in model_rows)
            vector[f"observed_model_response_tokens.{model}"] = _avg(row.get("output_tokens", 0.0) for row in model_rows)
        vectors[task] = vector
    return vectors


def _distance_matrix(vectors: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    tasks = sorted(vectors)
    return {
        left: {
            right: math.sqrt(sum((vectors[left].get(key, 0.0) - vectors[right].get(key, 0.0)) ** 2 for key in set(vectors[left]) | set(vectors[right])))
            for right in tasks
        }
        for left in tasks
    }


def _classical_mds(distances: dict[str, dict[str, float]], dimensions: int) -> dict[str, list[float]]:
    tasks = sorted(distances)
    if not tasks:
        return {}
    # Landmark projection: stable, dependency-free approximation good enough for small research artifacts.
    landmarks = tasks[:dimensions]
    coords: dict[str, list[float]] = {}
    for task in tasks:
        raw = [distances[task][landmark] for landmark in landmarks]
        mean = sum(raw) / len(raw) if raw else 0.0
        coords[task] = [value - mean for value in raw]
    return coords


def _cluster_tasks(tasks: list[str], coords: dict[str, list[float]]) -> dict[str, Any]:
    if len(tasks) < 3:
        return {"selected_k": len(tasks), "assignments": {task: "cluster_1" for task in tasks}, "clusters": {}}
    candidates = []
    for k in range(2, min(7, len(tasks)) + 1):
        assignments = _kmeans(tasks, coords, k)
        candidates.append((k, assignments, _silhouette(tasks, assignments, coords)))
    k, assignments, score = max(candidates, key=lambda item: item[2])
    grouped: dict[str, list[str]] = defaultdict(list)
    for task, cluster_id in assignments.items():
        grouped[cluster_id].append(task)
    clusters = {
        cluster_id: {
            "size": len(rows),
            "label": _label_tasks(rows),
            "examples": sorted(rows)[:10],
        }
        for cluster_id, rows in sorted(grouped.items())
    }
    return {
        "selected_k": k,
        "silhouette": round(score, 6),
        "assignments": assignments,
        "clusters": clusters,
        "candidate_scores": [{"k": row[0], "silhouette": round(row[2], 6)} for row in candidates],
    }


def _kmeans(tasks: list[str], coords: dict[str, list[float]], k: int) -> dict[str, str]:
    centers = [coords[task][:] for task in _initial_centers(tasks, coords, k)]
    assignments = {task: 0 for task in tasks}
    for _ in range(20):
        changed = False
        for task in tasks:
            cluster = min(range(k), key=lambda index: _euclidean(coords[task], centers[index]))
            changed = changed or assignments[task] != cluster
            assignments[task] = cluster
        if not changed:
            break
        for cluster in range(k):
            members = [coords[task] for task in tasks if assignments[task] == cluster]
            if members:
                centers[cluster] = [sum(row[dim] for row in members) / len(members) for dim in range(len(members[0]))]
    return {task: f"cluster_{assignments[task] + 1}" for task in tasks}


def _initial_centers(tasks: list[str], coords: dict[str, list[float]], k: int) -> list[str]:
    centers = [tasks[0]]
    while len(centers) < k:
        centers.append(max(tasks, key=lambda task: min(_euclidean(coords[task], coords[center]) for center in centers)))
    return centers


def _silhouette(tasks: list[str], assignments: dict[str, str], coords: dict[str, list[float]]) -> float:
    values = []
    for task in tasks:
        same = [other for other in tasks if assignments[other] == assignments[task] and other != task]
        other_clusters = sorted({assignments[other] for other in tasks if assignments[other] != assignments[task]})
        a = _avg(_euclidean(coords[task], coords[other]) for other in same) if same else 0.0
        b = min((_avg(_euclidean(coords[task], coords[other]) for other in tasks if assignments[other] == cluster) for cluster in other_clusters), default=0.0)
        values.append((b - a) / max(a, b) if max(a, b) else 0.0)
    return _avg(values)


def _label_tasks(tasks: list[str]) -> str:
    text = " ".join(tasks).lower()
    for label in ("coding", "debugging", "reasoning", "planning", "retrieval", "summarization", "tool_calling", "long_context"):
        if label in text:
            return label
    return "mixed_or_latent"


def _task_key(row: dict[str, Any]) -> str:
    repo = row.get("repository") or "unknown"
    task_type = row.get("task_type") or "unknown"
    return f"{repo}::{task_type}::observed"


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "")].append(row)
    return grouped


def _euclidean(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def _spread(values: Any) -> float:
    rows = [float(value) for value in values]
    return max(rows) - min(rows) if rows else 0.0


def _avg(values: Any) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


__all__ = ["build_task_embeddings", "export_task_embeddings", "load_task_matrix", "task_embedding_markdown"]
