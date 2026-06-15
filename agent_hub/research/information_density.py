from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .file_stats import load_file_stats
from .metrics import load_research_runs
from .telemetry import research_dir


def compute_information_density(state_dir: str | Path) -> dict[str, Any]:
    runs = [row for row in load_research_runs(state_dir) if row.get("success") is not None]
    stats = load_file_stats(state_dir)
    context_tokens: dict[str, list[int]] = defaultdict(list)
    for row in runs:
        files = row.get("context_files") if isinstance(row.get("context_files"), list) else []
        for path in files:
            context_tokens[str(path)].append(int(row.get("context_token_count") or 0))
    files: dict[str, dict[str, Any]] = {}
    for path, row in sorted(stats.items()):
        times = int(row.get("selections") or 0)
        successes = int(row.get("successful_inclusions") or 0)
        failures = int(row.get("failed_inclusions") or 0)
        average_validation = float(row.get("average_validation_score") or 0.0)
        average_context = _average(context_tokens.get(path, []))
        success_rate = successes / max(1, times)
        files[path] = {
            "times_selected": times,
            "successful_inclusions": successes,
            "failed_inclusions": failures,
            "success_rate_when_selected": round(success_rate, 6),
            "average_validation_score": round(average_validation, 6),
            "average_context_tokens_when_selected": round(average_context, 6),
            "information_density": round(success_rate * average_validation / max(1.0, average_context), 10),
        }
    return {"object": "agent_hub.research.information_density", "files": files}


def export_information_density_json(state_dir: str | Path, output: str | Path | None = None) -> Path:
    path = Path(output) if output is not None else research_dir(state_dir) / "information_density.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(compute_information_density(state_dir), indent=2, sort_keys=True), encoding="utf-8")
    return path


def top_information_density_files(state_dir: str | Path, *, limit: int = 20) -> list[dict[str, Any]]:
    payload = compute_information_density(state_dir)
    rows = [{"path": path, **data} for path, data in payload["files"].items()]
    rows.sort(key=lambda row: (-float(row.get("information_density") or 0.0), row["path"]))
    return rows[: max(1, limit)]


def _average(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


__all__ = [
    "compute_information_density",
    "export_information_density_json",
    "top_information_density_files",
]
