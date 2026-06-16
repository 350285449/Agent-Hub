from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .model_distance import build_behavior_vectors, load_model_observations
from .telemetry import research_dir


def compute_capability_embedding(behavior_payload: dict[str, Any]) -> dict[str, Any]:
    models = sorted(behavior_payload["models"])
    features = sorted(behavior_payload["feature_names"])
    matrix = [
        [float(behavior_payload["models"][model]["normalized_vector"].get(feature, 0.0)) for feature in features]
        for model in models
    ]
    centered = _center_columns(matrix)
    covariance = _covariance(centered)
    eigenvalues, eigenvectors = _jacobi_eigen(covariance)
    order = sorted(range(len(eigenvalues)), key=lambda index: eigenvalues[index], reverse=True)
    eigenvalues = [max(0.0, eigenvalues[index]) for index in order]
    eigenvectors = [[eigenvectors[row][index] for index in order] for row in range(len(eigenvectors))]
    total_variance = sum(eigenvalues) or 1.0
    max_components = min(len(models), len(features), len(eigenvalues))
    coordinates = _project(centered, eigenvectors, max_components)

    payload = {
        "object": "agent_hub.research.capability_embedding",
        "method": "pure_python_pca_jacobi_eigendecomposition",
        "models": models,
        "feature_count": len(features),
        "explained_variance": [round(value, 8) for value in eigenvalues[:max_components]],
        "explained_variance_ratio": [round(value / total_variance, 8) for value in eigenvalues[:max_components]],
        "embedding_2d": _dimension_payload(models, coordinates, 2),
        "embedding_3d": _dimension_payload(models, coordinates, 3),
        "embedding_nd": _dimension_payload(models, coordinates, max_components),
        "principal_feature_loadings": _top_loadings(features, eigenvectors, max_components),
        "notes": [
            "Coordinates are PCA scores over normalized behavioral vectors.",
            "Signs of PCA axes are arbitrary; relative distance and neighborhood structure are the interpretable parts.",
        ],
    }
    return payload


def export_capability_embedding(state_dir: str | Path, behavior_payload: dict[str, Any] | None = None) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    behavior = behavior_payload or build_behavior_vectors(load_model_observations(state_dir))
    payload = compute_capability_embedding(behavior)
    json_path = directory / "capability_embedding.json"
    md_path = directory / "capability_embedding.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(capability_embedding_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def capability_embedding_markdown(payload: dict[str, Any]) -> str:
    ratios = payload["explained_variance_ratio"]
    lines = [
        "# Capability Embedding",
        "",
        f"- Method: `{payload['method']}`",
        f"- Models: {len(payload['models'])}",
        f"- Features: {payload['feature_count']}",
        f"- Variance explained by PC1/PC2/PC3: {', '.join(str(value) for value in ratios[:3])}",
        "",
        "## 2D Coordinates",
        "",
        "| model | x | y |",
        "| --- | --- | --- |",
    ]
    for model, coords in payload["embedding_2d"].items():
        lines.append(f"| {model} | {coords[0]} | {coords[1]} |")
    lines.extend(["", "## 3D Coordinates", "", "| model | x | y | z |", "| --- | --- | --- | --- |"])
    for model, coords in payload["embedding_3d"].items():
        lines.append(f"| {model} | {coords[0]} | {coords[1]} | {coords[2]} |")
    lines.extend(["", "## Principal Feature Loadings"])
    for component, loadings in payload["principal_feature_loadings"].items():
        rendered = ", ".join(f"{item['feature']}={item['loading']}" for item in loadings[:6])
        lines.append(f"- {component}: {rendered}")
    lines.append("")
    return "\n".join(lines)


def _center_columns(matrix: list[list[float]]) -> list[list[float]]:
    if not matrix:
        return []
    means = [sum(row[column] for row in matrix) / len(matrix) for column in range(len(matrix[0]))]
    return [[value - means[column] for column, value in enumerate(row)] for row in matrix]


def _covariance(matrix: list[list[float]]) -> list[list[float]]:
    if not matrix:
        return []
    rows = len(matrix)
    cols = len(matrix[0])
    denom = max(1, rows - 1)
    return [
        [sum(matrix[row][i] * matrix[row][j] for row in range(rows)) / denom for j in range(cols)]
        for i in range(cols)
    ]


def _jacobi_eigen(matrix: list[list[float]], max_iterations: int = 200) -> tuple[list[float], list[list[float]]]:
    n = len(matrix)
    a = [row[:] for row in matrix]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    if n == 0:
        return [], []
    for _ in range(max_iterations):
        p, q, off = _largest_off_diagonal(a)
        if off < 1e-10:
            break
        if a[p][p] == a[q][q]:
            angle = math.pi / 4.0
        else:
            angle = 0.5 * math.atan2(2.0 * a[p][q], a[q][q] - a[p][p])
        c = math.cos(angle)
        s = math.sin(angle)
        for i in range(n):
            aip = a[i][p]
            aiq = a[i][q]
            a[i][p] = c * aip - s * aiq
            a[i][q] = s * aip + c * aiq
        for j in range(n):
            apj = a[p][j]
            aqj = a[q][j]
            a[p][j] = c * apj - s * aqj
            a[q][j] = s * apj + c * aqj
        for i in range(n):
            vip = v[i][p]
            viq = v[i][q]
            v[i][p] = c * vip - s * viq
            v[i][q] = s * vip + c * viq
    return [a[i][i] for i in range(n)], v


def _largest_off_diagonal(matrix: list[list[float]]) -> tuple[int, int, float]:
    best = (0, 0, 0.0)
    for i in range(len(matrix)):
        for j in range(i + 1, len(matrix)):
            value = abs(matrix[i][j])
            if value > best[2]:
                best = (i, j, value)
    return best


def _project(matrix: list[list[float]], eigenvectors: list[list[float]], components: int) -> list[list[float]]:
    if not matrix:
        return []
    return [
        [sum(row[feature] * eigenvectors[feature][component] for feature in range(len(row))) for component in range(components)]
        for row in matrix
    ]


def _dimension_payload(models: list[str], coordinates: list[list[float]], dimensions: int) -> dict[str, list[float]]:
    return {
        model: [round(coordinates[index][dimension], 6) if dimension < len(coordinates[index]) else 0.0 for dimension in range(dimensions)]
        for index, model in enumerate(models)
    }


def _top_loadings(features: list[str], eigenvectors: list[list[float]], components: int) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for component in range(min(components, 6)):
        rows = [
            {"feature": feature, "loading": round(eigenvectors[index][component], 6)}
            for index, feature in enumerate(features)
        ]
        result[f"PC{component + 1}"] = sorted(rows, key=lambda row: abs(row["loading"]), reverse=True)[:10]
    return result


__all__ = [
    "capability_embedding_markdown",
    "compute_capability_embedding",
    "export_capability_embedding",
]
