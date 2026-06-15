from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..research.information_context import select_ranked_files_by_information_density
from .file_ranker import FileRanker, RankedFile


class ContextLevel(str, Enum):
    FULL = "FULL"
    COMPRESSED = "COMPRESSED"
    SYMBOL_MAP = "SYMBOL_MAP"
    SUMMARY_ONLY = "SUMMARY_ONLY"
    OMITTED = "OMITTED"


LEGACY_LEVEL_LABELS = {
    ContextLevel.FULL: "Full",
    ContextLevel.COMPRESSED: "Compressed",
    ContextLevel.SYMBOL_MAP: "Map",
    ContextLevel.SUMMARY_ONLY: "Summary",
    ContextLevel.OMITTED: "Omitted",
}


@dataclass(frozen=True, slots=True)
class ContextFile:
    path: str
    level: ContextLevel
    estimated_tokens: int
    reason: str = ""
    confidence: float = 0.0
    score: float = 0.0

    @property
    def legacy_level(self) -> str:
        return LEGACY_LEVEL_LABELS.get(self.level, self.level.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "level": self.level.value,
            "display_level": self.legacy_level,
            "estimated_tokens": self.estimated_tokens,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
            "score": round(self.score, 3),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextFile":
        raw_level = str(data.get("level") or data.get("display_level") or ContextLevel.COMPRESSED.value)
        level = _level_from_any(raw_level)
        return cls(
            path=str(data.get("path") or ""),
            level=level,
            estimated_tokens=_int(data.get("estimated_tokens"), 0),
            reason=str(data.get("reason") or ""),
            confidence=_float(data.get("confidence"), 0.0),
            score=_float(data.get("score"), 0.0),
        )


@dataclass(frozen=True, slots=True)
class ContextPlan:
    context_files: list[ContextFile]
    selected_ranked_files: list[RankedFile] = field(default_factory=list, repr=False)
    omitted_ranked_files: list[RankedFile] = field(default_factory=list, repr=False)
    raw_context_tokens: int = 0
    optimized_context_tokens: int = 0
    total_files: int = 0
    reason: str = ""

    @property
    def selected_files(self) -> list[str]:
        return [
            file.path
            for file in self.context_files
            if file.level is not ContextLevel.OMITTED
        ]

    @property
    def omitted_files(self) -> list[str]:
        return [
            file.path
            for file in self.context_files
            if file.level is ContextLevel.OMITTED
        ]

    def legacy_levels(self) -> dict[str, str]:
        return {
            file.path: file.legacy_level
            for file in self.context_files
            if file.level is not ContextLevel.OMITTED
        }

    def level_counts(self) -> dict[str, int]:
        counts = {level.value: 0 for level in ContextLevel}
        for file in self.context_files:
            counts[file.level.value] = counts.get(file.level.value, 0) + 1
        selected_count = len(self.selected_files)
        if self.total_files > selected_count:
            counts[ContextLevel.OMITTED.value] = max(
                counts.get(ContextLevel.OMITTED.value, 0),
                self.total_files - selected_count,
            )
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.context_plan",
            "selected_files": self.selected_files,
            "omitted_files": self.omitted_files,
            "context_levels": self.legacy_levels(),
            "context_files": [file.to_dict() for file in self.context_files],
            "level_counts": self.level_counts(),
            "raw_context_tokens": self.raw_context_tokens,
            "optimized_context_tokens": self.optimized_context_tokens,
            "total_files": self.total_files,
            "reason": self.reason,
        }


class ContextPlanner:
    """Decide repository context shape from ranked file evidence."""

    def __init__(self, index: Any, *, ranker: FileRanker | None = None) -> None:
        self.index = index
        self.ranker = ranker or FileRanker(index)

    def plan(
        self,
        task: str,
        *,
        max_files: int = 8,
        full_files: int = 2,
        compressed_files: int = 4,
        map_files: int = 6,
        compression_aggression: float = 0.55,
        research_mode: bool = False,
        token_budget: int | None = None,
    ) -> ContextPlan:
        ranked = self.ranker.rank_files(task, limit=max(80, max_files * 6))
        if research_mode:
            selected = select_ranked_files_by_information_density(
                ranked,
                max_files=max(1, max_files),
                token_budget=token_budget or max(1, max_files) * 900,
            )
        else:
            selected = self.ranker.select_diverse(ranked, max_files=max(1, max_files), task=task)
        selected_paths = {item.path for item in selected}
        omitted_ranked = [item for item in ranked if item.path not in selected_paths]
        context_files: list[ContextFile] = []
        for index, item in enumerate(selected):
            level = _level_for_index(
                index,
                file_size=_int(getattr(item.file, "size", 0), 0),
                full_files=full_files,
                compressed_files=compressed_files,
                map_files=map_files,
            )
            context_files.append(
                ContextFile(
                    path=item.path,
                    level=level,
                    estimated_tokens=_estimated_tokens(
                        _int(getattr(item.file, "size", 0), 0),
                        level=level,
                        compression_aggression=compression_aggression,
                    ),
                    reason=_reason_for_ranked_file(item),
                    confidence=_confidence(item.score),
                    score=item.score,
                )
            )
        for item in omitted_ranked[:40]:
            context_files.append(
                ContextFile(
                    path=item.path,
                    level=ContextLevel.OMITTED,
                    estimated_tokens=0,
                    reason=_reason_for_ranked_file(item) or "Ranked below context budget.",
                    confidence=_confidence(item.score),
                    score=item.score,
                )
            )
        raw_tokens = sum(max(1, _int(getattr(item.file, "size", 0), 0) // 4) for item in selected)
        optimized_tokens = sum(file.estimated_tokens for file in context_files if file.level is not ContextLevel.OMITTED)
        return ContextPlan(
            context_files=context_files,
            selected_ranked_files=selected,
            omitted_ranked_files=omitted_ranked,
            raw_context_tokens=raw_tokens,
            optimized_context_tokens=optimized_tokens,
            total_files=self.ranker.total_rankable_files(),
            reason=(
                "Selected by research information-density per token."
                if research_mode
                else _selection_reason(selected)
            ),
        )


def _level_for_index(
    index: int,
    *,
    file_size: int,
    full_files: int,
    compressed_files: int,
    map_files: int,
) -> ContextLevel:
    full_limit = max(0, full_files)
    compressed_limit = full_limit + max(0, compressed_files)
    map_limit = compressed_limit + max(0, map_files)
    if index < full_limit and file_size <= 80_000:
        return ContextLevel.FULL
    if index < compressed_limit:
        return ContextLevel.COMPRESSED
    if index < map_limit:
        return ContextLevel.SYMBOL_MAP
    return ContextLevel.SUMMARY_ONLY


def _estimated_tokens(file_size: int, *, level: ContextLevel, compression_aggression: float) -> int:
    raw_tokens = max(1, file_size // 4)
    if level is ContextLevel.FULL:
        return min(raw_tokens, 2_000)
    if level is ContextLevel.SYMBOL_MAP:
        return min(max(60, raw_tokens // 10), 300)
    if level is ContextLevel.SUMMARY_ONLY:
        return min(max(80, raw_tokens // 8), 420)
    ratio = max(0.08, 0.35 - min(0.24, max(0.0, compression_aggression) * 0.18))
    return min(max(150, int(raw_tokens * ratio)), 800)


def _selection_reason(items: list[RankedFile]) -> str:
    signals: list[str] = []
    for item in items[:8]:
        signals.extend(item.signals)
    if not signals:
        return "Selected important or recently changed repository files."
    return "Matched " + ", ".join(_dedupe(signals)[:6]) + "."


def _reason_for_ranked_file(item: RankedFile) -> str:
    if item.signals:
        return ", ".join(_dedupe(item.signals)[:4])
    return "Selected by repository relevance score."


def _confidence(score: float) -> float:
    return max(0.05, min(0.99, float(score or 0.0) / 100.0))


def _level_from_any(value: str) -> ContextLevel:
    normalized = value.strip().upper().replace(" ", "_")
    legacy = {
        "FULL": ContextLevel.FULL,
        "COMPRESSED": ContextLevel.COMPRESSED,
        "MAP": ContextLevel.SYMBOL_MAP,
        "SYMBOL_MAP": ContextLevel.SYMBOL_MAP,
        "SUMMARY": ContextLevel.SUMMARY_ONLY,
        "SUMMARY_ONLY": ContextLevel.SUMMARY_ONLY,
        "OMITTED": ContextLevel.OMITTED,
    }
    return legacy.get(normalized, ContextLevel.COMPRESSED)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

