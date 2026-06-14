from __future__ import annotations

import time
from typing import Any, Protocol

from .task_suite import BenchmarkTask


class BenchmarkProvider(Protocol):
    def complete(self, prompt: str, *, task: BenchmarkTask) -> dict[str, Any]:
        ...


def run_provider_task(provider: BenchmarkProvider | Any, task: BenchmarkTask, *, model: str = "") -> dict[str, Any]:
    started = time.perf_counter()
    if hasattr(provider, "complete"):
        result = provider.complete(task.prompt, task=task)
    elif callable(provider):
        result = provider(task)
    else:
        result = {"text": "", "usage": {}}
    elapsed = time.perf_counter() - started
    usage = result.get("usage", {}) if isinstance(result, dict) else {}
    text = str(result.get("text") or result.get("content") or "") if isinstance(result, dict) else str(result)
    prompt_tokens = _int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion_tokens = _int(usage.get("completion_tokens") or usage.get("output_tokens"))
    total_tokens = _int(usage.get("total_tokens")) or prompt_tokens + completion_tokens or _estimate_tokens(task.prompt + text)
    return {
        "task": task.task,
        "model": model or str(result.get("model") or "") if isinstance(result, dict) else model,
        "tokens": total_tokens,
        "input_tokens": prompt_tokens or _estimate_tokens(task.prompt),
        "output_tokens": completion_tokens or _estimate_tokens(text),
        "latency_seconds": round(elapsed, 4),
        "tests_passed": _tests_passed(text, task),
        "text": text[:1000],
    }


def _tests_passed(text: str, task: BenchmarkTask) -> bool:
    lowered = text.lower()
    if not task.expected_keywords:
        return bool(text.strip())
    return all(keyword.lower() in lowered for keyword in task.expected_keywords[:5])


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
