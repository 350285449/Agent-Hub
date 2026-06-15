from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .datasets import CONTEXT_ABLATION_LEVELS, context_ablation_variants
from .telemetry import research_dir


@dataclass(slots=True)
class ContextAblationRecord:
    task_id: str
    context_percent: int
    success: bool
    validation_score: float
    tokens_used: int
    latency_ms: float
    cost: float
    model: str = ""
    task_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def context_ablation_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "context_ablation.jsonl"


def append_context_ablation_result(state_dir: str | Path, record: ContextAblationRecord | dict[str, Any]) -> Path:
    path = context_ablation_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = record.to_dict() if isinstance(record, ContextAblationRecord) else dict(record)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def build_context_ablation_tasks(task: dict[str, Any]) -> list[dict[str, Any]]:
    return context_ablation_variants(task, levels=CONTEXT_ABLATION_LEVELS)


__all__ = [
    "CONTEXT_ABLATION_LEVELS",
    "ContextAblationRecord",
    "append_context_ablation_result",
    "build_context_ablation_tasks",
    "context_ablation_path",
]
