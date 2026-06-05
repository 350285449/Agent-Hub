from __future__ import annotations

from ..observability import metrics_snapshot, permission_snapshot, usage_snapshot
from ..security.secrets import redact_secrets


def handle_get(handler: object, path: str) -> bool:
    from .. import server as server_module

    if path == "/v1/readiness":
        handler._send_diagnostics_json(
            handler.server.diagnostics_service.readiness_body(handler.server.router)
        )
        return True
    if path == "/v1/production-check":
        handler._send_diagnostics_json(
            handler.server.diagnostics_service.production_check_body(handler.server.router)
        )
        return True
    if path == "/v1/limits":
        handler._send_diagnostics_json(handler.server.diagnostics_service.limits_body(handler.server.router))
        return True
    if path == "/v1/usage":
        handler._send_diagnostics_json(
            usage_snapshot(
                handler.server.config.state_dir,
                handler.server.router.health_snapshot(include_history=True),
            )
        )
        return True
    if path == "/health":
        handler._send_json(
            handler.server.diagnostics_service.backend_health_body(
                handler.server.router,
                context_diagnostics=server_module._debug_context_summary(handler.server),
            )
        )
        return True
    if path == "/limits":
        handler._send_json(handler.server.diagnostics_service.limits_body(handler.server.router))
        return True
    if path == "/usage":
        handler._send_json(
            redact_secrets(
                usage_snapshot(
                    handler.server.config.state_dir,
                    handler.server.router.health_snapshot(include_history=True),
                )
            )
        )
        return True
    if path == "/permissions":
        handler._send_json(
            redact_secrets(
                permission_snapshot(
                    handler.server.config.state_dir,
                    approval_mode=handler.server.config.approval_mode,
                    safe_mode=handler.server.config.approval_mode == "safe",
                )
            )
        )
        return True
    if path == "/metrics":
        metrics = metrics_snapshot(
            handler.server.config.state_dir,
            handler.server.router.health_snapshot(include_history=True),
        )
        metrics["optimization"] = handler.server.adaptive_service.optimization_summary()
        handler._send_json(redact_secrets(metrics))
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
