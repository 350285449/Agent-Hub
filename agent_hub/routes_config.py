from __future__ import annotations

from .middleware import request_query


def handle_get(handler: object, path: str) -> bool:
    from . import server as server_module

    if path in {"/", ""}:
        handler._send_html(handler._root_html())
        return True
    if path == "/dashboard":
        handler._send_html(handler._root_html())
        return True
    if path == "/dashboard/optimization":
        handler._send_html(server_module._optimization_dashboard_html(handler.server.adaptive_service.optimization_summary()))
        return True
    if path == "/v1/events":
        handler._send_diagnostics_json(server_module._events_body(handler.server.config))
        return True
    if path == "/v1/optimization":
        handler._send_diagnostics_json(handler.server.adaptive_service.optimization_summary())
        return True
    if path == "/v1/tools":
        handler._send_diagnostics_json(server_module._tools_body(handler.server.router))
        return True
    if path == "/v1/workflows/status":
        handler._send_diagnostics_json(server_module._workflow_status_body(handler.server.config))
        return True
    if path == "/v1/plugins":
        handler._send_diagnostics_json(handler.server.diagnostics_service.plugins_body())
        return True
    if path == "/v1/enterprise/audit":
        handler._send_diagnostics_json(handler.server.diagnostics_service.enterprise_audit_body(request_query(handler.path)))
        return True
    return False
