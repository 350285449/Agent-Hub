from __future__ import annotations

from typing import Any

from .core.router import AgentRouter
from .models import HubRequest
from .observability import metrics_snapshot, recent_events
from .repository_intelligence import (
    build_autonomous_night_mode_plan,
    build_cost_optimizer_summary,
    build_failure_prediction,
    build_model_performance_database,
)


def routing_status_body(config: Any, router: AgentRouter) -> dict[str, Any]:
    health = router.health_snapshot(include_history=True)
    routing = recent_events(config.state_dir, "routing", limit=100)
    latest = latest_routing_decision(routing)
    latest_decision = latest.get("routing_decision") if isinstance(latest.get("routing_decision"), dict) else {}
    recommendations = router.recommend(
        HubRequest(
            session_id="routing-status",
            route="cloud-agent",
            messages=[{"role": "user", "content": "diagnose active routing"}],
            record_session=False,
        ),
        limit=12,
        needs_tools=True,
        include_unavailable=True,
    )
    return {
        "object": "agent_hub.routing.status",
        "status": "running",
        "running": True,
        "active_provider": latest.get("agent") or latest.get("selected_agent"),
        "active_model": latest.get("model") or latest.get("selected_model"),
        "selected_provider": latest.get("provider") or latest_decision.get("selected_provider"),
        "selected_model": latest.get("model") or latest_decision.get("selected_model"),
        "routing_reason": latest_decision.get("reason") or latest.get("reason") or "",
        "task_classification": latest_decision.get("task_classification") or {},
        "cost_context_estimate": _cost_context_estimate(latest),
        "routing_candidates": recommendations,
        "degraded_providers": [row for row in health.values() if row.get("degraded")],
        "cooldowns": {
            name: row.get("cooldown_until")
            for name, row in health.items()
            if row.get("cooldown_until")
        },
        "last_failover_reason": last_failover_reason(routing),
        "fallback_events": routing_failures(routing),
        "permission_blocked_actions": permission_blocked_actions(config),
        "workflow_progress": workflow_progress(config),
        "last_decision": latest,
        "client_sources": client_source_counts(config, health),
        "streaming_stats": {
            name: {
                "streaming_tokens_per_second": row.get("streaming_tokens_per_second"),
                "last_first_token_latency_seconds": row.get("last_first_token_latency_seconds"),
            }
            for name, row in health.items()
            if row.get("supports_streaming")
        },
        "provider_health": health,
    }


def routing_last_decision_body(config: Any) -> dict[str, Any]:
    routing = recent_events(config.state_dir, "routing", limit=100)
    latest = latest_routing_decision(routing)
    decision = latest.get("routing_decision") if isinstance(latest.get("routing_decision"), dict) else {}
    if not decision:
        memory = recent_events(config.state_dir, "routing_memory", limit=1)
        decision = _decision_from_memory(memory[-1] if memory else {})
    if decision:
        decision = dict(decision)
        decision["explanation"] = _normalized_decision_explanation(decision)
        latest = dict(latest)
        latest["routing_decision"] = decision
    return {
        "object": "agent_hub.routing.last_decision",
        "decision": latest,
        "selected_provider": latest.get("provider") or decision.get("selected_provider"),
        "selected_model": latest.get("model") or decision.get("selected_model"),
        "routing_reason": decision.get("reason") or latest.get("reason") or "",
        "task_classification": decision.get("task_classification") or {},
        "cost_context_estimate": _cost_context_estimate(latest),
        "failover": latest.get("failover", []) if isinstance(latest, dict) else [],
    }


def routing_test_failover_body(config: Any, router: AgentRouter) -> dict[str, Any]:
    request = HubRequest(
        session_id="routing-test-failover",
        route="cloud-agent",
        messages=[{"role": "user", "content": "simulate provider failover"}],
        record_session=False,
    )
    candidates = router.recommend(
        request,
        limit=20,
        needs_tools=True,
        include_unavailable=True,
    )
    available = [row for row in candidates if row.get("available")]
    simulated_failed = available[0] if available else (candidates[0] if candidates else None)
    simulated_next = next(
        (
            row
            for row in candidates
            if simulated_failed
            and row.get("agent") != simulated_failed.get("agent")
            and row.get("available")
        ),
        None,
    )
    return {
        "object": "agent_hub.routing.test_failover",
        "dry_run": True,
        "source": "diagnostics",
        "selected": simulated_failed,
        "next_compatible_provider": simulated_next,
        "candidates": candidates,
        "message": "Dry run only; no provider request was sent and no cooldown was changed.",
    }


def client_sources_body(config: Any, router: AgentRouter) -> dict[str, Any]:
    health = router.health_snapshot(include_history=True)
    return {
        "object": "agent_hub.client_sources",
        "sources": client_source_counts(config, health),
        "recent_requests": recent_events(config.state_dir, "requests", limit=100),
    }


def routing_history_body(config: Any) -> dict[str, Any]:
    events = recent_events(config.state_dir, "routing", limit=100)
    return {
        "object": "agent_hub.routing_history",
        "data": events,
        "count": len(events),
    }


def routing_intelligence_body(
    config: Any,
    router: AgentRouter,
    *,
    optimization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose the product-facing routing intelligence view from existing state."""

    health = router.health_snapshot(include_history=True)
    routing = recent_events(config.state_dir, "routing", limit=100)
    latest = latest_routing_decision(routing)
    latest_decision = latest.get("routing_decision") if isinstance(latest.get("routing_decision"), dict) else {}
    if not latest_decision:
        memory = recent_events(config.state_dir, "routing_memory", limit=1)
        latest_decision = _decision_from_memory(memory[-1] if memory else {})
        if latest_decision:
            latest = dict(latest)
            latest["routing_decision"] = latest_decision
    latest_explanation = _normalized_decision_explanation(latest_decision)
    optimization = optimization if isinstance(optimization, dict) else router.adaptive_learning.optimization_summary()
    routing_memory = router.routing_memory.stats()
    candidates = latest_decision.get("candidate_scores") if isinstance(latest_decision.get("candidate_scores"), list) else []
    provider_rankings = _provider_rankings(router, health, latest_explanation, candidates)
    model_rankings = _model_rankings(optimization, latest_explanation, candidates)
    workflow_rankings = _workflow_rankings(optimization)
    failovers = routing_failures(routing)
    repository_dna = latest_decision.get("repository_dna") if isinstance(latest_decision.get("repository_dna"), dict) else {}
    if not repository_dna:
        repository_dna = optimization.get("repository_dna") if isinstance(optimization.get("repository_dna"), dict) else {}
    workspace_memory = latest_decision.get("workspace_memory") if isinstance(latest_decision.get("workspace_memory"), dict) else {}
    if not workspace_memory:
        workspace_memory = optimization.get("workspace_memory") if isinstance(optimization.get("workspace_memory"), dict) else {}
    failure_prediction = latest_decision.get("failure_prediction") if isinstance(latest_decision.get("failure_prediction"), dict) else {}
    if not failure_prediction and latest_decision:
        failure_prediction = build_failure_prediction(decision=latest_decision, config=config)
    model_performance = build_model_performance_database(
        optimization=optimization,
        routing_memory=routing_memory,
        dna=repository_dna,
    )
    cost_optimizer = build_cost_optimizer_summary(
        decision=latest_decision,
        routing_events=routing,
    )
    return {
        "object": "agent_hub.routing_intelligence",
        "feature": "Adaptive Workspace Intelligence",
        "repository_dna": repository_dna,
        "workspace_memory": workspace_memory,
        "failure_prediction": failure_prediction,
        "model_performance_database": model_performance,
        "cost_optimizer": cost_optimizer,
        "autonomous_night_mode": build_autonomous_night_mode_plan(dna=repository_dna, config=config),
        "latest_decision": latest,
        "latest_explanation": latest_explanation,
        "routing_decisions": _recent_decision_rows(routing),
        "provider_rankings": provider_rankings,
        "model_rankings": model_rankings,
        "workflow_rankings": workflow_rankings,
        "adaptive_learning_trends": _adaptive_learning_trends(optimization),
        "failover_events": failovers,
        "cost_savings": _cost_savings_summary(latest_explanation, routing_memory, cost_optimizer),
        "context_optimization": _context_optimization_summary(latest, latest_explanation, health),
        "success_rate_trends": _success_rate_trends(health, optimization),
        "routing_explanations": _recent_explanations(routing),
        "routing_memory": routing_memory,
    }


def provider_health_body(config: Any, router: AgentRouter) -> dict[str, Any]:
    health = router.health_snapshot(include_history=True)
    return {
        "object": "agent_hub.provider_health",
        "providers": router.provider_status(),
        "health": health,
        "recent_failures": metrics_snapshot(config.state_dir, health).get("recent_failures", []),
    }


def routing_memory_stats_body(config: Any, router: AgentRouter) -> dict[str, Any]:
    del config
    return router.routing_memory.stats()


def routing_memory_recent_body(config: Any, router: AgentRouter, *, limit: int = 50) -> dict[str, Any]:
    del config
    recent = router.routing_memory.recent(limit=limit)
    return {
        "object": "agent_hub.routing_memory.recent",
        "enabled": router.routing_memory.enabled,
        "count": len(recent),
        "data": recent,
    }


def routing_decision_by_id_body(config: Any, router: AgentRouter, request_id: str) -> dict[str, Any]:
    request_ids = _request_id_aliases(request_id)
    events = [
        event
        for event in recent_events(config.state_dir, "routing", limit=100)
        if event.get("request_id") in request_ids
    ]
    decision_event = latest_routing_decision(events)
    memory = [
        row
        for row in router.routing_memory.recent(limit=200)
        if row.get("request_id") in request_ids
    ]
    decision = (
        decision_event.get("routing_decision")
        if isinstance(decision_event.get("routing_decision"), dict)
        else {}
    )
    if not decision and memory:
        decision = _decision_from_memory(memory[-1])
    if decision:
        decision = dict(decision)
        decision["explanation"] = _normalized_decision_explanation(decision)
        decision_event = dict(decision_event)
        decision_event["routing_decision"] = decision
    return {
        "object": "agent_hub.routing_decision",
        "request_id": request_id,
        "request_id_aliases": sorted(request_ids),
        "found": bool(events or memory),
        "decision": decision_event,
        "routing_decision": decision,
        "explanation": decision.get("explanation") if isinstance(decision.get("explanation"), dict) else {},
        "memory_records": memory,
        "events": events,
    }


def _request_id_aliases(value: str) -> set[str]:
    text = str(value or "").strip()
    aliases = {text} if text else set()
    for prefix in ("chatcmpl-", "resp_", "msg_"):
        if text.startswith(prefix):
            aliases.add(text[len(prefix) :])
    return aliases


def routing_failures(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for event in events:
        failover = event.get("failover")
        if isinstance(failover, list) and failover:
            failures.extend(item for item in failover if isinstance(item, dict))
        elif event.get("type") == "routing_failure":
            failures.append(event)
    return failures[-25:]


def latest_routing_decision(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if isinstance(event.get("routing_decision"), dict):
            return dict(event)
    for event in reversed(events):
        if event.get("type") in {
            "routing_decision",
            "stream_request_started",
            "request_started",
            "native_stream_finished",
            "routing_failure",
        }:
            return dict(event)
    return dict(events[-1]) if events else {}


def _normalized_decision_explanation(decision: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(decision, dict) or not decision:
        return {}
    explanation = decision.get("explanation") if isinstance(decision.get("explanation"), dict) else {}
    reasons = explanation.get("reasons") if isinstance(explanation.get("reasons"), list) else []
    if reasons:
        return {
            "object": explanation.get("object") or "agent_hub.routing_decision_explanation",
            **explanation,
        }
    selected = explanation.get("selected") if isinstance(explanation.get("selected"), dict) else {}
    if not selected:
        selected = {
            "agent": decision.get("selected_agent"),
            "provider": decision.get("selected_provider"),
            "model": decision.get("selected_model"),
            "workflow": decision.get("selected_workflow"),
            "routing_mode": decision.get("routing_mode"),
            "risk_level": decision.get("risk"),
        }
    raw_reasons = decision.get("routing_reasons") if isinstance(decision.get("routing_reasons"), list) else []
    reasons = [str(reason) for reason in raw_reasons if str(reason or "").strip()]
    if not reasons and decision.get("reason"):
        reasons = [str(decision.get("reason"))]
    if not reasons and selected.get("agent"):
        reasons = [f"Selected {selected['agent']} for {decision.get('routing_mode') or 'auto'} routing."]
    return {
        "object": "agent_hub.routing_decision_explanation",
        "summary": explanation.get("summary") or decision.get("selected_reason") or decision.get("reason") or "",
        "selected": {key: value for key, value in selected.items() if value not in (None, "")},
        "reasons": reasons,
        "rejected": explanation.get("rejected") if isinstance(explanation.get("rejected"), list) else [],
        **{key: value for key, value in explanation.items() if key not in {"object", "summary", "selected", "reasons", "rejected"}},
    }


def _decision_from_memory(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict) or not row:
        return {}
    agent = row.get("agent")
    provider = row.get("provider")
    model = row.get("model")
    routing_mode = row.get("routing_mode") or row.get("route")
    task_type = row.get("task_type")
    reason = f"Recovered compact routing decision for {agent or model or 'selected model'} from routing memory."
    return {
        "request_id": row.get("request_id"),
        "selected_agent": agent,
        "selected_provider": provider,
        "selected_model": model,
        "routing_mode": routing_mode,
        "route": row.get("route"),
        "task_type": task_type,
        "task_category": row.get("task_category"),
        "language": row.get("language"),
        "complexity": row.get("complexity"),
        "risk": row.get("risk_level"),
        "selected_workflow": row.get("workflow"),
        "reason": reason,
        "routing_reasons": [
            reason,
            f"Task type: {task_type or 'unknown'}.",
            f"Outcome memory recorded success={bool(row.get('success'))}.",
        ],
        "task_classification": {
            "task_type": task_type,
            "task_category": row.get("task_category"),
            "language": row.get("language"),
            "complexity": row.get("complexity"),
            "risk_level": row.get("risk_level"),
        },
    }


def last_failover_reason(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        failover = event.get("failover")
        if isinstance(failover, list):
            for item in reversed(failover):
                if isinstance(item, dict) and item.get("reason"):
                    return str(item["reason"])
        if event.get("type") == "routing_failure" and event.get("message"):
            return str(event["message"])
    return ""


def client_source_counts(config: Any, health: dict[str, dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    requests = recent_events(config.state_dir, "requests", limit=100)
    routing = recent_events(config.state_dir, "routing", limit=100)
    for event in [*requests, *routing]:
        source = event_source(event)
        counts[source] = counts.get(source, 0) + 1
    for row in health.values():
        source = row.get("last_request_source")
        if isinstance(source, str) and source:
            counts[source] = counts.get(source, 0) + 1
    return {
        "counts": counts,
        "known_sources": sorted(counts),
        "recent": [
            {
                "time": event.get("time"),
                "source": event_source(event),
                "api_shape": event.get("api_shape"),
                "route": event.get("route"),
                "stream": event.get("stream"),
            }
            for event in requests[-25:]
        ],
    }


def recent_workflow_stages(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events[-50:]
        if isinstance(event.get("workflow_stage"), str)
        or str(event.get("type", "")).startswith("workflow_")
    ][-25:]


def permission_blocked_actions(config: Any) -> list[dict[str, Any]]:
    events = recent_events(config.state_dir, "permissions", limit=100)
    blocked = [
        event
        for event in events
        if event.get("denied") is True or event.get("requires_approval") is True
    ]
    return blocked[-25:]


def workflow_progress(config: Any) -> list[dict[str, Any]]:
    events = recent_events(config.state_dir, "workflows", limit=100)
    return [
        event
        for event in events
        if str(event.get("type", "")).startswith("workflow_")
    ][-25:]


def _cost_context_estimate(event: dict[str, Any]) -> dict[str, Any]:
    decision = event.get("routing_decision") if isinstance(event.get("routing_decision"), dict) else {}
    candidates = decision.get("candidate_scores") if isinstance(decision.get("candidate_scores"), list) else []
    selected = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    return {
        "estimated_input_tokens": (
            event.get("estimated_input_tokens")
            or decision.get("estimated_input_tokens")
            or selected.get("estimated_input_tokens")
        ),
        "estimated_output_tokens": selected.get("estimated_output_tokens"),
        "estimated_cost_usd": selected.get("estimated_cost_usd"),
        "context_strategy": (
            (decision.get("task_classification") or {}).get("context_strategy")
            if isinstance(decision.get("task_classification"), dict)
            else None
        ),
    }


def _provider_rankings(
    router: AgentRouter,
    health: dict[str, dict[str, Any]],
    latest_explanation: dict[str, Any],
    candidates: list[Any],
) -> list[dict[str, Any]]:
    rows = latest_explanation.get("provider_rankings") if isinstance(latest_explanation, dict) else None
    if isinstance(rows, list) and rows:
        return [row for row in rows if isinstance(row, dict)][:12]
    if candidates:
        return [
            {
                "rank": row.get("rank"),
                "agent": row.get("agent"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "score": row.get("final_routing_score", row.get("routing_score")),
                "why": row.get("why"),
            }
            for row in candidates[:12]
            if isinstance(row, dict)
        ]
    return sorted(
        (
            {
                "rank": 0,
                "agent": row.get("agent") or name,
                "provider": row.get("provider"),
                "model": row.get("model"),
                "score": row.get("score"),
                "success_rate": row.get("success_rate"),
                "average_latency_ms": row.get("average_latency_ms"),
                "available": row.get("available"),
            }
            for name, row in health.items()
        ),
        key=lambda row: (
            not bool(row.get("available")),
            -_safe_float(row.get("score"), 0.0),
            str(row.get("agent") or ""),
        ),
    )[:12]


def _model_rankings(
    optimization: dict[str, Any],
    latest_explanation: dict[str, Any],
    candidates: list[Any],
) -> list[dict[str, Any]]:
    rows = latest_explanation.get("model_rankings") if isinstance(latest_explanation, dict) else None
    if isinstance(rows, list) and rows:
        return [row for row in rows if isinstance(row, dict)][:12]
    model_rates = optimization.get("model_win_rates") if isinstance(optimization.get("model_win_rates"), list) else []
    if model_rates:
        return [row for row in model_rates if isinstance(row, dict)][:12]
    return [
        {
            "rank": row.get("rank"),
            "agent": row.get("agent"),
            "provider": row.get("provider"),
            "model": row.get("model"),
            "score": row.get("final_routing_score", row.get("routing_score")),
        }
        for row in candidates[:12]
        if isinstance(row, dict)
    ]


def _workflow_rankings(optimization: dict[str, Any]) -> list[dict[str, Any]]:
    rows = optimization.get("workflow_analytics") if isinstance(optimization.get("workflow_analytics"), list) else []
    if rows:
        return [row for row in rows if isinstance(row, dict)][:12]
    patterns = optimization.get("workflow_patterns") if isinstance(optimization.get("workflow_patterns"), list) else []
    return [row for row in patterns if isinstance(row, dict)][:12]


def _adaptive_learning_trends(optimization: dict[str, Any]) -> dict[str, Any]:
    return {
        "recent": optimization.get("recent_optimization_decisions", []),
        "model_scorecards": optimization.get("model_scorecards", []),
        "model_win_rates": optimization.get("model_win_rates", []),
        "workflow_success_rate": optimization.get("workflow_success_rate", {}),
        "average_latency_ms": optimization.get("average_latency_ms"),
        "average_known_cost_usd": optimization.get("average_known_cost_usd"),
        "average_retries": optimization.get("average_retries"),
    }


def _recent_decision_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events[-25:]:
        decision = event.get("routing_decision") if isinstance(event.get("routing_decision"), dict) else {}
        rows.append(
            {
                "time": event.get("time"),
                "request_id": event.get("request_id"),
                "type": event.get("type"),
                "agent": event.get("agent") or decision.get("selected_agent"),
                "provider": event.get("provider") or decision.get("selected_provider"),
                "model": event.get("model") or decision.get("selected_model"),
                "workflow": decision.get("selected_workflow"),
                "task_type": decision.get("task_type"),
                "risk": decision.get("risk"),
                "reason": decision.get("reason") or event.get("reason") or event.get("message"),
                "failover_count": len(event.get("failover") or []),
            }
        )
    return rows


def _recent_explanations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events[-25:]:
        decision = event.get("routing_decision") if isinstance(event.get("routing_decision"), dict) else {}
        explanation = decision.get("explanation") if isinstance(decision.get("explanation"), dict) else {}
        if explanation:
            rows.append(
                {
                    "time": event.get("time"),
                    "request_id": event.get("request_id"),
                    "summary": explanation.get("summary"),
                    "selected": explanation.get("selected", {}),
                    "reasons": explanation.get("reasons", [])[:6],
                    "rejected": explanation.get("rejected", [])[:6],
                }
            )
    return rows[-10:]


def _cost_savings_summary(
    explanation: dict[str, Any],
    routing_memory: dict[str, Any],
    cost_optimizer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cost = explanation.get("cost_savings") if isinstance(explanation, dict) else {}
    if not isinstance(cost, dict):
        cost = {}
    winner = routing_memory.get("cost_performance_winner") if isinstance(routing_memory.get("cost_performance_winner"), dict) else {}
    return {
        **cost,
        **(cost_optimizer or {}),
        "routing_memory_cost_performance_winner": winner,
    }


def _context_optimization_summary(
    latest: dict[str, Any],
    explanation: dict[str, Any],
    health: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    context = explanation.get("context_optimization") if isinstance(explanation, dict) else {}
    context = dict(context) if isinstance(context, dict) else {}
    context.update({k: v for k, v in _cost_context_estimate(latest).items() if v is not None})
    compactions = []
    for row in health.values():
        usage = row.get("last_context_compaction_usage")
        if isinstance(usage, dict) and usage:
            compactions.append(
                {
                    "agent": row.get("agent"),
                    "provider": row.get("provider"),
                    "model": row.get("model"),
                    "tokens_saved": usage.get("tokens_saved"),
                    "compression_ratio": usage.get("compression_ratio"),
                    "context_reduced": usage.get("context_reduced"),
                    "context_cache_hit": usage.get("context_cache_hit"),
                }
            )
    context["recent_compactions"] = compactions[-10:]
    return context


def _success_rate_trends(
    health: dict[str, dict[str, Any]],
    optimization: dict[str, Any],
) -> dict[str, Any]:
    provider_rows = [
        {
            "agent": row.get("agent") or name,
            "provider": row.get("provider"),
            "model": row.get("model"),
            "success_rate": row.get("success_rate"),
            "success_count": row.get("success_count"),
            "failure_count": row.get("failure_count"),
            "timeout_count": row.get("timeout_count"),
        }
        for name, row in health.items()
    ]
    return {
        "providers": sorted(
            provider_rows,
            key=lambda row: (
                -_safe_float(row.get("success_rate"), 0.0),
                str(row.get("agent") or ""),
            ),
        ),
        "workflows": optimization.get("workflow_patterns", []),
        "models": optimization.get("model_win_rates", []),
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def event_source(event: dict[str, Any]) -> str:
    for key in ("source", "client", "request_source", "last_request_source"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    api_shape = event.get("api_shape")
    if isinstance(api_shape, str) and api_shape.strip():
        return api_shape.strip()
    return "unknown"
