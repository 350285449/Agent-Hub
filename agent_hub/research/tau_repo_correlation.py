from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .repo_metrics import compute_repo_metrics
from .tau_validation import compute_cross_repo_tau
from .telemetry import research_dir


METRICS = (
    "total_loc",
    "file_count",
    "average_file_length",
    "max_file_length",
    "estimated_dependency_import_count",
    "test_file_count",
    "approximate_complexity_score",
)


def compute_tau_repo_correlation(state_dir: str | Path) -> dict[str, Any]:
    tau_payload = compute_cross_repo_tau(state_dir)
    repos = tau_payload.get("repositories") if isinstance(tau_payload.get("repositories"), list) else []
    joined = []
    for repo in repos:
        metrics = compute_repo_metrics(repo.get("repo_path", ""))
        joined.append({"repo_id": repo.get("repo_id"), "tau": repo.get("tau_estimate"), "metrics": metrics})
    correlations = {
        metric: round(_pearson([float(row["tau"] or 0.0) for row in joined], [float(row["metrics"].get(metric) or 0.0) for row in joined]), 6)
        for metric in METRICS
    }
    return {
        "object": "agent_hub.research.tau_repo_correlation",
        "repository_count": len(joined),
        "correlations": correlations,
        "repositories": joined,
    }


def export_tau_repo_correlation(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = compute_tau_repo_correlation(state_dir)
    json_path = directory / "tau_repo_correlation.json"
    md_path = directory / "tau_repo_correlation.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(ys) < 2:
        return 0.0
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = sum((x - mean_x) ** 2 for x in xs)
    denom_y = sum((y - mean_y) ** 2 for y in ys)
    denom = (denom_x * denom_y) ** 0.5
    return numerator / denom if denom else 0.0


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Tau Repository Correlation",
        "",
        f"Repository count: {payload.get('repository_count')}",
        "",
        "| metric | Pearson correlation with tau |",
        "| --- | --- |",
    ]
    correlations = payload.get("correlations") if isinstance(payload.get("correlations"), dict) else {}
    for metric, value in correlations.items():
        lines.append(f"| {metric} | {value} |")
    lines.append("")
    return "\n".join(lines)


__all__ = ["compute_tau_repo_correlation", "export_tau_repo_correlation"]
