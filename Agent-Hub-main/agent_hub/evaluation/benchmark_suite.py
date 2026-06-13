from __future__ import annotations

import json
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..adaptive import estimate_known_cost_usd
from ..config import HubConfig
from ..core.router import AgentRouter
from ..models import HubRequest
from . import BenchmarkTask, default_benchmark_tasks, _score_text


REPORT_DIR = "benchmark_reports"


class BenchmarkSuiteRunner:
    """Compare static routing with adaptive routing using the existing router."""

    def __init__(self, config: HubConfig, *, provider_factory: Any | None = None) -> None:
        self.config = config
        self.provider_factory = provider_factory

    def run(
        self,
        *,
        route: str = "cloud-agent",
        limit: int = 20,
        tasks: list[BenchmarkTask] | None = None,
    ) -> dict[str, Any]:
        selected_tasks = (tasks or default_benchmark_tasks(route=route))[: max(1, min(limit, 50))]
        static_router = self._router(
            replace(
                self.config,
                adaptive_learning_enabled=False,
                adaptive_routing_enabled=False,
                adaptive_workflow_upgrades_enabled=False,
                routing_memory_enabled=False,
                expose_routing_details=True,
            )
        )
        adaptive_router = self._router(
            replace(
                self.config,
                adaptive_learning_enabled=True,
                adaptive_routing_enabled=True,
                adaptive_workflow_upgrades_enabled=True,
                routing_memory_enabled=True,
                expose_routing_details=True,
            )
        )
        static_results = _run_strategy(static_router, selected_tasks, strategy="static", route=route)
        adaptive_results = _run_strategy(adaptive_router, selected_tasks, strategy="adaptive", route=route)
        report_path = _report_path(self.config.state_dir)
        report = {
            "object": "agent_hub.benchmark_suite",
            "created_at": time.time(),
            "route": route,
            "tasks": [task.type for task in selected_tasks],
            "static_routing": _strategy_summary(static_results),
            "adaptive_routing": _strategy_summary(adaptive_results),
            "comparison": _comparison(static_results, adaptive_results),
            "results": {
                "static": static_results,
                "adaptive": adaptive_results,
            },
            "workflow_effectiveness": {
                "static": _workflow_effectiveness(static_router),
                "adaptive": _workflow_effectiveness(adaptive_router),
            },
            "report_path": str(report_path),
        }
        _write_report(report_path, report)
        return report

    def _router(self, config: HubConfig) -> AgentRouter:
        if self.provider_factory is None:
            return AgentRouter(config)
        return AgentRouter(config, provider_factory=self.provider_factory)


def _run_strategy(
    router: AgentRouter,
    tasks: list[BenchmarkTask],
    *,
    strategy: str,
    route: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        request = HubRequest(
            session_id=f"benchmark-suite-{strategy}-{uuid.uuid4().hex}",
            route=route or task.route,
            messages=[{"role": "user", "content": task.prompt}],
            max_tokens=256,
            record_session=False,
            raw={"agent_hub": {"benchmark_task_type": task.type, "benchmark_strategy": strategy}},
        )
        started = time.perf_counter()
        try:
            response = router.route(request)
            latency_ms = (time.perf_counter() - started) * 1000
            agent = router.config.agents.get(response.agent)
            input_tokens = _usage_int(response.usage, "prompt_tokens", "input_tokens")
            output_tokens = _usage_int(response.usage, "completion_tokens", "output_tokens")
            rows.append(
                {
                    "strategy": strategy,
                    "task_type": task.type,
                    "agent": response.agent,
                    "provider": response.provider,
                    "model": response.model,
                    "ok": bool(response.text.strip()),
                    "score": _score_text(response.text, task),
                    "latency_ms": round(latency_ms, 2),
                    "failover_count": len(response.failover),
                    "estimated_cost_usd": estimate_known_cost_usd(
                        agent,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    if agent is not None
                    else None,
                    "usage": dict(response.usage),
                    "routing_explanation": _response_explanation(response),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "strategy": strategy,
                    "task_type": task.type,
                    "agent": "",
                    "provider": "",
                    "model": "",
                    "ok": False,
                    "score": 0.0,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "failover_count": 0,
                    "estimated_cost_usd": None,
                    "error": str(exc),
                }
            )
    return rows


def _strategy_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    successes = sum(1 for row in rows if row.get("ok"))
    costs = [_safe_float(row.get("estimated_cost_usd")) for row in rows if row.get("estimated_cost_usd") is not None]
    latencies = [_safe_float(row.get("latency_ms")) for row in rows]
    return {
        "task_count": total,
        "successes": successes,
        "success_rate": round(successes / max(1, total), 4),
        "average_score": round(sum(_safe_float(row.get("score")) for row in rows) / max(1, total), 4),
        "average_latency_ms": round(sum(latencies) / max(1, len(latencies)), 2) if latencies else 0.0,
        "failover_frequency": round(
            sum(1 for row in rows if int(row.get("failover_count") or 0) > 0) / max(1, total),
            4,
        ),
        "average_failovers": round(
            sum(int(row.get("failover_count") or 0) for row in rows) / max(1, total),
            4,
        ),
        "average_cost_usd": round(sum(costs) / len(costs), 8) if costs else None,
    }


def _comparison(static_rows: list[dict[str, Any]], adaptive_rows: list[dict[str, Any]]) -> dict[str, Any]:
    static = _strategy_summary(static_rows)
    adaptive = _strategy_summary(adaptive_rows)
    cost_delta = _delta(adaptive.get("average_cost_usd"), static.get("average_cost_usd"))
    return {
        "success_rate_delta": round(
            _safe_float(adaptive.get("success_rate")) - _safe_float(static.get("success_rate")),
            4,
        ),
        "average_score_delta": round(
            _safe_float(adaptive.get("average_score")) - _safe_float(static.get("average_score")),
            4,
        ),
        "latency_delta_ms": round(
            _safe_float(adaptive.get("average_latency_ms")) - _safe_float(static.get("average_latency_ms")),
            2,
        ),
        "failover_frequency_delta": round(
            _safe_float(adaptive.get("failover_frequency")) - _safe_float(static.get("failover_frequency")),
            4,
        ),
        "average_cost_delta_usd": cost_delta,
        "cost_savings_usd": round(max(0.0, -(cost_delta or 0.0)), 8) if cost_delta is not None else None,
        "winner": _winner(static, adaptive),
    }


def _workflow_effectiveness(router: AgentRouter) -> dict[str, Any]:
    try:
        summary = router.adaptive_learning.optimization_summary()
    except Exception:
        return {}
    return {
        "workflow_success_rate": summary.get("workflow_success_rate", {}),
        "workflow_patterns": summary.get("workflow_patterns", []),
        "workflow_analytics": summary.get("workflow_analytics", []),
    }


def _response_explanation(response: Any) -> dict[str, Any]:
    raw = response.raw if isinstance(getattr(response, "raw", None), dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    decision = hub.get("routing_decision") if isinstance(hub.get("routing_decision"), dict) else {}
    explanation = decision.get("explanation") if isinstance(decision.get("explanation"), dict) else {}
    return {
        "summary": explanation.get("summary", ""),
        "selected": explanation.get("selected", {}),
        "rejected": explanation.get("rejected", [])[:5],
    }


def _report_path(state_dir: str | Path) -> Path:
    directory = Path(state_dir) / REPORT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"benchmark-suite-{int(time.time())}.json"


def _write_report(path: Path, report: dict[str, Any]) -> Path:
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _winner(static: dict[str, Any], adaptive: dict[str, Any]) -> str:
    static_score = (
        _safe_float(static.get("success_rate")) * 0.5
        + _safe_float(static.get("average_score")) * 0.35
        - _safe_float(static.get("failover_frequency")) * 0.1
        - min(0.05, _safe_float(static.get("average_latency_ms")) / 100_000)
    )
    adaptive_score = (
        _safe_float(adaptive.get("success_rate")) * 0.5
        + _safe_float(adaptive.get("average_score")) * 0.35
        - _safe_float(adaptive.get("failover_frequency")) * 0.1
        - min(0.05, _safe_float(adaptive.get("average_latency_ms")) / 100_000)
    )
    if abs(adaptive_score - static_score) < 0.01:
        return "tie"
    return "adaptive" if adaptive_score > static_score else "static"


def _delta(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return round(_safe_float(left) - _safe_float(right), 8)


def _usage_int(usage: dict[str, object], *keys: str) -> int:
    for key in keys:
        try:
            return max(0, int(usage.get(key, 0)))
        except (TypeError, ValueError):
            continue
    return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["BenchmarkSuiteRunner"]
