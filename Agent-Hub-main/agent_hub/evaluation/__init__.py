from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import HubRequest


SCORE_FILE = "provider_scores.json"
BENCHMARK_TYPES = (
    "coding",
    "reasoning",
    "summarization",
    "tool_calling",
    "long_context",
    "latency",
)


@dataclass(slots=True)
class BenchmarkTask:
    type: str
    prompt: str
    expected_keywords: list[str] = field(default_factory=list)
    route: str = "cloud-agent"
    needs_tools: bool = False


@dataclass(slots=True)
class BenchmarkResult:
    agent: str
    provider: str
    model: str
    task_type: str
    score: float
    latency_ms: float
    ok: bool
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "provider": self.provider,
            "model": self.model,
            "task_type": self.task_type,
            "score": self.score,
            "latency_ms": self.latency_ms,
            "ok": self.ok,
            "error": self.error,
        }


class ProviderScoreStore:
    def __init__(self, state_dir: str | Path) -> None:
        self.path = Path(state_dir) / SCORE_FILE

    def load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        scores = raw.get("providers") if isinstance(raw, dict) else None
        return dict(scores) if isinstance(scores, dict) else {}

    def save_results(self, results: list[BenchmarkResult]) -> dict[str, dict[str, Any]]:
        existing = self.load()
        grouped: dict[str, list[BenchmarkResult]] = {}
        for result in results:
            grouped.setdefault(result.agent, []).append(result)
        now = time.time()
        for agent, rows in grouped.items():
            current = existing.get(agent, {})
            task_scores = dict(current.get("task_scores") or {})
            task_sample_counts = _int_mapping(current.get("task_sample_counts"))
            latency_count = int(current.get("latency_sample_count", 0) or 0)
            average_latency = float(current.get("average_latency_ms", 0) or 0)
            successes = int(current.get("successes", 0) or 0)
            failures = int(current.get("failures", 0) or 0)
            for row in rows:
                task_type = row.task_type or "general"
                previous_count = max(0, int(task_sample_counts.get(task_type, 0)))
                previous_score = float(task_scores.get(task_type, 0.0) or 0.0)
                task_scores[task_type] = round(
                    ((previous_score * previous_count) + float(row.score)) / (previous_count + 1),
                    4,
                )
                task_sample_counts[task_type] = previous_count + 1
                if row.latency_ms:
                    average_latency = (
                        (average_latency * latency_count) + float(row.latency_ms)
                    ) / (latency_count + 1)
                    latency_count += 1
                if row.ok:
                    successes += 1
                else:
                    failures += 1
            total_samples = sum(max(0, int(value)) for value in task_sample_counts.values())
            if total_samples:
                overall = sum(
                    float(task_scores.get(task_type, 0.0) or 0.0) * max(0, int(count))
                    for task_type, count in task_sample_counts.items()
                ) / total_samples
            else:
                overall = sum(float(value) for value in task_scores.values()) / max(1, len(task_scores))
            existing[agent] = {
                **current,
                "agent": agent,
                "provider": rows[-1].provider,
                "model": rows[-1].model,
                "overall_score": round(max(0.0, min(1.0, overall)), 4),
                "task_scores": task_scores,
                "task_sample_counts": task_sample_counts,
                "average_latency_ms": round(average_latency, 2) if latency_count else 0,
                "latency_sample_count": latency_count,
                "sample_count": int(current.get("sample_count", 0)) + len(rows),
                "successes": successes,
                "failures": failures,
                "last_evaluated_at": now,
            }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"version": 1, "updated_at": now, "providers": existing}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return existing

    def record_outcome(
        self,
        *,
        agent: str,
        provider: str,
        model: str,
        task_type: str,
        score: float,
        latency_ms: float,
        ok: bool,
    ) -> dict[str, dict[str, Any]]:
        return self.save_results(
            [
                BenchmarkResult(
                    agent=agent,
                    provider=provider,
                    model=model,
                    task_type=task_type or "general",
                    score=round(max(0.0, min(1.0, float(score or 0.0))), 4),
                    latency_ms=round(max(0.0, float(latency_ms or 0.0)), 2),
                    ok=bool(ok),
                )
            ]
        )


class BenchmarkRunner:
    def __init__(self, router: Any, *, store: ProviderScoreStore | None = None) -> None:
        self.router = router
        self.store = store or ProviderScoreStore(router.config.state_dir)

    def run(self, tasks: list[BenchmarkTask] | None = None) -> list[BenchmarkResult]:
        tasks = tasks or default_benchmark_tasks()
        results: list[BenchmarkResult] = []
        for task in tasks:
            started = time.perf_counter()
            try:
                response = self.router.route(
                    HubRequest(
                        session_id=f"eval-{uuid.uuid4().hex}",
                        route=task.route,
                        messages=[{"role": "user", "content": task.prompt}],
                        max_tokens=256,
                        record_session=False,
                        raw={"agent_hub": {"benchmark_task_type": task.type}},
                    )
                )
                latency_ms = (time.perf_counter() - started) * 1000
                score = _score_text(response.text, task)
                results.append(
                    BenchmarkResult(
                        agent=response.agent,
                        provider=response.provider,
                        model=response.model,
                        task_type=task.type,
                        score=score,
                        latency_ms=round(latency_ms, 2),
                        ok=True,
                    )
                )
            except Exception as exc:
                latency_ms = (time.perf_counter() - started) * 1000
                results.append(
                    BenchmarkResult(
                        agent="",
                        provider="",
                        model="",
                        task_type=task.type,
                        score=0.0,
                        latency_ms=round(latency_ms, 2),
                        ok=False,
                        error=str(exc),
                    )
                )
        self.store.save_results([result for result in results if result.agent])
        return results


def default_benchmark_tasks(route: str = "cloud-agent") -> list[BenchmarkTask]:
    return [
        BenchmarkTask("coding", "Write a concise plan to fix a failing Python unit test.", ["test", "fix"], route),
        BenchmarkTask("coding", "Implement input validation for a JSON API handler.", ["validate", "error"], route),
        BenchmarkTask("coding", "Describe a safe multi-file refactor for duplicated parsing logic.", ["refactor", "test"], route),
        BenchmarkTask("coding", "Generate a minimal unit test for a function that adds two integers.", ["test", "assert"], route),
        BenchmarkTask("reasoning", "Explain why a fallback router should track provider health.", ["health", "fallback"], route),
        BenchmarkTask("reasoning", "Compare success-rate routing with prompt-only routing.", ["success", "routing"], route),
        BenchmarkTask("reasoning", "Explain when a cheap model should escalate to a stronger model.", ["confidence", "escalate"], route),
        BenchmarkTask("reasoning", "List risks of trusting approval flags from request JSON.", ["approval", "trust"], route),
        BenchmarkTask("summarization", "Summarize: Agent Hub routes requests across local and cloud models.", ["route"], route),
        BenchmarkTask("summarization", "Summarize why secrets should be redacted before provider calls.", ["secret", "provider"], route),
        BenchmarkTask("summarization", "Summarize the generate, verify, repair loop in one sentence.", ["verify", "repair"], route),
        BenchmarkTask("summarization", "Summarize the purpose of repository-specific routing memory.", ["repository", "routing"], route),
        BenchmarkTask("tool_calling", "Say which tool would read README.md from a workspace.", ["file_read", "read"], route, True),
        BenchmarkTask("tool_calling", "Say which tool should search a repository for TODO markers.", ["search", "repo"], route, True),
        BenchmarkTask("tool_calling", "Explain which validation command should run after Python edits.", ["test", "python"], route, True),
        BenchmarkTask("tool_calling", "Describe why shell execution needs explicit approval.", ["shell", "approval"], route, True),
        BenchmarkTask("long_context", "Identify the main point after reading a long repeated context. " + ("context " * 200), ["context"], route),
        BenchmarkTask("long_context", "Find the routing requirement in this repeated specification. " + ("routing memory " * 180), ["routing", "memory"], route),
        BenchmarkTask("long_context", "Extract the security requirement from this repeated text. " + ("never send secrets " * 180), ["secret"], route),
        BenchmarkTask("long_context", "State the requested workflow from this repeated text. " + ("generate verify repair " * 180), ["verify", "repair"], route),
        BenchmarkTask("latency", "Reply with the word ok.", ["ok"], route),
        BenchmarkTask("latency", "Reply with the word ready.", ["ready"], route),
        BenchmarkTask("latency", "Reply with the word pass.", ["pass"], route),
        BenchmarkTask("latency", "Reply with the word routed.", ["routed"], route),
    ]


def _score_text(text: str, task: BenchmarkTask) -> float:
    lowered = text.lower()
    if not text.strip():
        return 0.0
    keyword_score = 0.0
    if task.expected_keywords:
        keyword_score = sum(1 for word in task.expected_keywords if word.lower() in lowered) / len(task.expected_keywords)
    length_score = 1.0 if 2 <= len(text.split()) <= 500 else 0.5
    return round(max(0.0, min(1.0, (keyword_score * 0.7) + (length_score * 0.3))), 4)


__all__ = [
    "BENCHMARK_TYPES",
    "BenchmarkResult",
    "BenchmarkRunner",
    "BenchmarkTask",
    "ProviderScoreStore",
    "default_benchmark_tasks",
]


def _int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        try:
            result[key] = max(0, int(item))
        except (TypeError, ValueError):
            continue
    return result
