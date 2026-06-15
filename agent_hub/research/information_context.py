from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


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

    @classmethod
    def from_ranked_file(
        cls,
        ranked_file: Any,
        *,
        historical_success_lift: float = 0.0,
        redundancy_score: float = 0.0,
    ) -> "ContextFileSignal":
        file_obj = getattr(ranked_file, "file", ranked_file)
        return cls(
            path=str(getattr(ranked_file, "path", getattr(file_obj, "path", ""))).replace("\\", "/"),
            file_relevance=float(getattr(ranked_file, "score", 0.0) or 0.0),
            token_count=max(1, int(getattr(file_obj, "size", 0) or 0) // 4),
            historical_success_lift=historical_success_lift,
            redundancy_score=redundancy_score,
        )


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


def select_ranked_files_by_information_density(
    ranked_files: list[Any],
    *,
    max_files: int,
    token_budget: int,
    historical_success_lift: dict[str, float] | None = None,
) -> list[Any]:
    lifts = historical_success_lift or {}
    by_path = {
        signal.path: signal
        for signal in (
            ContextFileSignal.from_ranked_file(
                item,
                historical_success_lift=float(lifts.get(str(getattr(item, "path", "")), 0.0) or 0.0),
                redundancy_score=_redundancy_score(item, ranked_files),
            )
            for item in ranked_files
        )
    }
    selected_signals = select_context_files(by_path.values(), token_budget=token_budget)
    selected_paths = {signal.path for signal in selected_signals[: max(1, max_files)]}
    return [item for item in ranked_files if str(getattr(item, "path", "")).replace("\\", "/") in selected_paths][: max(1, max_files)]


def compare_context_rankings(heuristic: list[str], information_density: list[str]) -> dict[str, Any]:
    heuristic_positions = {path: index for index, path in enumerate(heuristic)}
    density_positions = {path: index for index, path in enumerate(information_density)}
    overlap = set(heuristic_positions) & set(density_positions)
    rank_deltas = {
        path: heuristic_positions[path] - density_positions[path]
        for path in sorted(overlap)
    }
    return {
        "heuristic_count": len(heuristic),
        "information_density_count": len(information_density),
        "overlap_count": len(overlap),
        "jaccard_overlap": round(len(overlap) / max(1, len(set(heuristic) | set(information_density))), 4),
        "rank_deltas": rank_deltas,
        "density_only": [path for path in information_density if path not in heuristic_positions],
        "heuristic_only": [path for path in heuristic if path not in density_positions],
    }


def _redundancy_score(item: Any, ranked_files: list[Any]) -> float:
    path = str(getattr(item, "path", "")).replace("\\", "/")
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    if not folder:
        return 0.0
    siblings = sum(
        1
        for other in ranked_files
        if other is not item and str(getattr(other, "path", "")).replace("\\", "/").startswith(folder + "/")
    )
    return min(10.0, siblings * 0.5)


__all__ = [
    "ContextFileSignal",
    "compare_context_rankings",
    "select_context_files",
    "select_ranked_files_by_information_density",
]
