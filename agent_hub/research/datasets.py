from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONTEXT_ABLATION_LEVELS = (0, 25, 50, 75, 100)


def load_jsonl_dataset(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def write_jsonl_dataset(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return target


def context_ablation_variants(task: dict[str, Any], *, levels: tuple[int, ...] = CONTEXT_ABLATION_LEVELS) -> list[dict[str, Any]]:
    base_id = str(task.get("task_id") or task.get("id") or "task")
    variants: list[dict[str, Any]] = []
    for level in levels:
        variants.append(
            {
                **task,
                "task_id": f"{base_id}:context-{level}",
                "ablation_parent_task_id": base_id,
                "context_percent": int(level),
                "research_experiment": "context_ablation",
            }
        )
    return variants


def write_context_ablation_dataset(
    path: str | Path,
    tasks: list[dict[str, Any]],
    *,
    levels: tuple[int, ...] = CONTEXT_ABLATION_LEVELS,
) -> Path:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        rows.extend(context_ablation_variants(task, levels=levels))
    return write_jsonl_dataset(path, rows)


__all__ = [
    "CONTEXT_ABLATION_LEVELS",
    "context_ablation_variants",
    "load_jsonl_dataset",
    "write_context_ablation_dataset",
    "write_jsonl_dataset",
]
