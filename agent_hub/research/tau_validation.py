from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .analysis import context_bucket
from .cross_repo_experiment import cross_repo_experiment_path
from .telemetry import research_dir


def compute_cross_repo_tau(state_dir: str | Path) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(state_dir):
        grouped[str(row.get("repo_id") or "unknown")].append(row)
    repositories = []
    for repo_id, rows in sorted(grouped.items()):
        points = _points(rows)
        fit = _fit_tau(points)
        repositories.append(
            {
                "repo_id": repo_id,
                "repo_path": rows[0].get("repo_path", ""),
                "repo_source": rows[0].get("repo_source", "real"),
                "rows": len(rows),
                "tau_estimate": fit["tau"],
                "r2": fit["r2"],
                "mse": fit["mse"],
                "best_fit_curve": "saturating_exponential",
                "diminishing_return_bucket": _diminishing_bucket(points),
                "best_success_per_token_bucket": _best_efficiency_bucket(points),
                "points": [{"context_tokens": x, "success_rate": y} for x, y in points],
            }
        )
    return {"object": "agent_hub.research.cross_repo_tau", "repositories": repositories}


def export_cross_repo_tau(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = compute_cross_repo_tau(state_dir)
    json_path = directory / "cross_repo_tau.json"
    md_path = directory / "cross_repo_tau.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _rows(state_dir: str | Path) -> list[dict[str, Any]]:
    path = cross_repo_experiment_path(state_dir)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _points(rows: list[dict[str, Any]]) -> list[tuple[float, float]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[context_bucket(row.get("context_token_count"))].append(row)
    points = []
    for items in grouped.values():
        if not items:
            continue
        tokens = sum(float(item.get("context_token_count") or 0.0) for item in items) / len(items)
        success = sum(1 for item in items if item.get("success") is True) / len(items)
        points.append((tokens, success))
    points.sort(key=lambda item: item[0])
    return points


def _fit_tau(points: list[tuple[float, float]]) -> dict[str, float]:
    best_tau = 0.0
    best_predictions: list[float] = []
    best_mse = float("inf")
    targets = [y for _x, y in points]
    for tau in _grid(100.0, 20_000.0, 300):
        predictions = [1.0 - math.exp(-x / tau) for x, _y in points]
        mse = _mse(targets, predictions)
        if mse < best_mse:
            best_tau = tau
            best_mse = mse
            best_predictions = predictions
    return {"tau": round(best_tau, 6), "r2": round(_r2(targets, best_predictions), 6), "mse": round(best_mse, 10)}


def _diminishing_bucket(points: list[tuple[float, float]]) -> str:
    previous_gain: float | None = None
    previous_y = 0.0
    for x, y in points:
        gain = y - previous_y
        if previous_gain is not None and gain < previous_gain:
            return context_bucket(x)
        previous_gain = gain
        previous_y = y
    return "not_detected"


def _best_efficiency_bucket(points: list[tuple[float, float]]) -> str:
    best_bucket = "not_enough_data"
    best_score = -1.0
    for x, y in points:
        if x <= 0:
            continue
        score = y / (x / 1000.0)
        if score > best_score:
            best_score = score
            best_bucket = context_bucket(x)
    return best_bucket


def _grid(start: float, stop: float, count: int) -> list[float]:
    step = (stop - start) / max(1, count - 1)
    return [start + step * index for index in range(count)]


def _mse(targets: list[float], predictions: list[float]) -> float:
    return sum((target - pred) ** 2 for target, pred in zip(targets, predictions)) / len(targets) if targets else 0.0


def _r2(targets: list[float], predictions: list[float]) -> float:
    if not targets:
        return 0.0
    mean = sum(targets) / len(targets)
    total = sum((target - mean) ** 2 for target in targets)
    residual = sum((target - pred) ** 2 for target, pred in zip(targets, predictions))
    return 1.0 - residual / total if total else 1.0


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Cross-Repository Tau Validation",
        "",
        "| repository | source | rows | tau | R2 | MSE | diminishing bucket | best efficiency bucket |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for repo in payload.get("repositories", []):
        lines.append(
            f"| {repo.get('repo_id')} | {repo.get('repo_source')} | {repo.get('rows')} | {repo.get('tau_estimate')} | {repo.get('r2')} | {repo.get('mse')} | {repo.get('diminishing_return_bucket')} | {repo.get('best_success_per_token_bucket')} |"
        )
    lines.append("")
    return "\n".join(lines)


__all__ = ["compute_cross_repo_tau", "export_cross_repo_tau"]
