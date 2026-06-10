from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..adaptive import estimate_known_cost_usd
from ..config import AgentConfig, HubConfig
from ..core.router import AgentRouter
from ..models import HubRequest, HubResponse
from ..token_budget import estimate_messages_tokens
from . import BenchmarkTask, _score_text, default_benchmark_tasks
from .datasets import (
    MAX_BENCHMARK_TASKS,
    benchmark_dataset_fingerprint,
    load_benchmark_corpus as _load_benchmark_corpus,
    resolve_benchmark_dataset,
    resolve_corpus_path,
    state_path,
)


DEFAULT_REPORT_DIR = "benchmark_reports"


@dataclass(frozen=True, slots=True)
class BenchmarkReportPaths:
    json: Path
    markdown: Path


class BenchmarkProofRunner:
    """Compare a user's baseline model with Agent-Hub routing on the same corpus."""

    def __init__(self, config: HubConfig, *, provider_factory: Any | None = None) -> None:
        self.config = config
        self.provider_factory = provider_factory

    def run(
        self,
        *,
        route: str = "cloud-agent",
        baseline: str = "",
        limit: int = 0,
        dataset: str = "",
        corpus_dir: str | Path | None = None,
        output_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        baseline_agent = _resolve_baseline_agent(self.config, baseline)
        resolved_dataset = resolve_benchmark_dataset(
            self.config,
            dataset=dataset,
            route=route,
            limit=limit,
            corpus_dir=corpus_dir,
        )
        task_limit = len(resolved_dataset.tasks) if dataset else max(1, min(MAX_BENCHMARK_TASKS, int(limit or 50)))
        tasks = list(resolved_dataset.tasks)[:task_limit]
        if not tasks:
            tasks = default_benchmark_tasks(route=route)[: max(1, min(MAX_BENCHMARK_TASKS, int(limit or 50)))]
        dataset_info = resolved_dataset.to_dict()
        dataset_info.update(
            {
                "task_count": len(tasks),
                "fingerprint": benchmark_dataset_fingerprint(tasks),
            }
        )
        baseline_router = self._router(only_agent=baseline_agent.name)
        routed_router = self._router()
        pairs = [
            _run_task_pair(
                task,
                baseline_router=baseline_router,
                routed_router=routed_router,
                baseline_agent=baseline_agent,
                route=route,
            )
            for task in tasks
        ]
        report = _report(
            route=route,
            baseline_agent=baseline_agent,
            pairs=pairs,
            dataset=dataset_info,
        )
        paths = write_benchmark_report(
            report,
            output_dir=output_dir or state_path(self.config, DEFAULT_REPORT_DIR),
        )
        report["report_paths"] = {"json": str(paths.json), "markdown": str(paths.markdown)}
        return report

    def _router(self, *, only_agent: str = "") -> AgentRouter:
        config = replace(self.config, repo_context_enabled=False, repository_dna_enabled=False)
        if only_agent:
            config = replace(
                config,
                default_route=[only_agent],
                routes=[replace(route, agents=[only_agent]) for route in config.routes],
            )
        if self.provider_factory is None:
            return AgentRouter(config)
        return AgentRouter(config, provider_factory=self.provider_factory)


def load_benchmark_corpus(path: str | Path, *, route: str, limit: int = 50) -> list[BenchmarkTask]:
    return _load_benchmark_corpus(path, route=route, limit=limit)


def write_benchmark_report(report: dict[str, Any], *, output_dir: str | Path) -> BenchmarkReportPaths:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "benchmark-report.json"
    markdown_path = directory / "benchmark-report.md"
    report["report_paths"] = {"json": str(json_path), "markdown": str(markdown_path)}
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    return BenchmarkReportPaths(json=json_path, markdown=markdown_path)


def _run_task_pair(
    task: BenchmarkTask,
    *,
    baseline_router: AgentRouter,
    routed_router: AgentRouter,
    baseline_agent: AgentConfig,
    route: str,
) -> dict[str, Any]:
    task_route = task.route or route
    baseline = _run_one(
        baseline_router,
        task,
        route=task_route,
        preferred_agent=baseline_agent.name,
        strategy="baseline",
    )
    routed = _run_one(
        routed_router,
        task,
        route=task_route,
        preferred_agent="",
        strategy="agent_hub",
    )
    return {
        "task_type": task.type,
        "prompt": task.prompt,
        "expected_keywords": list(task.expected_keywords),
        "route": task_route,
        "needs_tools": bool(task.needs_tools),
        "baseline": baseline,
        "agent_hub": routed,
        "comparison": _pair_comparison(baseline, routed),
    }


def _run_one(
    router: AgentRouter,
    task: BenchmarkTask,
    *,
    route: str,
    preferred_agent: str,
    strategy: str,
) -> dict[str, Any]:
    request = HubRequest(
        session_id=f"benchmark-{strategy}-{uuid.uuid4().hex}",
        route=route or task.route,
        preferred_agent=preferred_agent or None,
        messages=[{"role": "user", "content": task.prompt}],
        max_tokens=256,
        record_session=False,
        raw={
            "needs_tools": bool(task.needs_tools),
            "agent_hub": {
                "benchmark_task_type": task.type,
                "benchmark_strategy": strategy,
                "needs_tools": bool(task.needs_tools),
            }
        },
    )
    started = time.perf_counter()
    try:
        response = router.route(request)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return _response_row(router.config, response, task, latency_ms=latency_ms)
    except Exception as exc:
        return {
            "strategy": strategy,
            "agent": preferred_agent,
            "provider": "",
            "model": "",
            "ok": False,
            "success": False,
            "score": 0.0,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "cost_usd": None,
            "usage": {},
            "failover_count": 0,
            "error": str(exc),
        }


def _response_row(config: HubConfig, response: HubResponse, task: BenchmarkTask, *, latency_ms: float) -> dict[str, Any]:
    agent = config.agents.get(response.agent)
    input_tokens = _usage_int(response.usage, "prompt_tokens", "input_tokens")
    output_tokens = _usage_int(response.usage, "completion_tokens", "output_tokens")
    if input_tokens <= 0:
        input_tokens = estimate_messages_tokens([{"role": "user", "content": task.prompt}])
    if output_tokens <= 0:
        output_tokens = max(1, len(response.text or "") // 4)
    cost = (
        estimate_known_cost_usd(agent, input_tokens=input_tokens, output_tokens=output_tokens)
        if agent is not None
        else None
    )
    score = _score_text(response.text, task)
    return {
        "agent": response.agent,
        "provider": response.provider,
        "model": response.model,
        "ok": bool(response.text.strip()),
        "success": bool(response.text.strip()) and score >= 0.3,
        "score": score,
        "latency_ms": latency_ms,
        "cost_usd": cost,
        "usage": dict(response.usage),
        "failover_count": len(response.failover),
        "routing_explanation": _response_explanation(response),
    }


def _report(
    *,
    route: str,
    baseline_agent: AgentConfig,
    pairs: list[dict[str, Any]],
    dataset: dict[str, Any],
) -> dict[str, Any]:
    baseline_rows = [row["baseline"] for row in pairs]
    routed_rows = [row["agent_hub"] for row in pairs]
    baseline_summary = _summary(baseline_rows)
    routed_summary = _summary(routed_rows)
    comparison = _comparison(baseline_summary, routed_summary)
    return {
        "object": "agent_hub.benchmark_proof",
        "created_at": time.time(),
        "route": route,
        "baseline": {
            "agent": baseline_agent.name,
            "provider": baseline_agent.provider,
            "model": baseline_agent.model,
        },
        "task_count": len(pairs),
        "corpus_dir": str(dataset.get("source") or ""),
        "dataset": dict(dataset),
        "dataset_name": dataset.get("name"),
        "dataset_fingerprint": dataset.get("fingerprint"),
        "public_benchmark_repository": "benchmarks/",
        "baseline_summary": baseline_summary,
        "agent_hub_summary": routed_summary,
        "comparison": comparison,
        "cost_reduction": comparison.get("cost_reduction"),
        "latency_reduction": comparison.get("latency_reduction"),
        "success_delta": comparison.get("success_delta"),
        "results": pairs,
        "verification": {
            "dataset": dataset.get("name"),
            "fingerprint": dataset.get("fingerprint"),
            "rerun_command": (
                f"agent-hub benchmark --dataset {dataset.get('name')} --route {route} "
                f"--baseline {baseline_agent.name} --export results.json"
            ),
            "verify_command": f"agent-hub benchmark verify results.json --dataset {dataset.get('name')}",
        },
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    successes = sum(1 for row in rows if row.get("success"))
    costs = [_float(row.get("cost_usd")) for row in rows if row.get("cost_usd") is not None]
    latencies = [_float(row.get("latency_ms")) for row in rows]
    scores = [_float(row.get("score")) for row in rows]
    return {
        "task_count": total,
        "successes": successes,
        "failures": max(0, total - successes),
        "success_rate": round(successes / max(1, total), 4),
        "average_score": round(sum(scores) / max(1, len(scores)), 4),
        "average_latency_ms": round(sum(latencies) / max(1, len(latencies)), 2) if latencies else 0.0,
        "total_cost_usd": round(sum(costs), 8) if costs else None,
        "average_cost_usd": round(sum(costs) / len(costs), 8) if costs else None,
        "priced_task_count": len(costs),
        "failover_count": sum(int(row.get("failover_count") or 0) for row in rows),
    }


def _comparison(baseline: dict[str, Any], routed: dict[str, Any]) -> dict[str, Any]:
    return {
        "cost_reduction": _percent_reduction(routed.get("total_cost_usd"), baseline.get("total_cost_usd")),
        "latency_reduction": _percent_reduction(routed.get("average_latency_ms"), baseline.get("average_latency_ms")),
        "success_delta": round(
            (_float(routed.get("success_rate")) - _float(baseline.get("success_rate"))) * 100,
            2,
        ),
        "average_score_delta": round(_float(routed.get("average_score")) - _float(baseline.get("average_score")), 4),
        "failure_delta": int(routed.get("failures") or 0) - int(baseline.get("failures") or 0),
        "total_cost_delta_usd": _delta(routed.get("total_cost_usd"), baseline.get("total_cost_usd")),
        "average_latency_delta_ms": _delta(routed.get("average_latency_ms"), baseline.get("average_latency_ms")),
    }


def _pair_comparison(baseline: dict[str, Any], routed: dict[str, Any]) -> dict[str, Any]:
    return {
        "cost_reduction": _percent_reduction(routed.get("cost_usd"), baseline.get("cost_usd")),
        "latency_reduction": _percent_reduction(routed.get("latency_ms"), baseline.get("latency_ms")),
        "success_delta": int(bool(routed.get("success"))) - int(bool(baseline.get("success"))),
        "score_delta": round(_float(routed.get("score")) - _float(baseline.get("score")), 4),
    }


def _resolve_baseline_agent(config: HubConfig, baseline: str) -> AgentConfig:
    requested = str(baseline or "").strip().lower()
    if requested:
        for agent in config.agents.values():
            haystack = " ".join(
                str(value or "").lower()
                for value in (agent.name, agent.provider, agent.provider_type, agent.model)
            )
            if agent.name.lower() == requested or agent.model.lower() == requested or requested in haystack:
                return agent
    for name in config.default_route:
        agent = config.agents.get(name)
        if agent and agent.enabled:
            return agent
    for agent in config.agents.values():
        if agent.enabled:
            return agent
    raise ValueError("No enabled baseline agent is configured.")


def _resolve_corpus_path(config: HubConfig, corpus_dir: str | Path | None) -> Path:
    return resolve_corpus_path(config, corpus_dir)


def _response_explanation(response: HubResponse) -> dict[str, Any]:
    raw = response.raw if isinstance(response.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    decision = hub.get("routing_decision") if isinstance(hub.get("routing_decision"), dict) else {}
    explanation = decision.get("explanation") if isinstance(decision.get("explanation"), dict) else {}
    return {
        "summary": explanation.get("summary", ""),
        "selected": explanation.get("selected", {}),
        "rejected": explanation.get("rejected", [])[:6],
        "cost_savings": explanation.get("cost_savings", {}),
    }


def _markdown_report(report: dict[str, Any]) -> str:
    comparison = report.get("comparison") if isinstance(report.get("comparison"), dict) else {}
    baseline = report.get("baseline") if isinstance(report.get("baseline"), dict) else {}
    baseline_summary = report.get("baseline_summary") if isinstance(report.get("baseline_summary"), dict) else {}
    routed_summary = report.get("agent_hub_summary") if isinstance(report.get("agent_hub_summary"), dict) else {}
    lines = [
        "# Agent-Hub Benchmark Report",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_float(report.get('created_at'))))}",
        f"Route: `{report.get('route')}`",
        f"Baseline: `{baseline.get('agent')}` (`{baseline.get('provider')}` / `{baseline.get('model')}`)",
        f"Tasks: {report.get('task_count', 0)}",
        "",
        "## Measured Results",
        "",
        "| Metric | Agent-Hub vs Baseline |",
        "| --- | ---: |",
        f"| Cost reduction | {_metric(comparison.get('cost_reduction'), '%')} |",
        f"| Latency reduction | {_metric(comparison.get('latency_reduction'), '%')} |",
        f"| Success delta | {_metric(comparison.get('success_delta'), ' pp')} |",
        f"| Total cost delta | {_money(comparison.get('total_cost_delta_usd'))} |",
        "",
        "## Summary",
        "",
        "| Strategy | Success | Avg latency | Total cost | Avg score |",
        "| --- | ---: | ---: | ---: | ---: |",
        _summary_line("Baseline", baseline_summary),
        _summary_line("Agent-Hub", routed_summary),
        "",
        "## Task Details",
        "",
        "| Task | Baseline | Agent-Hub | Cost reduction | Latency reduction | Success delta |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in report.get("results", [])[:50]:
        if not isinstance(row, dict):
            continue
        baseline_row = row.get("baseline") if isinstance(row.get("baseline"), dict) else {}
        routed_row = row.get("agent_hub") if isinstance(row.get("agent_hub"), dict) else {}
        compare = row.get("comparison") if isinstance(row.get("comparison"), dict) else {}
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row.get("task_type")),
                    _md(f"{baseline_row.get('agent')} / {baseline_row.get('model')}"),
                    _md(f"{routed_row.get('agent')} / {routed_row.get('model')}"),
                    _metric(compare.get("cost_reduction"), "%"),
                    _metric(compare.get("latency_reduction"), "%"),
                    str(compare.get("success_delta", 0)),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _summary_line(label: str, row: dict[str, Any]) -> str:
    return (
        f"| {label} | {_metric(_float(row.get('success_rate')) * 100, '%')} | "
        f"{_metric(row.get('average_latency_ms'), ' ms')} | {_money(row.get('total_cost_usd'))} | "
        f"{_metric(row.get('average_score'), '')} |"
    )


def _percent_reduction(new_value: Any, baseline_value: Any) -> float | None:
    baseline = _float_or_none(baseline_value)
    new = _float_or_none(new_value)
    if baseline is None or new is None or baseline <= 0:
        return None
    return round(((baseline - new) / baseline) * 100, 2)


def _delta(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return round(_float(left) - _float(right), 8)


def _usage_int(usage: dict[str, Any], *keys: str) -> int:
    if not isinstance(usage, dict):
        return 0
    total = _optional_int(usage.get("total_tokens"))
    input_tokens = _optional_int(usage.get("prompt_tokens")) or _optional_int(usage.get("input_tokens"))
    output_tokens = _optional_int(usage.get("completion_tokens")) or _optional_int(usage.get("output_tokens"))
    if total is not None and input_tokens is None and output_tokens is not None:
        input_tokens = max(0, total - output_tokens)
    if total is not None and output_tokens is None and input_tokens is not None:
        output_tokens = max(0, total - input_tokens)
    values = {
        "prompt_tokens": input_tokens,
        "input_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
    }
    for key in keys:
        value = values.get(key)
        if value is not None:
            return max(0, int(value))
    return 0


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric(value: Any, suffix: str) -> str:
    if value is None:
        return "unpriced"
    number = _float(value)
    return f"{number:.2f}{suffix}"


def _money(value: Any) -> str:
    if value is None:
        return "unpriced"
    return f"${_float(value):.6f}".rstrip("0").rstrip(".")


def _md(value: Any) -> str:
    return str(value or "").replace("|", "/")


__all__ = [
    "BenchmarkProofRunner",
    "BenchmarkReportPaths",
    "load_benchmark_corpus",
    "write_benchmark_report",
]
