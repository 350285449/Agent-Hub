from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def file_stats_path(state_dir: str | Path) -> Path:
    return _research_dir(state_dir) / "file_stats.json"


def load_file_stats(state_dir: str | Path) -> dict[str, dict[str, Any]]:
    path = file_stats_path(state_dir)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    files = raw.get("files") if isinstance(raw, dict) else raw
    return files if isinstance(files, dict) else {}


def save_file_stats(state_dir: str | Path, stats: dict[str, dict[str, Any]]) -> Path:
    path = file_stats_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"object": "agent_hub.research.file_stats", "files": stats}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def update_file_stats(state_dir: str | Path, run: Any) -> dict[str, dict[str, Any]]:
    data = run.to_dict() if hasattr(run, "to_dict") else dict(run)
    files = [str(item) for item in data.get("context_files") or [] if str(item)]
    if not files:
        return load_file_stats(state_dir)
    success = data.get("success")
    validation_score = float(data.get("validation_score") or 0.0)
    stats = load_file_stats(state_dir)
    for path in files:
        row = stats.setdefault(
            path,
            {
                "selections": 0,
                "successful_inclusions": 0,
                "failed_inclusions": 0,
                "average_validation_score": 0.0,
                "validation_score_total": 0.0,
            },
        )
        row["selections"] = int(row.get("selections") or 0) + 1
        if success is True:
            row["successful_inclusions"] = int(row.get("successful_inclusions") or 0) + 1
        elif success is False:
            row["failed_inclusions"] = int(row.get("failed_inclusions") or 0) + 1
        row["validation_score_total"] = float(row.get("validation_score_total") or 0.0) + validation_score
        row["average_validation_score"] = round(
            float(row["validation_score_total"]) / max(1, int(row["selections"])),
            4,
        )
    save_file_stats(state_dir, stats)
    return stats


def most_useful_files(state_dir: str | Path, *, limit: int = 20) -> list[dict[str, Any]]:
    stats = load_file_stats(state_dir)
    rows = [{"path": path, **data} for path, data in stats.items()]
    rows.sort(
        key=lambda row: (
            -float(row.get("average_validation_score") or 0.0),
            -int(row.get("successful_inclusions") or 0),
            -int(row.get("selections") or 0),
            row.get("path", ""),
        )
    )
    return rows[: max(1, limit)]


def _research_dir(state_dir: str | Path) -> Path:
    state = Path(state_dir)
    if state.name == "state":
        return state.parent / "research"
    return state / "research"


__all__ = [
    "file_stats_path",
    "load_file_stats",
    "most_useful_files",
    "save_file_stats",
    "update_file_stats",
]
