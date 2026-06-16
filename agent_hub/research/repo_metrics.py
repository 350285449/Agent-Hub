from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .telemetry import research_dir


CODE_SUFFIXES = {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs"}


def compute_repo_metrics(repo_path: str | Path) -> dict[str, Any]:
    root = Path(repo_path)
    files = [path for path in _iter_files(root) if path.suffix.lower() in CODE_SUFFIXES or path.suffix.lower() in {".md", ".toml", ".json", ".yaml", ".yml"}]
    py_files = [path for path in files if path.suffix.lower() == ".py"]
    code_files = [path for path in files if path.suffix.lower() in CODE_SUFFIXES]
    line_counts = [_line_count(path) for path in code_files]
    import_count = sum(_import_count(path) for path in py_files)
    test_count = sum(1 for path in py_files if path.name.startswith("test_") or "/tests/" in _rel(root, path))
    loc = sum(line_counts)
    average = loc / len(code_files) if code_files else 0.0
    complexity = loc / 1000.0 + len(code_files) * 0.1 + import_count * 0.05 + test_count * 0.2
    return {
        "repo_id": _repo_id(root),
        "path": str(root),
        "synthetic": _is_synthetic(root),
        "total_loc": loc,
        "file_count": len(files),
        "python_file_count": len(py_files),
        "average_file_length": round(average, 6),
        "max_file_length": max(line_counts) if line_counts else 0,
        "directory_count": sum(1 for path in root.rglob("*") if path.is_dir() and not _ignored(path)),
        "estimated_dependency_import_count": import_count,
        "test_file_count": test_count,
        "approximate_complexity_score": round(complexity, 6),
    }


def compute_repo_metrics_for_paths(paths: list[str | Path]) -> dict[str, Any]:
    repos = [compute_repo_metrics(path) for path in paths]
    return {"object": "agent_hub.research.repo_metrics", "repositories": repos}


def export_repo_metrics(state_dir: str | Path, paths: list[str | Path], output: str | Path | None = None) -> Path:
    path = Path(output) if output is not None else research_dir(state_dir) / "repo_metrics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(compute_repo_metrics_for_paths(paths), indent=2, sort_keys=True), encoding="utf-8")
    return path


def _iter_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file() and not _ignored(path)]


def _ignored(path: Path) -> bool:
    ignored = {".git", ".agent-hub", "__pycache__", ".pytest_cache", "node_modules", "dist", "build", ".venv"}
    return any(part in ignored for part in path.parts)


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0


def _import_count(path: Path) -> int:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return 0
    return sum(1 for line in lines if line.strip().startswith(("import ", "from ")))


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _repo_id(path: Path) -> str:
    return path.name.replace(" ", "-").replace("(", "").replace(")", "").lower()


def _is_synthetic(path: Path) -> bool:
    return ".agent-hub" in path.parts and "synthetic_repos" in path.parts


__all__ = ["compute_repo_metrics", "compute_repo_metrics_for_paths", "export_repo_metrics"]
