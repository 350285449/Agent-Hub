from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .model_distance import build_behavior_vectors, compute_distance_matrix, load_model_observations
from .telemetry import research_dir


def compute_model_clusters(behavior_payload: dict[str, Any], distance_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    distance = distance_payload or compute_distance_matrix(behavior_payload)
    models = sorted(behavior_payload["models"])
    if len(models) <= 2:
        clusters = {f"cluster_{index + 1}": [model] for index, model in enumerate(models)}
        k = len(models)
    else:
        candidates = []
        for k_value in range(2, min(5, len(models)) + 1):
            candidate = _agglomerative(models, distance["metrics"]["composite"], k_value)
            candidates.append((k_value, candidate, _silhouette(candidate, distance["metrics"]["composite"])))
        k, clusters, _score = max(candidates, key=lambda item: item[2])
    summaries = _summarize_clusters(clusters, behavior_payload, distance)
    return {
        "object": "agent_hub.research.model_clusters",
        "method": "average_linkage_agglomerative_on_composite_behavior_distance",
        "selected_k": k,
        "clusters": summaries,
        "model_assignments": {model: cluster_id for cluster_id, summary in summaries.items() for model in summary["models"]},
        "candidate_cluster_counts": _candidate_scores(models, distance["metrics"]["composite"]),
        "notes": [
            "Cluster names are descriptive labels inferred from observed behavior, not a ground truth taxonomy.",
            "Small sample sizes can make singleton clusters look more meaningful than they are.",
        ],
    }


def export_model_clusters(
    state_dir: str | Path,
    behavior_payload: dict[str, Any] | None = None,
    distance_payload: dict[str, Any] | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    behavior = behavior_payload or build_behavior_vectors(load_model_observations(state_dir))
    distance = distance_payload or compute_distance_matrix(behavior)
    payload = compute_model_clusters(behavior, distance)
    json_path = directory / "model_clusters.json"
    md_path = directory / "model_clusters.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(model_clusters_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def model_clusters_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Model Clusters",
        "",
        f"- Method: `{payload['method']}`",
        f"- Selected cluster count: {payload['selected_k']}",
        "",
    ]
    for cluster_id, summary in payload["clusters"].items():
        lines.extend(
            [
                f"## {cluster_id}: {summary['label']}",
                "",
                f"- Models: {', '.join(summary['models'])}",
                f"- Average success: {summary['average_success_rate']}",
                f"- Average validation: {summary['average_validation_score']}",
                f"- Average latency ms: {summary['average_latency_ms']}",
                f"- Context tolerance: {summary['average_context_tolerance']}",
                f"- Evidence: {summary['evidence']}",
                "",
            ]
        )
    lines.extend(["## Candidate Cluster Counts", "", "| k | silhouette |", "| --- | --- |"])
    for row in payload["candidate_cluster_counts"]:
        lines.append(f"| {row['k']} | {row['silhouette']} |")
    lines.append("")
    return "\n".join(lines)


def _agglomerative(models: list[str], matrix: dict[str, dict[str, float]], k: int) -> dict[str, list[str]]:
    clusters = [[model] for model in models]
    while len(clusters) > k:
        best_pair = (0, 1, float("inf"))
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                distance = _cluster_distance(clusters[i], clusters[j], matrix)
                if distance < best_pair[2]:
                    best_pair = (i, j, distance)
        i, j, _distance = best_pair
        clusters[i] = sorted(clusters[i] + clusters[j])
        del clusters[j]
    return {f"cluster_{index + 1}": sorted(cluster) for index, cluster in enumerate(sorted(clusters, key=lambda row: row[0]))}


def _cluster_distance(left: list[str], right: list[str], matrix: dict[str, dict[str, float]]) -> float:
    values = [matrix[a][b] for a in left for b in right if a != b]
    return sum(values) / len(values) if values else 0.0


def _silhouette(clusters: dict[str, list[str]], matrix: dict[str, dict[str, float]]) -> float:
    assignments = {model: cluster_id for cluster_id, models in clusters.items() for model in models}
    scores = []
    for model, cluster_id in assignments.items():
        same = [other for other in clusters[cluster_id] if other != model]
        a = sum(matrix[model][other] for other in same) / len(same) if same else 0.0
        other_distances = []
        for other_cluster, members in clusters.items():
            if other_cluster == cluster_id:
                continue
            other_distances.append(sum(matrix[model][member] for member in members) / len(members))
        b = min(other_distances) if other_distances else 0.0
        denom = max(a, b)
        scores.append((b - a) / denom if denom else 0.0)
    return round(sum(scores) / len(scores), 6) if scores else 0.0


def _summarize_clusters(
    clusters: dict[str, list[str]],
    behavior_payload: dict[str, Any],
    distance_payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result = {}
    for cluster_id, models in clusters.items():
        raw_vectors = [behavior_payload["models"][model]["raw_vector"] for model in models]
        task_types = sorted({task for model in models for task in behavior_payload["models"][model]["task_types"]})
        success = _avg(vector.get("success_rate.overall", 0.0) for vector in raw_vectors)
        validation = _avg(vector.get("validation_score.overall", 0.0) for vector in raw_vectors)
        latency = _avg(vector.get("latency.mean_ms", 0.0) for vector in raw_vectors)
        context = _avg(vector.get("context_tolerance", 0.0) for vector in raw_vectors)
        label, evidence = _label_cluster(models, raw_vectors, task_types)
        result[cluster_id] = {
            "models": models,
            "label": label,
            "evidence": evidence,
            "task_types": task_types,
            "average_success_rate": round(success, 6),
            "average_validation_score": round(validation, 6),
            "average_latency_ms": round(latency, 3),
            "average_context_tolerance": round(context, 6),
            "internal_distance": round(_internal_distance(models, distance_payload["metrics"]["composite"]), 6),
        }
    return result


def _label_cluster(models: list[str], vectors: list[dict[str, float]], task_types: list[str]) -> tuple[str, str]:
    validation = _avg(vector.get("validation_score.overall", 0.0) for vector in vectors)
    success = _avg(vector.get("success_rate.overall", 0.0) for vector in vectors)
    latency = _avg(vector.get("latency.mean_ms", 0.0) for vector in vectors)
    context = _avg(vector.get("context_tolerance", 0.0) for vector in vectors)
    coding = _avg(vector.get("success_rate.task.coding", 0.0) for vector in vectors)
    reasoning = _avg(vector.get("success_rate.task.reasoning", 0.0) for vector in vectors)
    if context > 0.08:
        return "context specialists", f"context tolerance is positive ({round(context, 4)})"
    if coding >= max(reasoning, success) and "coding" in task_types:
        return "coding specialists", f"coding success is the strongest task signal ({round(coding, 4)})"
    if reasoning >= max(coding, success) and "reasoning" in task_types:
        return "reasoning specialists", f"reasoning success is the strongest task signal ({round(reasoning, 4)})"
    if latency and latency < 1000 and validation >= 0.5:
        return "fast/cheap specialists", f"mean latency is low ({round(latency, 3)} ms)"
    if success >= 0.5 and validation >= 0.5:
        return "generalists", f"success ({round(success, 4)}) and validation ({round(validation, 4)}) are both broad"
    return "weak or unstable specialists", "observed success/validation is low or incomplete"


def _candidate_scores(models: list[str], matrix: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    if len(models) <= 2:
        return [{"k": len(models), "silhouette": 0.0}]
    return [
        {"k": k, "silhouette": _silhouette(_agglomerative(models, matrix, k), matrix)}
        for k in range(2, min(5, len(models)) + 1)
    ]


def _internal_distance(models: list[str], matrix: dict[str, dict[str, float]]) -> float:
    pairs = [matrix[left][right] for index, left in enumerate(models) for right in models[index + 1 :]]
    return sum(pairs) / len(pairs) if pairs else 0.0


def _avg(values: Any) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


__all__ = [
    "compute_model_clusters",
    "export_model_clusters",
    "model_clusters_markdown",
]
