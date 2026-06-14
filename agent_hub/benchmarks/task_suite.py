from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BENCHMARK_CATEGORIES = [
    "bug_fix",
    "feature_request",
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
        return public_150_suite()
    source = Path(path)
    if not source.exists():
        return public_150_suite()
    rows: list[BenchmarkTask] = []
    lines = source.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if not line.strip():
            continue
        data = json.loads(line)
        rows.append(task_from_dict(data))
    return rows or public_150_suite()


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
        "feature": "feature_request",
        "features": "feature_request",
        "feature_requests": "feature_request",
        "refactoring": "refactor",
        "tests": "test_generation",
        "docs": "documentation",
        "upgrade": "dependency_upgrade",
    }
    return aliases.get(text, text if text in BENCHMARK_CATEGORIES else "feature_implementation")


def public_150_suite() -> list[BenchmarkTask]:
    tasks: list[BenchmarkTask] = []
    for index in range(1, 51):
        domain = _domain(index)
        tasks.append(
            BenchmarkTask(
                task="bug_fix",
                prompt=(
                    f"Bug fix #{index}: repair a failing {domain} path, add or update the "
                    "smallest regression test, and explain the root cause."
                ),
                tests=[f"tests/test_{domain}_{index:02d}.py"],
                expected_keywords=["fix", "test", "root"],
                metadata={"public_suite": "agent-hub-public-150", "difficulty": _difficulty(index)},
            )
        )
        tasks.append(
            BenchmarkTask(
                task="refactor",
                prompt=(
                    f"Refactor #{index}: simplify duplicated {domain} logic without changing "
                    "public behavior, keeping tests green and naming clearer."
                ),
                tests=[f"tests/test_{domain}_{index:02d}.py"],
                expected_keywords=["refactor", "test", "behavior"],
                metadata={"public_suite": "agent-hub-public-150", "difficulty": _difficulty(index)},
            )
        )
        tasks.append(
            BenchmarkTask(
                task="feature_request",
                prompt=(
                    f"Feature request #{index}: implement a small {domain} capability with "
                    "validation, documentation notes, and focused tests."
                ),
                tests=[f"tests/test_{domain}_{index:02d}.py"],
                expected_keywords=["implement", "validation", "test"],
                metadata={"public_suite": "agent-hub-public-150", "difficulty": _difficulty(index)},
            )
        )
    return tasks


def write_public_150_suite(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(task.to_dict(), separators=(",", ":")) for task in public_150_suite()]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


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


def _domain(index: int) -> str:
    domains = [
        "auth",
        "billing",
        "routing",
        "cache",
        "search",
        "notifications",
        "permissions",
        "imports",
        "exports",
        "settings",
    ]
    return domains[(index - 1) % len(domains)]


def _difficulty(index: int) -> str:
    if index % 5 == 0:
        return "hard"
    if index % 2 == 0:
        return "medium"
    return "easy"
