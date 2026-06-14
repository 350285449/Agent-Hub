from __future__ import annotations

from ..measurement import metrics_savings, metrics_summary, usage_ledger_summary
from ..observability import metrics_snapshot, permission_snapshot, usage_snapshot
from ..security.secrets import redact_secrets


def handle_get(handler: object, path: str) -> bool:
    from .. import server as server_module

    if path == "/v1/readiness":
        handler._send_cached_diagnostics_json(
            "GET /v1/readiness",
            lambda: handler.server.diagnostics_service.readiness_body(handler.server.router),
        )
        return True
    if path == "/v1/production-check":
        handler._send_cached_diagnostics_json(
            "GET /v1/production-check",
            lambda: handler.server.diagnostics_service.production_check_body(handler.server.router),
        )
        return True
    if path == "/v1/feature-scorecard":
        handler._send_cached_diagnostics_json(
            "GET /v1/feature-scorecard",
            lambda: handler.server.diagnostics_service.feature_scorecard_body(handler.server.router),
        )
        return True
    if path == "/v1/system-health":
        handler._send_cached_diagnostics_json(
            "GET /v1/system-health",
            lambda: _system_health_body(handler),
        )
        return True
    if path == "/v1/limits":
        handler._send_cached_diagnostics_json(
            "GET /v1/limits",
            lambda: handler.server.diagnostics_service.limits_body(handler.server.router),
        )
        return True
    if path == "/v1/usage":
        handler._send_cached_diagnostics_json(
            "GET /v1/usage",
            lambda: _usage_body(handler),
        )
        return True
    if path == "/api/metrics/summary":
        handler._send_cached_diagnostics_json(
            "GET /api/metrics/summary",
            lambda: metrics_summary(handler.server.config),
        )
        return True
    if path == "/api/metrics/savings":
        handler._send_cached_diagnostics_json(
            "GET /api/metrics/savings",
            lambda: metrics_savings(handler.server.config),
        )
        return True
    if path == "/health":
        handler._send_cached_json(
            "GET /health",
            lambda: _health_body(handler, server_module),
        )
        return True
    if path == "/limits":
        handler._send_cached_json(
            "GET /limits",
            lambda: handler.server.diagnostics_service.limits_body(handler.server.router),
        )
        return True
    if path == "/usage":
        handler._send_cached_json(
            "GET /usage",
            lambda: _usage_body(handler),
            redact=True,
        )
        return True
    if path == "/permissions":
        handler._send_cached_json(
            "GET /permissions",
            lambda: permission_snapshot(
                handler.server.config.state_dir,
                approval_mode=handler.server.config.approval_mode,
                safe_mode=handler.server.config.approval_mode == "safe",
            ),
            redact=True,
        )
        return True
    if path == "/metrics":
        handler._send_cached_json(
            "GET /metrics",
            lambda: _metrics_body(handler),
            redact=True,
        )
        return True
    if path == "/debug/request":
        handler._send_json(
            redact_secrets(
                {
                    "object": "agent_hub.debug.request",
                    "recent": list(reversed(handler.server.debug_requests[-20:])),
                }
            )
        )
        return True
    if path == "/debug/context":
        handler._send_json(
            redact_secrets(
                {
                    "object": "agent_hub.debug.context",
                    "summary": server_module._debug_context_summary(handler.server),
                    "recent": list(reversed(handler.server.debug_requests[-20:])),
                }
            )
        )
        return True
    return False


def _usage_body(handler: object) -> dict:
    body = usage_snapshot(
        handler.server.config.state_dir,
        handler.server.router.health_snapshot(include_history=True),
    )
    body["usage_ledger"] = usage_ledger_summary(handler.server.config)
    return body


def _metrics_body(handler: object) -> dict:
    metrics = metrics_snapshot(
        handler.server.config.state_dir,
        handler.server.router.health_snapshot(include_history=True),
    )
    metrics["optimization"] = handler.server.adaptive_service.optimization_summary()
    return metrics


def _system_health_body(handler: object) -> dict:
    config = handler.server.config
    provider_health = handler.server.router.health_snapshot(include_history=False)
    agents = getattr(config, "agents", {}) or {}
    enabled = [agent for agent in agents.values() if getattr(agent, "enabled", True)]
    openai = any(str(getattr(agent, "provider", "")).lower() == "openai" for agent in enabled)
    anthropic = any(str(getattr(agent, "provider", "")).lower() == "anthropic" for agent in enabled)
    components = [
        _component("OpenAI", "healthy" if openai else "not_configured"),
        _component("Anthropic", "healthy" if anthropic else "not_configured"),
        _component("Workspace", "healthy" if getattr(config, "workspace_dir", None) else "needs_attention"),
        _component("Database", "healthy"),
    ]
    if isinstance(provider_health, dict) and provider_health:
        unhealthy = [
            name
            for name, row in provider_health.items()
            if isinstance(row, dict) and row.get("available") is False
        ]
        if unhealthy and len(unhealthy) == len(provider_health):
            components.append(_component("Providers", "needs_attention"))
        else:
            components.append(_component("Providers", "healthy"))
    return {
        "object": "agent_hub.system_health",
        "status": "healthy" if all(row["status"] in {"healthy", "not_configured"} for row in components) else "needs_attention",
        "components": components,
        "advanced_view": "/health",
        "support_bundle": "agent-hub support-bundle",
    }


def _component(name: str, status: str) -> dict:
    labels = {
        "healthy": "Healthy",
        "not_configured": "Not configured",
        "needs_attention": "Needs attention",
    }
    return {"component": name, "status": labels.get(status, status)}


def _health_body(handler: object, server_module: object) -> dict:
    body = handler.server.diagnostics_service.backend_health_body(
        handler.server.router,
        context_diagnostics=server_module._debug_context_summary(handler.server),
    )
    body["backend_efficiency"] = {
        "diagnostics_cache": handler.server.diagnostics_cache_stats(),
        "runtime_kernel": handler.server.runtime_kernel.efficiency_summary(),
    }
    return body
