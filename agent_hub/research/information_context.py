from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ContextFileSignal:
    path: str
    file_relevance: float
    token_count: int
    historical_success_lift: float = 0.0
    redundancy_score: float = 0.0

    @property
    def success_lift(self) -> float:
        return max(0.0, self.file_relevance + self.historical_success_lift - self.redundancy_score)

    @property
    def information_density(self) -> float:
        return self.success_lift / max(1, self.token_count)


def select_context_files(files: Iterable[ContextFileSignal], token_budget: int) -> list[ContextFileSignal]:
    remaining = max(0, int(token_budget))
    selected: list[ContextFileSignal] = []
    for item in sorted(files, key=lambda file: (-file.information_density, -file.success_lift, file.token_count, file.path)):
        if item.token_count <= 0:
            continue
        if item.token_count <= remaining:
            selected.append(item)
            remaining -= item.token_count
    return selected


__all__ = ["ContextFileSignal", "select_context_files"]
