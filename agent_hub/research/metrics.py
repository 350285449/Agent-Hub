from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .telemetry import runs_path


@dataclass(slots=True)
class ResearchSummary:
    total_runs: int
    outcomes: int
    success_rate: float
    average_validation_score: float
    average_latency_ms: float
    total_cost_estimate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "outcomes": self.outcomes,
            "success_rate": self.success_rate,
            "average_validation_score": self.average_validation_score,
            "average_latency_ms": self.average_latency_ms,
            "total_cost_estimate": self.total_cost_estimate,
        }


def load_research_runs(state_dir: str | Path) -> list[dict[str, Any]]:
    path = runs_path(state_dir)
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def summarize_runs(rows: list[dict[str, Any]]) -> ResearchSummary:
    outcomes = [row for row in rows if row.get("success") is not None]
    successes = sum(1 for row in outcomes if row.get("success") is True)
    validation_total = sum(float(row.get("validation_score") or 0.0) for row in outcomes)
    latency_total = sum(float(row.get("latency_ms") or 0.0) for row in outcomes)
    return ResearchSummary(
        total_runs=len(rows),
        outcomes=len(outcomes),
        success_rate=round(successes / len(outcomes), 4) if outcomes else 0.0,
        average_validation_score=round(validation_total / len(outcomes), 4) if outcomes else 0.0,
        average_latency_ms=round(latency_total / len(outcomes), 2) if outcomes else 0.0,
        total_cost_estimate=round(sum(float(row.get("cost_estimate") or 0.0) for row in outcomes), 8),
    )


def wilson_interval(successes: int, total: int, *, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * ((p * (1 - p) + z * z / (4 * total)) / total) ** 0.5 / denominator
    return (round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4))


__all__ = ["ResearchSummary", "load_research_runs", "summarize_runs", "wilson_interval"]
