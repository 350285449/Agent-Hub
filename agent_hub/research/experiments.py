from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


CONTEXT_LEVELS = (0, 25, 50, 75, 100)


@dataclass(slots=True)
class ContextAblationResult:
    context_percent: int
    success: bool
    validation_score: float
    tokens_used: int
    latency_ms: float
    cost: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_percent": self.context_percent,
            "success": self.success,
            "validation_score": self.validation_score,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "cost": self.cost,
        }


class ContextAblationExperiment:
    def __init__(self, runner: Callable[[Any, int], dict[str, Any]]) -> None:
        self.runner = runner

    def run(self, task: Any, levels: tuple[int, ...] = CONTEXT_LEVELS) -> list[ContextAblationResult]:
        results: list[ContextAblationResult] = []
        for level in levels:
            row = self.runner(task, level)
            results.append(
                ContextAblationResult(
                    context_percent=int(level),
                    success=bool(row.get("success")),
                    validation_score=float(row.get("validation_score") or 0.0),
                    tokens_used=int(row.get("tokens_used") or row.get("input_tokens") or 0),
                    latency_ms=float(row.get("latency_ms") or 0.0),
                    cost=float(row.get("cost") or row.get("cost_estimate") or 0.0),
                )
            )
        return results


__all__ = ["CONTEXT_LEVELS", "ContextAblationExperiment", "ContextAblationResult"]
