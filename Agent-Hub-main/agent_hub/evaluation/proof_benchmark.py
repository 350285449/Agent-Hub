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
        "request_token_comparison": _request_token_comparison(baseline, routed),
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
        request_tokens = estimate_messages_tokens(request.messages)
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
            "request_input_tokens": request_tokens,
            "raw_request_input_tokens": request_tokens,
            "optimized_request_input_tokens": request_tokens,
            "token_accounting": _token_accounting(
                request_input_tokens=request_tokens,
                raw_request_input_tokens=request_tokens,
                provider_input_tokens=0,
                provider_output_tokens=0,
                input_tokens_used=request_tokens,
                output_tokens_used=0,
            ),
            "failover_count": 0,
            "error": str(exc),
        }


def _response_row(config: HubConfig, response: HubResponse, task: BenchmarkTask, *, latency_ms: float) -> dict[str, Any]:
    agent = config.agents.get(response.agent)
    context_usage = _response_context_usage(response)
    optimization_trace = _response_optimization_trace(response)
    request_input_tokens = _positive_int(
        context_usage.get("optimized_context_tokens"),
        context_usage.get("estimated_input_tokens"),
    ) or estimate_messages_tokens([{"role": "user", "content": task.prompt}])
    raw_request_input_tokens = _positive_int(
        context_usage.get("original_input_tokens"),
        context_usage.get("original_context_tokens"),
    ) or request_input_tokens
    provider_input_tokens = _usage_int(response.usage, "prompt_tokens", "input_tokens")
    provider_output_tokens = _usage_int(response.usage, "completion_tokens", "output_tokens")
    input_tokens = provider_input_tokens or request_input_tokens
    output_tokens = provider_output_tokens
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
        "request_input_tokens": request_input_tokens,
        "raw_request_input_tokens": raw_request_input_tokens,
        "optimized_request_input_tokens": request_input_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "token_accounting": _token_accounting(
            request_input_tokens=request_input_tokens,
            raw_request_input_tokens=raw_request_input_tokens,
            provider_input_tokens=provider_input_tokens,
            provider_output_tokens=provider_output_tokens,
            input_tokens_used=input_tokens,
            output_tokens_used=output_tokens,
        ),
        "failover_count": len(response.failover),
        "routing_explanation": _response_explanation(response),
        "optimization_trace": optimization_trace,
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
    outcome_metrics = _outcome_metrics(baseline_summary, routed_summary, comparison)
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
        "outcome_metrics": outcome_metrics,
        "token_savings_proof": _token_savings_proof(baseline_summary, routed_summary, pairs),
        "agent_hub_vs_raw_agent": {
            "raw_agent": baseline_summary,
            "raw_agent_label": _raw_agent_label(baseline_agent),
            "agent_hub": routed_summary,
            "metrics": outcome_metrics,
        },
        "cost_reduction": comparison.get("cost_reduction"),
        "token_reduction": comparison.get("token_reduction"),
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
    tokens = [_float(row.get("total_tokens")) for row in rows]
    request_tokens = [_float(row.get("request_input_tokens")) for row in rows]
    raw_request_tokens = [_float(row.get("raw_request_input_tokens")) for row in rows]
    provider_reported = sum(1 for row in rows if _dict(row.get("token_accounting")).get("provider_reported_input_tokens"))
    return {
        "task_count": total,
        "tasks_completed": successes,
        "successes": successes,
        "failures": max(0, total - successes),
        "success_rate": round(successes / max(1, total), 4),
        "quality_score": round(sum(scores) / max(1, len(scores)), 4),
        "average_score": round(sum(scores) / max(1, len(scores)), 4),
        "average_latency_ms": round(sum(latencies) / max(1, len(latencies)), 2) if latencies else 0.0,
        "time_to_working_solution_ms": round(sum(latencies) / max(1, successes), 2) if successes else 0.0,
        "total_tokens": int(sum(tokens)) if tokens else 0,
        "average_tokens": round(sum(tokens) / max(1, len(tokens)), 2) if tokens else 0.0,
        "total_request_input_tokens": int(sum(request_tokens)) if request_tokens else 0,
        "total_raw_request_input_tokens": int(sum(raw_request_tokens)) if raw_request_tokens else 0,
        "provider_reported_input_token_tasks": provider_reported,
        "total_cost_usd": round(sum(costs), 8) if costs else None,
        "average_cost_usd": round(sum(costs) / len(costs), 8) if costs else None,
        "priced_task_count": len(costs),
        "failover_count": sum(int(row.get("failover_count") or 0) for row in rows),
        "prompt_loops": sum(int(row.get("failover_count") or 0) for row in rows),
    }


def _comparison(baseline: dict[str, Any], routed: dict[str, Any]) -> dict[str, Any]:
    return {
        "cost_reduction": _percent_reduction(routed.get("total_cost_usd"), baseline.get("total_cost_usd")),
        "token_reduction": _percent_reduction(routed.get("total_tokens"), baseline.get("total_tokens")),
        "request_token_reduction": _percent_reduction(
            routed.get("total_request_input_tokens"),
            baseline.get("total_request_input_tokens"),
        ),
        "retry_reduction": _percent_reduction(routed.get("prompt_loops"), baseline.get("prompt_loops")),
        "latency_reduction": _percent_reduction(routed.get("average_latency_ms"), baseline.get("average_latency_ms")),
        "success_delta": round(
            (_float(routed.get("success_rate")) - _float(baseline.get("success_rate"))) * 100,
            2,
        ),
        "average_score_delta": round(_float(routed.get("average_score")) - _float(baseline.get("average_score")), 4),
        "failure_delta": int(routed.get("failures") or 0) - int(baseline.get("failures") or 0),
        "total_cost_delta_usd": _delta(routed.get("total_cost_usd"), baseline.get("total_cost_usd")),
        "total_tokens_delta": _delta(routed.get("total_tokens"), baseline.get("total_tokens")),
        "prompt_loops_avoided": max(0, int(baseline.get("prompt_loops") or 0) - int(routed.get("prompt_loops") or 0)),
        "average_latency_delta_ms": _delta(routed.get("average_latency_ms"), baseline.get("average_latency_ms")),
    }


def _pair_comparison(baseline: dict[str, Any], routed: dict[str, Any]) -> dict[str, Any]:
    return {
        "cost_reduction": _percent_reduction(routed.get("cost_usd"), baseline.get("cost_usd")),
        "token_reduction": _percent_reduction(routed.get("total_tokens"), baseline.get("total_tokens")),
        "request_token_reduction": _percent_reduction(
            routed.get("request_input_tokens"),
            baseline.get("request_input_tokens"),
        ),
        "latency_reduction": _percent_reduction(routed.get("latency_ms"), baseline.get("latency_ms")),
        "success_delta": int(bool(routed.get("success"))) - int(bool(baseline.get("success"))),
        "score_delta": round(_float(routed.get("score")) - _float(baseline.get("score")), 4),
    }


def _outcome_metrics(
    baseline: dict[str, Any],
    routed: dict[str, Any],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    cost_delta = comparison.get("total_cost_delta_usd")
    tokens_delta = comparison.get("total_tokens_delta")
    request_tokens_delta = _delta(
        routed.get("total_request_input_tokens"),
        baseline.get("total_request_input_tokens"),
    )
    return {
        "tasks_completed": int(routed.get("tasks_completed") or 0),
        "tokens_saved": int(abs(tokens_delta)) if tokens_delta is not None and float(tokens_delta) < 0 else 0,
        "tokens_saved_percent": comparison.get("token_reduction"),
        "request_tokens_saved": int(abs(request_tokens_delta))
        if request_tokens_delta is not None and float(request_tokens_delta) < 0
        else 0,
        "request_tokens_saved_percent": comparison.get("request_token_reduction"),
        "token_savings_basis": _summary_token_savings_basis(baseline, routed),
        "prompt_loops_avoided": comparison.get("prompt_loops_avoided", 0),
        "cost_saved_usd": round(abs(float(cost_delta)), 8)
        if cost_delta is not None and float(cost_delta) < 0
        else 0.0,
        "cost_saved_percent": comparison.get("cost_reduction"),
        "quality_score": routed.get("quality_score"),
        "quality_delta_pp": comparison.get("success_delta"),
        "time_to_working_solution_ms": routed.get("time_to_working_solution_ms"),
        "baseline_time_to_working_solution_ms": baseline.get("time_to_working_solution_ms"),
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


def _raw_agent_label(agent: AgentConfig) -> str:
    haystack = " ".join(
        str(value or "").lower()
        for value in (agent.name, agent.provider, agent.provider_type, agent.model)
    )
    if "claude" in haystack or "anthropic" in haystack:
        return "Claude Code alone"
    if "codex" in haystack or "openai" in haystack or "gpt" in haystack:
        return "Codex alone"
    return f"{agent.name} alone"


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


def _response_context_usage(response: HubResponse) -> dict[str, Any]:
    raw = response.raw if isinstance(response.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    usage = hub.get("context_usage") if isinstance(hub.get("context_usage"), dict) else {}
    return dict(usage)


def _response_optimization_trace(response: HubResponse) -> dict[str, Any]:
    raw = response.raw if isinstance(response.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    trace = hub.get("optimization_trace") if isinstance(hub.get("optimization_trace"), dict) else {}
    return dict(trace)


def _token_accounting(
    *,
    request_input_tokens: int,
    raw_request_input_tokens: int,
    provider_input_tokens: int,
    provider_output_tokens: int,
    input_tokens_used: int,
    output_tokens_used: int,
) -> dict[str, Any]:
    provider_reported = provider_input_tokens > 0
    return {
        "raw_request_input_tokens": max(0, int(raw_request_input_tokens or 0)),
        "optimized_request_input_tokens": max(0, int(request_input_tokens or 0)),
        "actual_request_input_tokens": max(0, int(request_input_tokens or 0)),
        "provider_reported_input_tokens": int(provider_input_tokens) if provider_reported else None,
        "provider_reported_output_tokens": int(provider_output_tokens) if provider_output_tokens > 0 else None,
        "input_tokens_used_for_cost": max(0, int(input_tokens_used or 0)),
        "output_tokens_used_for_cost": max(0, int(output_tokens_used or 0)),
        "input_token_source": "provider_reported_usage" if provider_reported else "actual_prepared_request_estimate",
        "token_savings_basis": "provider_reported_usage" if provider_reported else "actual_request_payload_estimate",
        "not_repo_size_delta": True,
    }


def _request_token_comparison(baseline: dict[str, Any], routed: dict[str, Any]) -> dict[str, Any]:
    raw_tokens = _optional_int(baseline.get("request_input_tokens")) or 0
    optimized_tokens = _optional_int(routed.get("request_input_tokens")) or 0
    saved = max(0, raw_tokens - optimized_tokens)
    return {
        "raw_agent_request_input_tokens": raw_tokens,
        "agent_hub_optimized_request_input_tokens": optimized_tokens,
        "request_tokens_saved": saved,
        "request_token_reduction": _percent_reduction(optimized_tokens, raw_tokens),
        "basis": _row_token_savings_basis(baseline, routed),
        "not_repo_size_delta": True,
    }


def _token_savings_proof(
    baseline: dict[str, Any],
    routed: dict[str, Any],
    pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_tokens = int(baseline.get("total_request_input_tokens") or 0)
    optimized_tokens = int(routed.get("total_request_input_tokens") or 0)
    return {
        "raw_agent_request_input_tokens": raw_tokens,
        "agent_hub_optimized_request_input_tokens": optimized_tokens,
        "request_tokens_saved": max(0, raw_tokens - optimized_tokens),
        "request_token_reduction": _percent_reduction(optimized_tokens, raw_tokens),
        "tokens_used_reduction": _percent_reduction(routed.get("total_tokens"), baseline.get("total_tokens")),
        "basis": _summary_token_savings_basis(baseline, routed),
        "definition": "raw agent request tokens vs Agent Hub optimized request tokens actually sent",
        "not_repo_size_delta": True,
        "sample_task_count": len(pairs),
    }


def _summary_token_savings_basis(baseline: dict[str, Any], routed: dict[str, Any]) -> str:
    if baseline.get("provider_reported_input_token_tasks") and routed.get("provider_reported_input_token_tasks"):
        return "provider_reported_usage"
    return "actual_request_payload_estimate"


def _row_token_savings_basis(baseline: dict[str, Any], routed: dict[str, Any]) -> str:
    baseline_accounting = _dict(baseline.get("token_accounting"))
    routed_accounting = _dict(routed.get("token_accounting"))
    if baseline_accounting.get("provider_reported_input_tokens") and routed_accounting.get("provider_reported_input_tokens"):
        return "provider_reported_usage"
    return "actual_request_payload_estimate"


def _markdown_report(report: dict[str, Any]) -> str:
    comparison = report.get("comparison") if isinstance(report.get("comparison"), dict) else {}
    outcomes = report.get("outcome_metrics") if isinstance(report.get("outcome_metrics"), dict) else {}
    baseline = report.get("baseline") if isinstance(report.get("baseline"), dict) else {}
    baseline_summary = report.get("baseline_summary") if isinstance(report.get("baseline_summary"), dict) else {}
    routed_summary = report.get("agent_hub_summary") if isinstance(report.get("agent_hub_summary"), dict) else {}
    raw_label = str((report.get("agent_hub_vs_raw_agent") or {}).get("raw_agent_label") or "Raw Agent")
    lines = [
        "# Agent Hub vs Raw Agent",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_float(report.get('created_at'))))}",
        f"Route: `{report.get('route')}`",
        f"Baseline: `{raw_label}` (`{baseline.get('provider')}` / `{baseline.get('model')}`)",
        f"Tasks: {report.get('task_count', 0)}",
        "",
        "## Outcome Metrics",
        "",
        "| Metric | Agent-Hub vs Baseline |",
        "| --- | ---: |",
        f"| Tasks completed | {outcomes.get('tasks_completed', routed_summary.get('tasks_completed', 0))} |",
        f"| Tokens used | {_metric(_negative_percent(comparison.get('token_reduction')), '%')} |",
        f"| Request tokens actually sent | {_metric(_negative_percent(comparison.get('request_token_reduction')), '%')} |",
        f"| Token savings basis | {_md(outcomes.get('token_savings_basis'))} |",
        f"| Tokens saved | {_metric(outcomes.get('tokens_saved'), ' tokens')} |",
        f"| Request tokens saved | {_metric(outcomes.get('request_tokens_saved'), ' tokens')} |",
        f"| Prompt loops avoided | {outcomes.get('prompt_loops_avoided', 0)} |",
        f"| Cost reduction | {_metric(comparison.get('cost_reduction'), '%')} |",
        f"| Cost saved | {_money(outcomes.get('cost_saved_usd'))} |",
        f"| Task success | {_metric(comparison.get('success_delta'), ' pp')} |",
        f"| Quality score | {_metric(outcomes.get('quality_score'), '')} |",
        f"| Time to working solution | {_metric(outcomes.get('time_to_working_solution_ms'), ' ms')} |",
        "",
        "## Summary",
        "",
        "| Strategy | Success | Tokens | Cost | Quality | Time to working solution |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        _summary_line(raw_label, baseline_summary),
        _summary_line("Agent Hub", routed_summary),
        "",
        "## Task Details",
        "",
        "| Task | Raw Agent | Agent Hub | Tokens | Cost | Success delta |",
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
                    _metric(_negative_percent(compare.get("token_reduction")), "%"),
                    _metric(compare.get("cost_reduction"), "%"),
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
        f"{_metric(row.get('total_tokens'), '')} | {_money(row.get('total_cost_usd'))} | "
        f"{_metric(row.get('quality_score', row.get('average_score')), '')} | "
        f"{_metric(row.get('time_to_working_solution_ms'), ' ms')} |"
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


def _positive_int(*values: Any) -> int | None:
    for value in values:
        parsed = _optional_int(value)
        if parsed is not None and parsed > 0:
            return parsed
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


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _metric(value: Any, suffix: str) -> str:
    if value is None:
        return "unpriced"
    number = _float(value)
    return f"{number:.2f}{suffix}"


def _negative_percent(value: Any) -> float | None:
    if value is None:
        return None
    return -_float(value)


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
