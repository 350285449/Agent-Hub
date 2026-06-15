from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .metrics import load_research_runs
from .telemetry import research_dir


DATASET_FIELDS = [
    "task_type",
    "model",
    "context_tokens",
    "file_count",
    "latency",
    "cost",
    "validation_score",
    "success",
]


def dataset_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "dataset.csv"


def dataset_rows(state_dir: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in load_research_runs(state_dir):
        if run.get("success") is None:
            continue
        context_files = run.get("context_files") if isinstance(run.get("context_files"), list) else []
        rows.append(
            {
                "task_type": run.get("task_type", ""),
                "model": run.get("selected_model", ""),
                "context_tokens": int(run.get("context_token_count") or 0),
                "file_count": len(context_files),
                "latency": float(run.get("latency_ms") or 0.0),
                "cost": float(run.get("cost_estimate") or 0.0),
                "validation_score": float(run.get("validation_score") or 0.0),
                "success": bool(run.get("success")),
            }
        )
    return rows


def export_dataset_csv(state_dir: str | Path, output: str | Path | None = None) -> Path:
    path = Path(output) if output is not None else dataset_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_FIELDS)
        writer.writeheader()
        for row in dataset_rows(state_dir):
            writer.writerow(row)
    return path


__all__ = ["DATASET_FIELDS", "dataset_path", "dataset_rows", "export_dataset_csv"]
