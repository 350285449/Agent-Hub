from __future__ import annotations

import re
from pathlib import Path


def rank_error_paths(error_text: str, root: str | Path | None = None) -> list[dict[str, object]]:
    root_path = Path(root).resolve() if root else None
    rows = []
    pattern = re.compile(r"([A-Za-z]:\\[^\s:]+|[./\w-]+(?:/|\\)[\w./\\-]+):(\d+)")
    for match in pattern.finditer(error_text or ""):
        file_name = match.group(1)
        line = int(match.group(2))
        path = Path(file_name)
        rel = file_name
        if root_path:
            try:
                rel = str(path.resolve().relative_to(root_path))
            except (OSError, ValueError):
                rel = file_name
        rows.append({"file": rel, "line": line, "score": 10.0})
    return rows
