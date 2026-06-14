from __future__ import annotations

from typing import Any

from .provider_runner import run_provider_task
from .task_suite import BenchmarkTask


def run_baseline(provider: Any, task: BenchmarkTask, *, baseline_model: str = "claude") -> dict[str, Any]:
    result = run_provider_task(provider, task, model=baseline_model)
    result["baseline_model"] = baseline_model
    result["baseline_tokens"] = result["tokens"]
    return result
