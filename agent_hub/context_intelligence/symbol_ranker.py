from __future__ import annotations

import ast
from pathlib import Path


def rank_symbols(root: str | Path, query: str = "", *, limit: int = 50, max_files: int = 250) -> list[dict[str, object]]:
    root = Path(root)
    terms = {term.lower() for term in query.replace("_", " ").split() if len(term) > 2}
    rows: list[dict[str, object]] = []
    for index, path in enumerate(_files(root)):
        if index >= max_files:
            break
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                score = 1.0 + sum(2.0 for term in terms if term in name.lower())
                rows.append({"file": str(path.relative_to(root)), "symbol": name, "line": getattr(node, "lineno", 0), "score": score})
    return sorted(rows, key=lambda row: (-float(row["score"]), str(row["file"]), int(row["line"])))[:limit]


def _files(root: Path):
    ignored = {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}
    for path in root.rglob("*"):
        if path.is_file() and not any(part in ignored for part in path.parts):
            yield path
