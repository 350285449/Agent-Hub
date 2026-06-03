from __future__ import annotations

from typing import Any

from .core.router import AgentRouter
from .models import HubRequest
from .observability import metrics_snapshot, recent_events


def routing_status_body(config: Any, router: AgentRouter) -> dict[str, Any]:
    health = router.health_snapshot(include_history=True)
    routing = recent_events(config.state_dir, "routing", limit=100)
    latest = latest_routing_decision(routing)
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
        "routing_candidates": recommendations,
        "degraded_providers": [row for row in health.values() if row.get("degraded")],
        "cooldowns": {
            name: row.get("cooldown_until")
            for name, row in health.items()
            if row.get("cooldown_until")
        },
        "last_failover_reason": last_failover_reason(routing),
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
    return {
        "object": "agent_hub.routing.last_decision",
        "decision": latest,
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


def provider_health_body(config: Any, router: AgentRouter) -> dict[str, Any]:
    health = router.health_snapshot(include_history=True)
    return {
        "object": "agent_hub.provider_health",
        "providers": router.provider_status(),
        "health": health,
        "recent_failures": metrics_snapshot(config.state_dir, health).get("recent_failures", []),
    }


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
        if event.get("type") in {
            "routing_decision",
            "stream_request_started",
            "request_started",
            "native_stream_finished",
            "routing_failure",
        }:
            return dict(event)
    return dict(events[-1]) if events else {}


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


def event_source(event: dict[str, Any]) -> str:
    for key in ("source", "client", "request_source", "last_request_source"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    api_shape = event.get("api_shape")
    if isinstance(api_shape, str) and api_shape.strip():
        return api_shape.strip()
    return "unknown"
