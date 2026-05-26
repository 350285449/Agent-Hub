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
            latencies = []
            for row in rows:
                task_scores[row.task_type] = row.score
                if row.latency_ms:
                    latencies.append(row.latency_ms)
            overall = sum(float(value) for value in task_scores.values()) / max(1, len(task_scores))
            existing[agent] = {
                **current,
                "agent": agent,
                "provider": rows[-1].provider,
                "model": rows[-1].model,
                "overall_score": round(max(0.0, min(1.0, overall)), 4),
                "task_scores": task_scores,
                "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else current.get("average_latency_ms", 0),
                "sample_count": int(current.get("sample_count", 0)) + len(rows),
                "last_evaluated_at": now,
            }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"version": 1, "updated_at": now, "providers": existing}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return existing


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
        BenchmarkTask("reasoning", "Explain why a fallback router should track provider health.", ["health", "fallback"], route),
        BenchmarkTask("summarization", "Summarize: Agent Hub routes requests across local and cloud models.", ["route"], route),
        BenchmarkTask("tool_calling", "Say which tool would read README.md from a workspace.", ["file_read", "read"], route, True),
        BenchmarkTask("long_context", "Identify the main point after reading a long repeated context. " + ("context " * 200), ["context"], route),
        BenchmarkTask("latency", "Reply with the word ok.", ["ok"], route),
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
