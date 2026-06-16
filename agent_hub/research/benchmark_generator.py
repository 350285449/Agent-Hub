from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .task_generator import (
    DEFAULT_TASKS_PER_CATEGORY,
    benchmark_tasks_path,
    default_repo_roots,
    load_benchmark_tasks,
    validate_benchmark_tasks,
    write_benchmark_tasks,
)


def generate_research_benchmark(
    state_dir: str | Path,
    *,
    repo_roots: dict[str, Path] | None = None,
    tasks_per_category: int = DEFAULT_TASKS_PER_CATEGORY,
) -> dict[str, Any]:
    path = write_benchmark_tasks(
        state_dir,
        repo_roots or default_repo_roots(),
        tasks_per_category=tasks_per_category,
    )
    tasks = load_benchmark_tasks(path)
    audit = validate_benchmark_tasks(tasks, tasks_per_category=tasks_per_category)
    return {"benchmark_tasks": str(path), "audit": audit}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the balanced Agent-Hub benchmark task set.")
    parser.add_argument("--state-dir", default=".agent-hub/state")
    parser.add_argument("--tasks-per-category", type=int, default=DEFAULT_TASKS_PER_CATEGORY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = generate_research_benchmark(args.state_dir, tasks_per_category=args.tasks_per_category)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"benchmark_tasks: {result['benchmark_tasks']}")
        print(f"balanced: {result['audit']['balanced']}")
        print(f"path: {benchmark_tasks_path(args.state_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["generate_research_benchmark"]
