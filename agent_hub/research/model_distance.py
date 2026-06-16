from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from .telemetry import research_dir


CONTEXT_BUCKETS = (0, 25, 50, 75, 100)


def load_model_observations(state_dir: str | Path) -> list[dict[str, Any]]:
    directory = research_dir(state_dir)
    rows: list[dict[str, Any]] = []
    for name in ("runs.jsonl", "experiments.jsonl", "real_model_validation_results.jsonl"):
        rows.extend(_load_jsonl(directory / name, source=name))
    rows.extend(_load_dataset_csv(directory / "dataset.csv"))
    rows.extend(_load_multi_model_context_scaling(directory / "multi_model_context_scaling.json"))
    return [row for row in rows if row["model"]]


def build_behavior_vectors(observations: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    task_types = sorted({row["task_type"] for row in observations if row["task_type"]})
    for row in observations:
        by_model[row["model"]].append(row)

    models: dict[str, dict[str, Any]] = {}
    raw_vectors: dict[str, dict[str, float]] = {}
    success_patterns: dict[str, list[str]] = {}
    failure_patterns: dict[str, list[str]] = {}

    for model, rows in sorted(by_model.items()):
        vector = _base_features(rows)
        for task_type in task_types:
            task_rows = [row for row in rows if row["task_type"] == task_type]
            vector[f"success_rate.task.{task_type}"] = _rate(task_rows, "success")
            vector[f"validation_score.task.{task_type}"] = _mean(row["validation_score"] for row in task_rows)
        for bucket in CONTEXT_BUCKETS:
            bucket_rows = [row for row in rows if row["context_percent"] == bucket]
            vector[f"context.success.{bucket}"] = _rate(bucket_rows, "success")
            vector[f"context.validation.{bucket}"] = _mean(row["validation_score"] for row in bucket_rows)
        vector.update(_context_features(rows))
        raw_vectors[model] = {key: round(value, 8) for key, value in sorted(vector.items())}
        success_patterns[model] = sorted(_pattern_key(row) for row in rows if row["success"])
        failure_patterns[model] = sorted(_pattern_key(row) for row in rows if not row["success"])
        models[model] = {
            "runs": len(rows),
            "sources": _counts(row["source"] for row in rows),
            "repositories": sorted({row["repository"] for row in rows if row["repository"]}),
            "task_types": sorted({row["task_type"] for row in rows if row["task_type"]}),
            "raw_vector": raw_vectors[model],
            "success_pattern_size": len(success_patterns[model]),
            "failure_pattern_size": len(failure_patterns[model]),
        }

    normalized_vectors = normalize_vectors(raw_vectors)
    for model, vector in normalized_vectors.items():
        models[model]["normalized_vector"] = vector

    return {
        "object": "agent_hub.research.model_behavior_vectors",
        "total_observations": len(observations),
        "models": models,
        "feature_names": sorted({key for vector in raw_vectors.values() for key in vector}),
        "success_patterns": success_patterns,
        "failure_patterns": failure_patterns,
        "notes": [
            "Missing feature values are imputed with the cross-model feature mean before normalization.",
            "Rows from runs.jsonl, experiments.jsonl, dataset.csv, validation JSONL, and multi-model context scaling are all used; overlapping deterministic rows may be overrepresented.",
        ],
    }


def normalize_vectors(vectors: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    features = sorted({key for vector in vectors.values() for key in vector})
    means = {
        feature: _mean(vectors[model].get(feature, 0.0) for model in vectors if feature in vectors[model])
        for feature in features
    }
    stds: dict[str, float] = {}
    for feature in features:
        values = [vectors[model].get(feature, means[feature]) for model in vectors]
        mean = sum(values) / len(values) if values else 0.0
        variance = sum((value - mean) ** 2 for value in values) / len(values) if values else 0.0
        stds[feature] = math.sqrt(variance) or 1.0
    return {
        model: {
            feature: round((vectors[model].get(feature, means[feature]) - means[feature]) / stds[feature], 8)
            for feature in features
        }
        for model in sorted(vectors)
    }


def compute_distance_matrix(behavior_payload: dict[str, Any]) -> dict[str, Any]:
    models = sorted(behavior_payload["models"])
    vectors = {model: behavior_payload["models"][model]["normalized_vector"] for model in models}
    success_patterns = behavior_payload.get("success_patterns", {})
    pair_rows: list[dict[str, Any]] = []
    matrices = {name: {model: {} for model in models} for name in ("euclidean", "cosine", "correlation", "jaccard", "composite")}

    for left in models:
        for right in models:
            pair = _pair_distances(vectors[left], vectors[right], success_patterns.get(left, []), success_patterns.get(right, []))
            for key, value in pair.items():
                matrices[key][left][right] = value
            if left < right:
                pair_rows.append({"model_i": left, "model_j": right, **pair})

    nearest = {
        model: sorted(
            (
                {"model": other, "distance": matrices["composite"][model][other]}
                for other in models
                if other != model
            ),
            key=lambda row: row["distance"],
        )[:3]
        for model in models
    }
    return {
        "object": "agent_hub.research.model_distance_matrix",
        "models": models,
        "metrics": matrices,
        "pairs": sorted(pair_rows, key=lambda row: row["composite"]),
        "nearest_neighbors": nearest,
        "notes": [
            "Composite distance is the mean of Euclidean, cosine, correlation, and Jaccard distances over normalized behavioral vectors.",
            "Jaccard distance uses aligned success pattern keys; no shared task/context keys is treated as maximum distance.",
        ],
    }


def export_behavior_vectors(state_dir: str | Path) -> tuple[Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = build_behavior_vectors(load_model_observations(state_dir))
    path = directory / "model_behavior_vectors.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path, payload


def export_distance_matrix(state_dir: str | Path, behavior_payload: dict[str, Any] | None = None) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    behavior = behavior_payload or build_behavior_vectors(load_model_observations(state_dir))
    payload = compute_distance_matrix(behavior)
    json_path = directory / "model_distance_matrix.json"
    md_path = directory / "model_distance_matrix.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(distance_matrix_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def distance_matrix_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Model Distance Matrix",
        "",
        "Distances are behavioral, not architectural. Lower means more similar under the observed tasks.",
        "",
        "| model i | model j | euclidean | cosine | correlation | jaccard | composite |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["pairs"]:
        lines.append(
            f"| {row['model_i']} | {row['model_j']} | {row['euclidean']} | {row['cosine']} | {row['correlation']} | {row['jaccard']} | {row['composite']} |"
        )
    lines.extend(["", "## Nearest Neighbors"])
    for model, neighbors in payload["nearest_neighbors"].items():
        rendered = ", ".join(f"{row['model']} ({row['distance']})" for row in neighbors) or "none"
        lines.append(f"- {model}: {rendered}")
    lines.append("")
    return "\n".join(lines)


def _load_jsonl(path: Path, *, source: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(_normalize(json.loads(line), source))
        except json.JSONDecodeError:
            continue
    return rows


def _load_dataset_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [_normalize(row, "dataset.csv") for row in csv.DictReader(handle)]


def _load_multi_model_context_scaling(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    rows = [_normalize(row, "multi_model_context_scaling.json") for row in payload.get("runs", []) if isinstance(row, dict)]
    for model, summary in (payload.get("per_model") or {}).items():
        if not isinstance(summary, dict):
            continue
        synthetic = dict(summary)
        synthetic["model"] = model
        synthetic["task_id"] = f"{model}-multi-model-summary"
        synthetic["task_type"] = "context_scaling"
        synthetic["success"] = summary.get("success_rate", summary.get("average_success_rate", 0.0)) >= 0.5
        synthetic["validation_score"] = summary.get("average_validation_score", summary.get("validation_score", 0.0))
        synthetic["latency_ms"] = summary.get("average_latency_ms", summary.get("latency_ms", 0.0))
        rows.append(_normalize(synthetic, "multi_model_context_scaling.json:per_model"))
    return rows


def _normalize(raw: dict[str, Any], source: str) -> dict[str, Any]:
    error = str(raw.get("error") or "")
    timeout = bool(raw.get("timeout")) or "timeout" in error.lower()
    return {
        "source": source,
        "model": str(raw.get("model") or raw.get("selected_model") or raw.get("agent") or ""),
        "task_id": str(raw.get("task_id") or raw.get("experiment_id") or ""),
        "task_type": str(raw.get("task_type") or raw.get("route") or ""),
        "repository": str(raw.get("repository") or raw.get("repo_id") or raw.get("repo_source") or ""),
        "context_percent": _int(raw.get("context_percent"), default=-1),
        "context_tokens": _float(raw.get("context_token_count", raw.get("context_tokens", raw.get("context", 0.0)))),
        "file_count": len(raw.get("context_files") or raw.get("selected_files") or []) if isinstance(raw.get("context_files") or raw.get("selected_files"), list) else _int(raw.get("file_count")),
        "latency_ms": _float(raw.get("latency_ms", raw.get("latency", 0.0))),
        "output_tokens": _float(raw.get("output_tokens")),
        "response_length": float(len(str(raw.get("output_preview") or ""))),
        "cost_estimate": _float(raw.get("cost_estimate", raw.get("cost", 0.0))),
        "validation_score": _float(raw.get("validation_score")),
        "success": _bool(raw.get("success")),
        "retry_count": _float(raw.get("retry_count")),
        "error": error,
        "timeout": timeout,
    }


def _base_features(rows: list[dict[str, Any]]) -> dict[str, float]:
    latencies = sorted(row["latency_ms"] for row in rows if row["latency_ms"] > 0)
    return {
        "success_rate.overall": _rate(rows, "success"),
        "validation_score.overall": _mean(row["validation_score"] for row in rows),
        "error_rate.overall": sum(1 for row in rows if row["error"]) / len(rows) if rows else 0.0,
        "timeout_rate.overall": sum(1 for row in rows if row["timeout"]) / len(rows) if rows else 0.0,
        "latency.mean_ms": _mean(latencies),
        "latency.median_ms": float(median(latencies)) if latencies else 0.0,
        "latency.p90_ms": _percentile(latencies, 0.9),
        "retry.mean": _mean(row["retry_count"] for row in rows),
        "cost.mean": _mean(row["cost_estimate"] for row in rows),
    }


def _context_features(rows: list[dict[str, Any]]) -> dict[str, float]:
    measured = [row for row in rows if row["context_percent"] >= 0]
    low = [row for row in measured if row["context_percent"] in (0, 25)]
    high = [row for row in measured if row["context_percent"] in (75, 100)]
    slope = _slope([(row["context_tokens"], row["validation_score"]) for row in measured])
    success_slope = _slope([(row["context_tokens"], 1.0 if row["success"] else 0.0) for row in measured])
    high_context_success = _rate(high, "success")
    low_context_success = _rate(low, "success")
    return {
        "context_tolerance": high_context_success - low_context_success,
        "information_density_benefit": _mean(row["validation_score"] for row in high) - _mean(row["validation_score"] for row in low),
        "context_scaling.validation_slope_per_1k": slope * 1000.0,
        "context_scaling.success_slope_per_1k": success_slope * 1000.0,
        "context.mean_tokens": _mean(row["context_tokens"] for row in measured),
        "context.max_tokens": max((row["context_tokens"] for row in measured), default=0.0),
    }


def _pair_distances(left: dict[str, float], right: dict[str, float], left_success: list[str], right_success: list[str]) -> dict[str, float]:
    features = sorted(set(left) | set(right))
    a = [left.get(feature, 0.0) for feature in features]
    b = [right.get(feature, 0.0) for feature in features]
    raw = {
        "euclidean": _euclidean(a, b),
        "cosine": _cosine_distance(a, b),
        "correlation": _correlation_distance(a, b),
        "jaccard": _jaccard_distance(left_success, right_success),
    }
    raw["composite"] = sum(raw.values()) / len(raw)
    return {key: round(value, 6) for key, value in raw.items()}


def _pattern_key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            row["repository"],
            row["task_type"],
            row["task_id"].rsplit("-", 1)[0] if row["task_id"] else "",
            str(row["context_percent"]),
        ]
    )


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[str(value)] += 1
    return dict(sorted(counts.items()))


def _rate(rows: list[dict[str, Any]], field: str) -> float:
    return sum(1 for row in rows if row[field]) / len(rows) if rows else 0.0


def _mean(values: Any) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, int(math.ceil(len(values) * quantile) - 1)))
    return values[index]


def _slope(points: list[tuple[float, float]]) -> float:
    points = [(x, y) for x, y in points if x >= 0]
    if len(points) < 2:
        return 0.0
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in points) / denom if denom else 0.0


def _euclidean(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _cosine_distance(a: list[float], b: list[float]) -> float:
    denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if not denom:
        return 1.0
    return 1.0 - sum(x * y for x, y in zip(a, b)) / denom


def _correlation_distance(a: list[float], b: list[float]) -> float:
    ma = sum(a) / len(a) if a else 0.0
    mb = sum(b) / len(b) if b else 0.0
    centered_a = [x - ma for x in a]
    centered_b = [y - mb for y in b]
    return _cosine_distance(centered_a, centered_b)


def _jaccard_distance(left: list[str], right: list[str]) -> float:
    a = set(left)
    b = set(right)
    union = a | b
    if not union:
        return 1.0
    return 1.0 - (len(a & b) / len(union))


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in ("", None) else default)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value if value not in ("", None) else default))
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "y"}
    return bool(value)


__all__ = [
    "build_behavior_vectors",
    "compute_distance_matrix",
    "distance_matrix_markdown",
    "export_behavior_vectors",
    "export_distance_matrix",
    "load_model_observations",
    "normalize_vectors",
]
