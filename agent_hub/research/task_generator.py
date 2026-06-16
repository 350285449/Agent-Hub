from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .telemetry import research_dir


REPOSITORIES = ("Agent-Hub", "ytdl_site", "face")
TASK_CATEGORIES = (
    "bug_fix",
    "code_generation",
    "refactor",
    "testing",
    "analysis",
    "architecture",
    "documentation",
)
EXPECTED_OUTPUT_TYPES = {
    "bug_fix": "diagnosis_and_patch_plan",
    "code_generation": "implementation_plan_and_code",
    "refactor": "refactor_plan",
    "testing": "test_plan",
    "analysis": "analysis_report",
    "architecture": "architecture_decision_record",
    "documentation": "documentation_patch",
}
RELEVANT_SUFFIXES = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".md",
    ".html",
    ".css",
}
DEFAULT_TASKS_PER_CATEGORY = 10


@dataclass(frozen=True, slots=True)
class BenchmarkTask:
    task_id: str
    category: str
    repository: str
    description: str
    expected_output_type: str
    focus_files: tuple[str, ...] = ()
    constraints: tuple[str, ...] = (
        "Use repository evidence from the provided context.",
        "Do not assume hidden files or external benchmark scores.",
        "Return concrete validation steps.",
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["focus_files"] = list(self.focus_files)
        payload["constraints"] = list(self.constraints)
        return payload


def default_repo_roots(cwd: Path | None = None) -> dict[str, Path]:
    root = (cwd or Path.cwd()).resolve()
    return {
        "Agent-Hub": root,
        "ytdl_site": root.parent / "ytdl_site",
        "face": root.parent / "face",
    }


def benchmark_tasks_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "benchmark_tasks.json"


def generate_benchmark_tasks(
    repo_roots: dict[str, Path] | None = None,
    *,
    tasks_per_category: int = DEFAULT_TASKS_PER_CATEGORY,
) -> list[dict[str, Any]]:
    roots = repo_roots or default_repo_roots()
    tasks: list[BenchmarkTask] = []
    for repository in REPOSITORIES:
        files = _repository_files(roots.get(repository))
        for category in TASK_CATEGORIES:
            for index in range(1, max(1, int(tasks_per_category)) + 1):
                focus = _focus_files(files, category, index)
                task_id = f"{_slug(repository)}-{category}-{index:02d}"
                tasks.append(
                    BenchmarkTask(
                        task_id=task_id,
                        category=category,
                        repository=repository,
                        description=_description(repository, category, index, focus),
                        expected_output_type=EXPECTED_OUTPUT_TYPES[category],
                        focus_files=tuple(focus),
                    )
                )
    return [task.to_dict() for task in tasks]


def write_benchmark_tasks(
    state_dir: str | Path,
    repo_roots: dict[str, Path] | None = None,
    *,
    tasks_per_category: int = DEFAULT_TASKS_PER_CATEGORY,
) -> Path:
    path = benchmark_tasks_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tasks = generate_benchmark_tasks(repo_roots, tasks_per_category=tasks_per_category)
    path.write_text(json.dumps(tasks, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_benchmark_tasks(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"benchmark task file must contain a list: {source}")
    return [_normalize_task(row) for row in data if isinstance(row, dict)]


def validate_benchmark_tasks(tasks: Iterable[dict[str, Any]], *, tasks_per_category: int = DEFAULT_TASKS_PER_CATEGORY) -> dict[str, Any]:
    rows = [_normalize_task(row) for row in tasks]
    ids = [row["task_id"] for row in rows]
    counts: dict[str, int] = {}
    missing_fields: list[str] = []
    for row in rows:
        counts[f"{row['repository']}|{row['category']}"] = counts.get(f"{row['repository']}|{row['category']}", 0) + 1
        for field in ("task_id", "category", "repository", "description", "expected_output_type"):
            if not row.get(field):
                missing_fields.append(f"{row.get('task_id', '<missing>')}:{field}")
    missing_cells = [
        {"repository": repository, "category": category, "count": counts.get(f"{repository}|{category}", 0)}
        for repository in REPOSITORIES
        for category in TASK_CATEGORIES
        if counts.get(f"{repository}|{category}", 0) < tasks_per_category
    ]
    return {
        "task_count": len(rows),
        "expected_minimum_tasks": len(REPOSITORIES) * len(TASK_CATEGORIES) * tasks_per_category,
        "duplicate_task_ids": sorted({task_id for task_id in ids if ids.count(task_id) > 1}),
        "missing_required_fields": missing_fields,
        "missing_cells": missing_cells,
        "balanced": not missing_cells and len(set(ids)) == len(ids) and not missing_fields,
    }


def _normalize_task(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    if "expected output type" in normalized and "expected_output_type" not in normalized:
        normalized["expected_output_type"] = normalized["expected output type"]
    return normalized


def _repository_files(root: Path | None) -> list[str]:
    if root is None or not root.exists():
        return []
    rows: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in RELEVANT_SUFFIXES:
            continue
        parts = {part.lower() for part in path.parts}
        if parts & {".git", "__pycache__", ".pytest_cache", "node_modules", "dist", "build"}:
            continue
        try:
            rows.append(path.relative_to(root).as_posix())
        except ValueError:
            rows.append(path.as_posix())
    return sorted(rows)[:600]


def _focus_files(files: list[str], category: str, index: int) -> list[str]:
    if not files:
        return []
    preferred = {
        "testing": ("test", "spec", "fixture"),
        "documentation": ("readme", "docs", ".md"),
        "architecture": ("router", "provider", "architecture", "config"),
        "analysis": ("research", "metrics", "analysis", "report"),
        "bug_fix": ("error", "validator", "runtime", "provider"),
        "refactor": ("service", "runner", "router", "manager"),
        "code_generation": ("api", "sdk", "tools", "workflow"),
    }[category]
    ranked = [path for path in files if any(marker in path.lower() for marker in preferred)] or files
    start = (index - 1) % len(ranked)
    return [ranked[(start + offset) % len(ranked)] for offset in range(min(3, len(ranked)))]


def _description(repository: str, category: str, index: int, focus_files: list[str]) -> str:
    focus = ", ".join(focus_files) if focus_files else "the repository context provided to the runner"
    templates = {
        "bug_fix": "Find a plausible defect or fragile edge case in {repo} around {focus}; propose the smallest safe fix and validation.",
        "code_generation": "Design and sketch a small repository-native implementation for {repo} using {focus} as integration context.",
        "refactor": "Identify a behavior-preserving refactor in {repo} around {focus}; explain invariants and migration risk.",
        "testing": "Create a focused test plan for {repo} around {focus}; include cases, assertions, and the command to run.",
        "analysis": "Analyze the behavior, data flow, or operational risk in {repo} using {focus} as evidence.",
        "architecture": "Write a concise architecture decision record for an improvement in {repo} grounded in {focus}.",
        "documentation": "Draft a documentation update for {repo} that accurately explains the workflow or API visible in {focus}.",
    }
    return templates[category].format(repo=repository, focus=focus) + f" Task variant {index}."


def _slug(value: str) -> str:
    return value.lower().replace("_", "-").replace(" ", "-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate balanced Agent-Hub research benchmark tasks.")
    parser.add_argument("--state-dir", default=".agent-hub/state")
    parser.add_argument("--tasks-per-category", type=int, default=DEFAULT_TASKS_PER_CATEGORY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    path = write_benchmark_tasks(args.state_dir, tasks_per_category=args.tasks_per_category)
    audit = validate_benchmark_tasks(load_benchmark_tasks(path), tasks_per_category=args.tasks_per_category)
    if args.json:
        print(json.dumps({"path": str(path), "audit": audit}, indent=2, sort_keys=True))
    else:
        print(f"benchmark_tasks: {path}")
        print(f"balanced: {audit['balanced']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BenchmarkTask",
    "EXPECTED_OUTPUT_TYPES",
    "REPOSITORIES",
    "TASK_CATEGORIES",
    "benchmark_tasks_path",
    "default_repo_roots",
    "generate_benchmark_tasks",
    "load_benchmark_tasks",
    "validate_benchmark_tasks",
    "write_benchmark_tasks",
]
