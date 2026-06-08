from __future__ import annotations

import re
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


_DYNAMIC_SEGMENT_RE = re.compile(r"^[0-9a-fA-F-]{12,}$|^\d+$")


@dataclass(slots=True)
class KernelRequestSample:
    method: str
    path: str
    status: int
    duration_ms: float
    cache_state: str
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": _iso_timestamp(self.timestamp),
            "method": self.method,
            "path": self.path,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "cache_state": self.cache_state or "none",
        }


class AgentHubRuntimeKernel:
    """Small control-plane observer for HTTP, cache, routing, and safety state."""

    def __init__(
        self,
        *,
        slow_request_threshold_ms: float = 750.0,
        max_recent_slow_requests: int = 40,
        max_route_stats: int = 96,
    ) -> None:
        self.boot_id = uuid.uuid4().hex
        self.started_at = time.time()
        self._started_monotonic = time.monotonic()
        self.slow_request_threshold_ms = float(slow_request_threshold_ms)
        self.max_route_stats = int(max_route_stats)
        self._lock = threading.RLock()
        self._in_flight = 0
        self._request_count = 0
        self._status_codes: Counter[str] = Counter()
        self._methods: Counter[str] = Counter()
        self._cache_states: Counter[str] = Counter()
        self._latency_total_ms = 0.0
        self._latency_ewma_ms = 0.0
        self._latency_max_ms = 0.0
        self._recent_slow_requests: deque[KernelRequestSample] = deque(maxlen=max_recent_slow_requests)
        self._timeline: deque[dict[str, Any]] = deque(maxlen=80)
        self._routes: dict[str, dict[str, Any]] = {}
        with self._lock:
            self._record_event_locked(
                event_type="boot",
                title="Runtime kernel booted",
                tone="ok",
                detail="Control-plane telemetry is online.",
                data={"boot_id": self.boot_id},
            )

    def begin_request(self) -> None:
        with self._lock:
            self._in_flight += 1

    def record_request(
        self,
        *,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
        cache_state: str = "",
    ) -> None:
        route = normalize_route(path)
        method = (method or "GET").upper()
        status = int(status or 0)
        duration_ms = max(0.0, float(duration_ms or 0.0))
        cache_state = str(cache_state or "").lower()
        timestamp = time.time()
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._request_count += 1
            self._status_codes[str(status)] += 1
            self._methods[method] += 1
            if cache_state:
                self._cache_states[cache_state] += 1
            self._latency_total_ms += duration_ms
            self._latency_max_ms = max(self._latency_max_ms, duration_ms)
            if self._latency_ewma_ms <= 0:
                self._latency_ewma_ms = duration_ms
            else:
                self._latency_ewma_ms = (self._latency_ewma_ms * 0.82) + (duration_ms * 0.18)

            route_stats = self._routes.setdefault(
                route,
                {
                    "path": route,
                    "count": 0,
                    "error_count": 0,
                    "cache_hits": 0,
                    "cache_misses": 0,
                    "total_latency_ms": 0.0,
                    "ewma_latency_ms": 0.0,
                    "max_latency_ms": 0.0,
                    "last_status": 0,
                    "last_seen": 0.0,
                },
            )
            route_stats["count"] = int(route_stats["count"]) + 1
            route_stats["error_count"] = int(route_stats["error_count"]) + (1 if status >= 400 else 0)
            route_stats["total_latency_ms"] = float(route_stats["total_latency_ms"]) + duration_ms
            route_stats["max_latency_ms"] = max(float(route_stats["max_latency_ms"]), duration_ms)
            route_stats["last_status"] = status
            route_stats["last_seen"] = timestamp
            if float(route_stats["ewma_latency_ms"]) <= 0:
                route_stats["ewma_latency_ms"] = duration_ms
            else:
                route_stats["ewma_latency_ms"] = (float(route_stats["ewma_latency_ms"]) * 0.78) + (
                    duration_ms * 0.22
                )
            if cache_state == "hit":
                route_stats["cache_hits"] = int(route_stats["cache_hits"]) + 1
            elif cache_state == "miss":
                route_stats["cache_misses"] = int(route_stats["cache_misses"]) + 1

            if duration_ms >= self.slow_request_threshold_ms:
                self._recent_slow_requests.append(
                    KernelRequestSample(
                        method=method,
                        path=route,
                        status=status,
                        duration_ms=duration_ms,
                        cache_state=cache_state,
                        timestamp=timestamp,
                    )
                )
                self._record_event_locked(
                    event_type="slow_request",
                    title=f"Slow {method} {route}",
                    tone="warn",
                    detail=f"{duration_ms:.1f} ms crossed {self.slow_request_threshold_ms:.1f} ms.",
                    data={"status": status, "cache_state": cache_state},
                )
            if status >= 500:
                self._record_event_locked(
                    event_type="server_error",
                    title=f"{status} from {method} {route}",
                    tone="error",
                    detail="The backend returned a server error.",
                    data={"duration_ms": round(duration_ms, 2), "cache_state": cache_state},
                )
            elif status >= 400:
                self._record_event_locked(
                    event_type="client_error",
                    title=f"{status} from {method} {route}",
                    tone="warn",
                    detail="The request completed with a non-success status.",
                    data={"duration_ms": round(duration_ms, 2), "cache_state": cache_state},
                )
            self._prune_routes_locked()

    def snapshot(
        self,
        *,
        config: Any,
        router: Any,
        diagnostics_cache: dict[str, Any],
    ) -> dict[str, Any]:
        provider_health, provider_error = _provider_health(router)
        routing_memory, routing_memory_error = _routing_memory(router)
        telemetry = self._telemetry_snapshot()
        subsystems = _subsystems(
            config=config,
            provider_health=provider_health,
            provider_error=provider_error,
            diagnostics_cache=diagnostics_cache,
            routing_memory=routing_memory,
            routing_memory_error=routing_memory_error,
        )
        pressure = _pressure_snapshot(telemetry, diagnostics_cache)
        score = _operational_score(
            config=config,
            telemetry=telemetry,
            subsystems=subsystems,
            provider_health=provider_health,
            diagnostics_cache=diagnostics_cache,
        )
        state = _kernel_state(score, subsystems)
        next_actions = _next_actions(
            config=config,
            telemetry=telemetry,
            subsystems=subsystems,
            provider_health=provider_health,
            diagnostics_cache=diagnostics_cache,
            pressure=pressure,
        )
        return {
            "object": "agent_hub.runtime_kernel",
            "boot_id": self.boot_id,
            "state": state,
            "operational_score": score,
            "started_at": _iso_timestamp(self.started_at),
            "uptime_seconds": round(time.monotonic() - self._started_monotonic, 3),
            "subsystems": subsystems,
            "request_telemetry": telemetry,
            "pressure": pressure,
            "service_map": _service_map(subsystems),
            "timeline": self._timeline_snapshot(),
            "primary_next_action": next_actions[0],
            "next_actions": next_actions,
            "diagnostics_cache": diagnostics_cache,
            "kernel_policy": {
                "slow_request_threshold_ms": round(self.slow_request_threshold_ms, 2),
                "max_recent_slow_requests": self._recent_slow_requests.maxlen,
                "max_route_stats": self.max_route_stats,
            },
        }

    def efficiency_summary(self) -> dict[str, Any]:
        telemetry = self._telemetry_snapshot()
        return {
            "object": "agent_hub.runtime_kernel.efficiency",
            "boot_id": self.boot_id,
            "uptime_seconds": round(time.monotonic() - self._started_monotonic, 3),
            "total_requests": telemetry.get("total_requests", 0),
            "in_flight": telemetry.get("in_flight", 0),
            "error_rate": telemetry.get("error_rate", 0.0),
            "cache_hit_rate": telemetry.get("cache_hit_rate", 0.0),
            "latency_ms": telemetry.get("latency_ms", {}),
            "slow_request_count": len(telemetry.get("recent_slow_requests") or []),
            "pressure_state": _pressure_snapshot(telemetry, {}).get("state", "nominal"),
        }

    def _telemetry_snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = self._request_count
            cache_total = sum(self._cache_states.values())
            route_rows = [_route_snapshot(row) for row in self._routes.values()]
            route_rows.sort(key=lambda row: (-int(row["count"]), str(row["path"])))
            status_codes = dict(sorted(self._status_codes.items(), key=lambda item: item[0]))
            methods = dict(sorted(self._methods.items(), key=lambda item: item[0]))
            cache_states = dict(sorted(self._cache_states.items(), key=lambda item: item[0]))
            slow_requests = [sample.to_dict() for sample in reversed(self._recent_slow_requests)]
            error_count = sum(count for status, count in self._status_codes.items() if int(status or 0) >= 400)
            return {
                "total_requests": total,
                "in_flight": self._in_flight,
                "status_codes": status_codes,
                "methods": methods,
                "cache_states": cache_states,
                "cache_hit_rate": round(self._cache_states.get("hit", 0) / cache_total, 4) if cache_total else 0.0,
                "error_rate": round(error_count / total, 4) if total else 0.0,
                "latency_ms": {
                    "average": round(self._latency_total_ms / total, 2) if total else 0.0,
                    "ewma": round(self._latency_ewma_ms, 2),
                    "max": round(self._latency_max_ms, 2),
                },
                "routes": route_rows[:20],
                "recent_slow_requests": slow_requests,
            }

    def _prune_routes_locked(self) -> None:
        overflow = len(self._routes) - self.max_route_stats
        if overflow <= 0:
            return
        candidates = sorted(
            self._routes.items(),
            key=lambda item: (int(item[1].get("count") or 0), float(item[1].get("last_seen") or 0.0)),
        )
        for route, _stats in candidates[:overflow]:
            self._routes.pop(route, None)

    def _timeline_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._timeline))

    def _record_event_locked(
        self,
        *,
        event_type: str,
        title: str,
        tone: str,
        detail: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        self._timeline.append(
            {
                "timestamp": _iso_timestamp(time.time()),
                "type": event_type,
                "tone": tone,
                "title": title,
                "detail": detail,
                "data": data or {},
            }
        )


def normalize_route(path: str) -> str:
    clean = str(path or "/").split("?", 1)[0] or "/"
    if clean.startswith("/v1/routing-decision/"):
        return "/v1/routing-decision/:id"
    if clean.startswith("/v1/plugins/") and clean.endswith("/execute"):
        return "/v1/plugins/:id/execute"
    parts = []
    for segment in clean.split("/"):
        if not segment:
            continue
        parts.append(":id" if _DYNAMIC_SEGMENT_RE.match(segment) else segment)
    return "/" + "/".join(parts) if parts else "/"


def _route_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    count = int(row.get("count") or 0)
    errors = int(row.get("error_count") or 0)
    hits = int(row.get("cache_hits") or 0)
    misses = int(row.get("cache_misses") or 0)
    cache_total = hits + misses
    return {
        "path": row.get("path") or "",
        "count": count,
        "error_count": errors,
        "error_rate": round(errors / count, 4) if count else 0.0,
        "cache_hit_rate": round(hits / cache_total, 4) if cache_total else 0.0,
        "average_latency_ms": round(float(row.get("total_latency_ms") or 0.0) / count, 2) if count else 0.0,
        "ewma_latency_ms": round(float(row.get("ewma_latency_ms") or 0.0), 2),
        "max_latency_ms": round(float(row.get("max_latency_ms") or 0.0), 2),
        "last_status": int(row.get("last_status") or 0),
        "last_seen": _iso_timestamp(float(row.get("last_seen") or 0.0)),
    }


def _pressure_snapshot(telemetry: dict[str, Any], diagnostics_cache: dict[str, Any]) -> dict[str, Any]:
    latency = telemetry.get("latency_ms") if isinstance(telemetry.get("latency_ms"), dict) else {}
    ewma_latency = float(latency.get("ewma") or 0.0)
    max_latency = float(latency.get("max") or 0.0)
    in_flight = int(telemetry.get("in_flight") or 0)
    total_requests = int(telemetry.get("total_requests") or 0)
    error_rate = float(telemetry.get("error_rate") or 0.0)
    slow_count = len(telemetry.get("recent_slow_requests") or [])
    cache_total = int(diagnostics_cache.get("hits") or 0) + int(diagnostics_cache.get("misses") or 0)
    cache_hit_rate = float(diagnostics_cache.get("hit_rate") or telemetry.get("cache_hit_rate") or 0.0)
    cache_pressure = cache_total >= 8 and cache_hit_rate < 0.20 and ewma_latency >= 250
    signals = [
        {
            "id": "traffic",
            "state": "elevated" if in_flight >= 8 else "nominal",
            "value": in_flight,
            "detail": f"{in_flight} in-flight request(s), {total_requests} completed.",
        },
        {
            "id": "latency",
            "state": "hot" if ewma_latency >= 1200 else "elevated" if ewma_latency >= 750 else "nominal",
            "value": round(ewma_latency, 2),
            "detail": f"EWMA {ewma_latency:.1f} ms, max {max_latency:.1f} ms.",
        },
        {
            "id": "errors",
            "state": "hot" if error_rate >= 0.10 else "elevated" if error_rate >= 0.02 else "nominal",
            "value": round(error_rate, 4),
            "detail": f"{error_rate * 100:.1f}% non-success response rate.",
        },
        {
            "id": "cache",
            "state": "elevated" if cache_pressure else "nominal",
            "value": round(cache_hit_rate, 4),
            "detail": (
                f"{cache_hit_rate * 100:.1f}% diagnostics cache hit rate over {cache_total} lookup(s); "
                f"diagnostic EWMA {ewma_latency:.1f} ms."
            ),
        },
        {
            "id": "slow_path",
            "state": "elevated" if slow_count else "nominal",
            "value": slow_count,
            "detail": f"{slow_count} recent slow request(s) retained.",
        },
    ]
    state_order = {"nominal": 0, "elevated": 1, "hot": 2}
    state = max((signal["state"] for signal in signals), key=lambda item: state_order.get(str(item), 0))
    return {
        "object": "agent_hub.runtime_kernel.pressure",
        "state": state,
        "signals": signals,
    }


def _service_map(subsystems: list[dict[str, Any]]) -> dict[str, Any]:
    state_by_id = {
        str(row.get("id")): str(row.get("state") or "unknown")
        for row in subsystems
        if isinstance(row, dict)
    }
    labels = {
        "http_server": "HTTP Gateway",
        "security_policy": "Security Policy",
        "router": "Router",
        "provider_pool": "Provider Pool",
        "workspace_tools": "Workspace Tools",
        "routing_memory": "Routing Memory",
        "diagnostics_cache": "Diagnostics Cache",
    }
    ids = [
        "http_server",
        "security_policy",
        "router",
        "provider_pool",
        "workspace_tools",
        "routing_memory",
        "diagnostics_cache",
    ]
    nodes = [
        {
            "id": node_id,
            "label": labels[node_id],
            "state": state_by_id.get(node_id, "unknown"),
        }
        for node_id in ids
    ]
    edges = [
        {"from": "http_server", "to": "security_policy", "type": "guards"},
        {"from": "http_server", "to": "router", "type": "routes"},
        {"from": "router", "to": "provider_pool", "type": "selects"},
        {"from": "router", "to": "routing_memory", "type": "learns"},
        {"from": "router", "to": "workspace_tools", "type": "uses"},
        {"from": "http_server", "to": "diagnostics_cache", "type": "observes"},
    ]
    return {
        "object": "agent_hub.runtime_kernel.service_map",
        "nodes": nodes,
        "edges": edges,
    }


def _next_actions(
    *,
    config: Any,
    telemetry: dict[str, Any],
    subsystems: list[dict[str, Any]],
    provider_health: dict[str, dict[str, Any]],
    diagnostics_cache: dict[str, Any],
    pressure: dict[str, Any],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    by_id = {str(row.get("id")): row for row in subsystems if isinstance(row, dict)}
    router = by_id.get("router", {})
    providers = by_id.get("provider_pool", {})
    security = by_id.get("security_policy", {})
    memory = by_id.get("routing_memory", {})
    workspace_tools = by_id.get("workspace_tools", {})
    provider_metrics = providers.get("metrics") if isinstance(providers.get("metrics"), dict) else {}
    available = int(provider_metrics.get("available") or 0)
    enabled = int(provider_metrics.get("enabled") or 0)
    degraded = int(provider_metrics.get("degraded") or 0)
    route_rows = telemetry.get("routes") if isinstance(telemetry.get("routes"), list) else []
    slow_count = len(telemetry.get("recent_slow_requests") or [])
    latency = telemetry.get("latency_ms") if isinstance(telemetry.get("latency_ms"), dict) else {}
    ewma_latency = float(latency.get("ewma") or 0.0)
    error_rate = float(telemetry.get("error_rate") or 0.0)
    cache_total = int(diagnostics_cache.get("hits") or 0) + int(diagnostics_cache.get("misses") or 0)
    cache_hit_rate = float(diagnostics_cache.get("hit_rate") or telemetry.get("cache_hit_rate") or 0.0)

    if security.get("state") == "critical":
        actions.append(
            _action(
                "secure_public_bind",
                "critical",
                "Add API auth before public binding",
                "The backend is reachable outside localhost without API authentication.",
                command="Set api_auth_token or api_auth_token_env, then restart Agent Hub.",
                path="/dashboard/production-check",
                source="security_policy",
            )
        )
    if router.get("state") == "needs_setup":
        actions.append(
            _action(
                "configure_routes",
                "critical",
                "Configure at least one enabled route",
                "No usable route/default_route is ready, so agent requests cannot be routed reliably.",
                command="python -m agent_hub init",
                path="/dashboard/readiness",
                source="router",
            )
        )
    if enabled <= 0 or providers.get("state") == "needs_setup":
        actions.append(
            _action(
                "configure_providers",
                "critical",
                "Add a provider or local model",
                "Agent Hub has no enabled providers to route work to.",
                command="python -m agent_hub presets",
                path="/dashboard/provider-health",
                source="provider_pool",
            )
        )
    elif available <= 0 or providers.get("state") == "degraded":
        actions.append(
            _action(
                "repair_provider_pool",
                "critical",
                "Repair provider availability",
                f"0/{enabled} enabled provider(s) are currently route-ready.",
                command="python -m agent_hub providers",
                path="/dashboard/provider-health",
                source="provider_pool",
            )
        )
    elif degraded:
        actions.append(
            _action(
                "review_degraded_providers",
                "warn",
                "Review degraded provider health",
                f"{degraded} provider(s) are degraded, but {available}/{enabled} enabled provider(s) can still route.",
                path="/dashboard/provider-health",
                source="provider_pool",
            )
        )

    if error_rate >= 0.02:
        worst = _worst_route(route_rows, key="error_rate")
        actions.append(
            _action(
                "investigate_error_rate",
                "warn",
                "Investigate elevated HTTP errors",
                f"Kernel error rate is {error_rate * 100:.1f}%."
                + (f" Worst route: {worst.get('path')}." if worst else ""),
                path="/dashboard/kernel",
                source="request_telemetry",
            )
        )
    if ewma_latency >= 750:
        worst = _worst_route(route_rows, key="ewma_latency_ms")
        actions.append(
            _action(
                "investigate_latency",
                "warn",
                "Investigate slow diagnostics",
                f"Request latency EWMA is {ewma_latency:.1f} ms."
                + (f" Slowest route: {worst.get('path')}." if worst else ""),
                path="/dashboard/kernel",
                source="request_telemetry",
            )
        )
    if slow_count:
        actions.append(
            _action(
                "review_slow_requests",
                "warn",
                "Review slow request timeline",
                f"{slow_count} recent request(s) crossed the slow-path threshold.",
                path="/dashboard/kernel",
                source="request_telemetry",
            )
        )
    if cache_total >= 8 and cache_hit_rate < 0.20 and ewma_latency >= 250:
        actions.append(
            _action(
                "tune_diagnostics_cache",
                "info",
                "Tune diagnostics refresh cadence",
                "Diagnostics cache reuse is low and diagnostics are no longer cheap.",
                path="/dashboard/kernel",
                source="diagnostics_cache",
            )
        )
    if memory.get("state") == "disabled":
        actions.append(
            _action(
                "enable_routing_memory",
                "info",
                "Enable routing memory for better model choices",
                "Routing memory is off, so Agent Hub cannot learn from local outcomes.",
                command="Set routing_memory_enabled=true.",
                path="/dashboard/learning",
                source="routing_memory",
            )
        )
    if workspace_tools.get("state") == "disabled" and bool(getattr(config, "tool_loop_enabled", True)):
        actions.append(
            _action(
                "workspace_shell_optional",
                "info",
                "Workspace shell tools are locked down",
                "This is safe by default. Enable shell tools only when you want Agent Hub to run local commands.",
                command="Set allow_shell_tools=true and shell_command_policy=ask.",
                path="/dashboard/tools",
                source="workspace_tools",
            )
        )

    if not actions:
        actions.append(
            _action(
                "ready_to_use",
                "ok",
                "Ready to use",
                "No blocking runtime issues were found. Start with a real task, Route Lab, or the model leaderboard.",
                path="/dashboard/routing-intelligence",
                source="runtime_kernel",
            )
        )
    actions.sort(key=lambda row: {"critical": 0, "warn": 1, "info": 2, "ok": 3}.get(str(row["severity"]), 4))
    return actions[:6]


def _action(
    action_id: str,
    severity: str,
    title: str,
    detail: str,
    *,
    command: str = "",
    path: str = "",
    source: str = "",
) -> dict[str, Any]:
    return {
        "id": action_id,
        "severity": severity,
        "title": title,
        "detail": detail,
        "command": command,
        "path": path,
        "source": source,
    }


def _worst_route(routes: list[Any], *, key: str) -> dict[str, Any]:
    rows = [row for row in routes if isinstance(row, dict)]
    if not rows:
        return {}
    return max(rows, key=lambda row: float(row.get(key) or 0.0))


def _provider_health(router: Any) -> tuple[dict[str, dict[str, Any]], str]:
    try:
        health = router.health_snapshot()
    except Exception as exc:  # pragma: no cover - defensive diagnostics path
        return {}, str(exc)
    return health if isinstance(health, dict) else {}, ""


def _routing_memory(router: Any) -> tuple[dict[str, Any], str]:
    try:
        memory = router.routing_memory.stats()
    except Exception as exc:  # pragma: no cover - defensive diagnostics path
        return {}, str(exc)
    return memory if isinstance(memory, dict) else {}, ""


def _subsystems(
    *,
    config: Any,
    provider_health: dict[str, dict[str, Any]],
    provider_error: str,
    diagnostics_cache: dict[str, Any],
    routing_memory: dict[str, Any],
    routing_memory_error: str,
) -> list[dict[str, Any]]:
    agents = getattr(config, "agents", {}) if getattr(config, "agents", None) is not None else {}
    routes = getattr(config, "routes", []) if getattr(config, "routes", None) is not None else []
    default_route = getattr(config, "default_route", []) if getattr(config, "default_route", None) is not None else []
    enabled_agents = [
        name
        for name, agent in agents.items()
        if bool(getattr(agent, "enabled", True))
    ]
    available = sum(1 for row in provider_health.values() if bool(row.get("available")))
    degraded = sum(1 for row in provider_health.values() if bool(row.get("degraded")))
    tool_capable = sum(1 for row in provider_health.values() if bool(row.get("supports_tools") or row.get("tool_support")))
    public_bind = _public_bind_host(getattr(config, "host", "127.0.0.1"))
    auth_configured = bool(getattr(config, "api_auth_token", None) or getattr(config, "api_auth_token_env", None))
    approval_mode = str(getattr(config, "approval_mode", "safe") or "safe")
    shell_policy = str(getattr(config, "shell_command_policy", "deny") or "deny")
    allow_shell = bool(getattr(config, "allow_shell_tools", False))

    router_state = "ready" if enabled_agents and (default_route or routes) else "needs_setup"
    provider_state = "ready"
    if provider_error:
        provider_state = "degraded"
    elif not enabled_agents:
        provider_state = "needs_setup"
    elif available <= 0:
        provider_state = "degraded"
    elif degraded:
        provider_state = "watching"

    security_state = "ready"
    security_detail = f"approval={approval_mode}, provider_privacy={bool(getattr(config, 'provider_privacy_mode_enabled', True))}"
    if public_bind and not auth_configured:
        security_state = "critical"
        security_detail = "public bind without API auth"
    elif approval_mode == "auto":
        security_state = "watching"

    shell_state = "disabled"
    if allow_shell:
        shell_state = "ready" if shell_policy in {"ask", "auto"} else "guarded"
    elif shell_policy != "deny":
        shell_state = "guarded"

    memory_enabled = bool(routing_memory.get("enabled", getattr(config, "routing_memory_enabled", True)))
    memory_state = "ready" if memory_enabled else "disabled"
    if routing_memory_error:
        memory_state = "degraded"

    return [
        _subsystem(
            "http_server",
            "ready",
            "Threaded HTTP server is accepting requests.",
            {"host": getattr(config, "host", "127.0.0.1"), "port": getattr(config, "port", 8787)},
        ),
        _subsystem(
            "router",
            router_state,
            f"{len(enabled_agents)} enabled agent(s), {len(default_route)} default route candidate(s), {len(routes)} named route(s).",
            {"enabled_agents": len(enabled_agents), "default_route": len(default_route), "routes": len(routes)},
        ),
        _subsystem(
            "provider_pool",
            provider_state,
            provider_error or f"{available}/{len(enabled_agents)} enabled provider(s) currently route-ready.",
            {
                "available": available,
                "enabled": len(enabled_agents),
                "degraded": degraded,
                "tool_capable": tool_capable,
            },
        ),
        _subsystem(
            "diagnostics_cache",
            "ready" if diagnostics_cache.get("enabled") else "disabled",
            f"{diagnostics_cache.get('entries', 0)} cached diagnostic payload(s), hit rate {diagnostics_cache.get('hit_rate', 0.0)}.",
            diagnostics_cache,
        ),
        _subsystem(
            "security_policy",
            security_state,
            security_detail,
            {
                "approval_mode": approval_mode,
                "public_bind": public_bind,
                "api_auth_configured": auth_configured,
                "secret_scanning_enabled": bool(getattr(config, "secret_scanning_enabled", True)),
                "provider_privacy_mode_enabled": bool(getattr(config, "provider_privacy_mode_enabled", True)),
            },
        ),
        _subsystem(
            "workspace_tools",
            shell_state,
            f"shell_tools={allow_shell}, shell_policy={shell_policy}",
            {"allow_shell_tools": allow_shell, "shell_command_policy": shell_policy},
        ),
        _subsystem(
            "routing_memory",
            memory_state,
            routing_memory_error or _routing_memory_detail(routing_memory),
            {
                "enabled": memory_enabled,
                "sample_count": routing_memory.get(
                    "sample_count",
                    routing_memory.get("total_records", routing_memory.get("record_count", 0)),
                ),
                "retention_days": getattr(config, "routing_memory_retention_days", 30),
            },
        ),
    ]


def _subsystem(
    subsystem_id: str,
    state: str,
    detail: str,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": subsystem_id,
        "state": state,
        "detail": detail,
        "metrics": metrics or {},
    }


def _routing_memory_detail(memory: dict[str, Any]) -> str:
    summary = memory.get("summary") if isinstance(memory.get("summary"), dict) else {}
    data_state = str(summary.get("data_state") or memory.get("state") or "local outcome memory")
    total = summary.get("total_records", memory.get("total_records", memory.get("record_count", 0)))
    return f"{data_state}; {total} retained outcome record(s)."


def _operational_score(
    *,
    config: Any,
    telemetry: dict[str, Any],
    subsystems: list[dict[str, Any]],
    provider_health: dict[str, dict[str, Any]],
    diagnostics_cache: dict[str, Any],
) -> int:
    score = 100.0
    states = {str(row.get("id")): str(row.get("state")) for row in subsystems}
    if states.get("router") == "needs_setup":
        score -= 25
    if states.get("provider_pool") == "needs_setup":
        score -= 25
    elif states.get("provider_pool") == "degraded":
        score -= 14
    if states.get("security_policy") == "critical":
        score -= 30
    elif states.get("security_policy") == "watching":
        score -= 5
    if states.get("routing_memory") == "disabled":
        score -= 4
    if states.get("workspace_tools") == "disabled" and bool(getattr(config, "tool_loop_enabled", True)):
        score -= 2

    error_rate = float(telemetry.get("error_rate") or 0.0)
    if error_rate > 0.02:
        score -= min(20.0, error_rate * 100)
    ewma_latency = float((telemetry.get("latency_ms") or {}).get("ewma") or 0.0)
    if ewma_latency > 1200:
        score -= 10
    elif ewma_latency > 750:
        score -= 5
    slow_count = len(telemetry.get("recent_slow_requests") or [])
    score -= min(8, slow_count * 0.8)

    cache_total = int(diagnostics_cache.get("hits") or 0) + int(diagnostics_cache.get("misses") or 0)
    if cache_total >= 8 and float(diagnostics_cache.get("hit_rate") or 0.0) < 0.2 and ewma_latency > 250:
        score -= 3
    if provider_health and not any(bool(row.get("supports_tools") or row.get("tool_support")) for row in provider_health.values()):
        score -= 2
    return max(0, min(100, int(round(score))))


def _kernel_state(score: int, subsystems: list[dict[str, Any]]) -> str:
    if any(row.get("state") == "critical" for row in subsystems):
        return "critical"
    if score >= 92:
        return "production_ready"
    if score >= 78:
        return "ready"
    if score >= 55:
        return "degraded"
    return "needs_attention"


def _public_bind_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    return normalized not in {"", "127.0.0.1", "localhost", "::1"}


def _iso_timestamp(value: float) -> str:
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
