from __future__ import annotations

from typing import Any

from .api.compatibility import compatibility_endpoint, debug_api_shape, request_from_header_payload
from .context import request_context_diagnostics
from .middleware import request_path


def handle_post(handler: object, path: str, payload: dict[str, Any]) -> bool:
    from . import server as server_module

    if path == "/debug/request":
        api_shape = debug_api_shape(payload)
        request = request_from_header_payload(payload, handler.headers, api_shape=api_shape)
        diagnostics = request_context_diagnostics(request)
        server_module._record_debug_request(
            handler.server,
            {
                "path": path,
                "api_shape": api_shape,
                "response_shape": "debug",
                "session_id": request.session_id,
                "route": request.route,
                "preferred_agent": request.preferred_agent,
                "message_count": len(request.messages),
                "diagnostics": diagnostics,
            },
        )
        handler._send_json(
            {
                "object": "agent_hub.debug.request",
                "api_shape": api_shape,
                "session_id": request.session_id,
                "route": request.route,
                "preferred_agent": request.preferred_agent,
                "message_count": len(request.messages),
                "metadata": request.metadata,
                "diagnostics": diagnostics,
            }
        )
        return True
    if path.startswith("/v1/workflows/"):
        workflow = path.rsplit("/", 1)[-1]
        handler._handle_workflow(payload, workflow)
        return True
    if path == "/v1/auto":
        handler._handle_auto_payload(payload)
        return True
    if path == "/v1/feedback":
        handler._handle_feedback(payload)
        return True
    if path == "/v1/routing/simulate":
        handler._handle_routing_simulation(payload)
        return True
    if path in {"/v1/recommend-model", "/api/v1/recommend-model"}:
        handler._handle_recommendation(payload)
        return True
    endpoint = compatibility_endpoint(path)
    if endpoint is not None:
        handler._handle_payload(
            payload,
            api_shape=endpoint.api_shape,
            response_shape=endpoint.response_shape,
            agent_mode_default=endpoint.agent_mode_default,
        )
        return True
    return False
