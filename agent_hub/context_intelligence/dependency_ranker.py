from __future__ import annotations

from pathlib import Path


def rank_dependencies(root: str | Path, changed_files: list[str] | None = None, *, limit: int = 50) -> list[dict[str, object]]:
    root = Path(root)
    changed = {Path(item).stem.lower() for item in changed_files or []}
    rows: list[dict[str, object]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".js", ".ts", ".tsx"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        score = 1.0 + sum(3.0 for name in changed if name and name in text.lower())
        if score > 1.0 or path.name in {"pyproject.toml", "package.json"}:
            rows.append({"file": rel, "score": score})
    return sorted(rows, key=lambda row: (-float(row["score"]), str(row["file"])))[:limit]
