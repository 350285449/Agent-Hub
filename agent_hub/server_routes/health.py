from __future__ import annotations

from ..measurement import usage_ledger_summary
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
