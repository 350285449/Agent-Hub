from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BENCHMARK_CATEGORIES = [
    "bug_fix",
    "feature_implementation",
    "refactor",
    "test_generation",
    "documentation",
    "dependency_upgrade",
]


@dataclass(frozen=True, slots=True)
class BenchmarkTask:
    task: str
    prompt: str
    tests: list[str] = field(default_factory=list)
    expected_keywords: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "prompt": self.prompt,
            "tests": list(self.tests),
            "expected_keywords": list(self.expected_keywords),
            "metadata": dict(self.metadata),
        }


def load_task_suite(path: str | Path | None = None) -> list[BenchmarkTask]:
    if path is None:
        return _default_suite()
    source = Path(path)
    if not source.exists():
        return _default_suite()
    rows: list[BenchmarkTask] = []
    lines = source.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if not line.strip():
            continue
        data = json.loads(line)
        rows.append(task_from_dict(data))
    return rows or _default_suite()


def task_from_dict(data: dict[str, Any]) -> BenchmarkTask:
    task = str(data.get("task") or data.get("type") or data.get("category") or "feature_implementation")
    if task not in BENCHMARK_CATEGORIES:
        task = _normalize_category(task)
    return BenchmarkTask(
        task=task,
        prompt=str(data.get("prompt") or data.get("description") or ""),
        tests=[str(item) for item in data.get("tests", []) if isinstance(item, str)],
        expected_keywords=[str(item) for item in data.get("expected_keywords", []) if isinstance(item, str)],
        metadata={key: value for key, value in data.items() if key not in {"task", "type", "category", "prompt", "description", "tests", "expected_keywords"}},
    )


def _normalize_category(value: str) -> str:
    text = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "debugging": "bug_fix",
        "coding": "feature_implementation",
        "refactoring": "refactor",
        "tests": "test_generation",
        "docs": "documentation",
        "upgrade": "dependency_upgrade",
    }
    return aliases.get(text, text if text in BENCHMARK_CATEGORIES else "feature_implementation")


def _default_suite() -> list[BenchmarkTask]:
    prompts = {
        "bug_fix": "Fix a failing request handler and preserve the regression test.",
        "feature_implementation": "Implement a small service-layer feature with validation and tests.",
        "refactor": "Refactor duplicated logic without changing public behavior.",
        "test_generation": "Add missing tests for an edge case in the repository.",
        "documentation": "Update developer documentation for a changed workflow.",
        "dependency_upgrade": "Upgrade a dependency and adjust compatibility code.",
    }
    return [
        BenchmarkTask(task=category, prompt=prompt, expected_keywords=category.split("_"))
        for category, prompt in prompts.items()
    ]
