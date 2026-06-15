from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class SuccessKey:
    model: str
    task_type: str
    context_level: str


class BayesianSuccessRouter:
    def __init__(self) -> None:
        self._counts: dict[SuccessKey, tuple[int, int]] = {}

    def record(self, model: str, task_type: str, context_level: str, *, success: bool) -> None:
        key = SuccessKey(model, task_type, context_level)
        successes, failures = self._counts.get(key, (0, 0))
        if success:
            successes += 1
        else:
            failures += 1
        self._counts[key] = (successes, failures)

    def expected_success(self, model: str, task_type: str, context_level: str) -> float:
        successes, failures = self._counts.get(SuccessKey(model, task_type, context_level), (0, 0))
        alpha = successes + 1
        beta = failures + 1
        return alpha / (alpha + beta)

    def score(
        self,
        model: str,
        task_type: str,
        context_level: str,
        *,
        cost: float = 0.0,
        latency_ms: float = 0.0,
        cost_weight: float = 1.0,
        latency_weight: float = 0.001,
    ) -> float:
        return (
            self.expected_success(model, task_type, context_level)
            - max(0.0, cost) * cost_weight
            - max(0.0, latency_ms) * latency_weight
        )

    def choose(
        self,
        candidates: Iterable[str],
        task_type: str,
        context_level: str,
        *,
        costs: dict[str, float] | None = None,
        latencies_ms: dict[str, float] | None = None,
    ) -> str:
        rows = list(candidates)
        if not rows:
            raise ValueError("Cannot choose without candidates")
        costs = costs or {}
        latencies_ms = latencies_ms or {}
        return max(
            rows,
            key=lambda model: (
                self.score(
                    model,
                    task_type,
                    context_level,
                    cost=costs.get(model, 0.0),
                    latency_ms=latencies_ms.get(model, 0.0),
                ),
                model,
            ),
        )

    def to_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for key, (successes, failures) in sorted(self._counts.items(), key=lambda item: (item[0].task_type, item[0].model)):
            rows.append(
                {
                    "model": key.model,
                    "task_type": key.task_type,
                    "context_level": key.context_level,
                    "successes": successes,
                    "failures": failures,
                    "expected_success": self.expected_success(key.model, key.task_type, key.context_level),
                }
            )
        return rows


__all__ = ["BayesianSuccessRouter", "SuccessKey"]
