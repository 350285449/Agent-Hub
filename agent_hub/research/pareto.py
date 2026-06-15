from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ModelObjective:
    model: str
    quality: float
    cost: float
    latency: float
    task_type: str = ""


def dominates(a: ModelObjective, b: ModelObjective) -> bool:
    return (
        a.quality >= b.quality
        and a.cost <= b.cost
        and a.latency <= b.latency
        and (
            a.quality > b.quality
            or a.cost < b.cost
            or a.latency < b.latency
        )
    )


def pareto_frontier(points: Iterable[ModelObjective]) -> list[ModelObjective]:
    rows = list(points)
    frontier = [
        candidate
        for candidate in rows
        if not any(dominates(other, candidate) for other in rows if other is not candidate)
    ]
    return sorted(frontier, key=lambda item: (-item.quality, item.cost, item.latency, item.model))


__all__ = ["ModelObjective", "dominates", "pareto_frontier"]
