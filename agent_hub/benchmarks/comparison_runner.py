from __future__ import annotations

from typing import Any

from .baseline_runner import run_baseline
from .provider_runner import run_provider_task
from .report_builder import build_report
from .task_suite import BenchmarkTask, load_task_suite


def compare_task(
    task: BenchmarkTask,
    *,
    baseline_provider: Any,
    hub_provider: Any,
    baseline_model: str = "claude",
    hub_model: str = "agent-hub",
) -> dict[str, Any]:
    baseline = run_baseline(baseline_provider, task, baseline_model=baseline_model)
    hub = run_provider_task(hub_provider, task, model=hub_model)
    baseline_tokens = int(baseline["baseline_tokens"])
    hub_tokens = int(hub["tokens"])
    savings = 0.0 if baseline_tokens <= 0 else ((baseline_tokens - hub_tokens) / baseline_tokens) * 100.0
    return {
        "task": task.task,
        "baseline_model": baseline_model,
        "baseline_tokens": baseline_tokens,
        "hub_tokens": hub_tokens,
        "savings": round(savings, 1),
        "tests_passed": bool(hub["tests_passed"]),
        "baseline_tests_passed": bool(baseline["tests_passed"]),
        "latency_seconds": hub["latency_seconds"],
        "baseline_latency_seconds": baseline["latency_seconds"],
    }


def run_comparison(
    *,
    baseline_provider: Any,
    hub_provider: Any,
    suite_path: str | None = None,
    baseline_model: str = "claude",
    hub_model: str = "agent-hub",
    limit: int | None = None,
) -> dict[str, Any]:
    tasks = load_task_suite(suite_path)
    if limit:
        tasks = tasks[: max(1, int(limit))]
    rows = [
        compare_task(
            task,
            baseline_provider=baseline_provider,
            hub_provider=hub_provider,
            baseline_model=baseline_model,
            hub_model=hub_model,
        )
        for task in tasks
    ]
    return build_report(rows, baseline_model=baseline_model, hub_model=hub_model)
