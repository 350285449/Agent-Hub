from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def append_jsonl(path: str | Path, row: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")


def read_jsonl(path: str | Path, *, limit: int = 5000) -> list[dict[str, Any]]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines[-max(1, int(limit)) :]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def append_outcome(path: str | Path, row: dict[str, Any]) -> dict[str, Any]:
    stored = dict(row)
    stored.setdefault("time", time.time())
    append_jsonl(path, stored)
    return stored


def prune_jsonl(path: str | Path, *, max_rows: int = 5000) -> int:
    path = Path(path)
    rows = read_jsonl(path, limit=max_rows * 2)
    kept = rows[-max(1, int(max_rows)) :]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n" for row in kept),
        encoding="utf-8",
    )
    return len(rows) - len(kept)
