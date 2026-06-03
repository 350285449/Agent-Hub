from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..api.compatibility import (
    compatibility_endpoint,
    debug_api_shape,
    request_from_header_payload,
    response_headers,
    response_permission_status,
    response_token_metadata,
    safe_header_value,
    stream_response_headers,
)
from ..context import request_context_diagnostics


def handle_post(handler: object, path: str, payload: dict[str, Any]) -> bool:
    from .. import server as server_module

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

def _response_headers(response: Any, router: AgentRouter) -> dict[str, str]:
    return response_headers(response, router)

def _stream_response_headers(stream: Any, router: AgentRouter) -> dict[str, str]:
    return stream_response_headers(stream, router)

def _recover_native_stream(
    server: AgentHubHTTPServer,
    stream: Any,
    *,
    replay_required: bool = True,
    emitted_text: str = "",
) -> Any | None:
    policy = str(getattr(server.config, "native_stream_failure_policy", "recover") or "recover")
    routing = getattr(server.config, "routing", {}) or {}
    if policy == "recover":
        policy = "fallback_provider"
    if policy == "terminate":
        return None
    if replay_required and not str(emitted_text or "").strip() and not _stream_replay_safe(getattr(stream, "request", None)):
        return None
    if policy == "retry_same_provider":
        request = _stream_recovery_request(
            stream.request,
            recovery="retry_same_provider",
            emitted_text=emitted_text,
        )
        return server.router.native_stream_for_agent(request, stream.agent.name)
    if policy == "fallback_provider":
        server.router.cooldown_agent(stream.agent.name, getattr(stream.agent, "cooldown_seconds", 1.0))
        request = _stream_recovery_request(
            stream.request,
            recovery="fallback_provider",
            emitted_text=emitted_text,
        )
        return server.router.native_stream(request)
    return None

def _stream_replay_safe(request: Any) -> bool:
    raw = request.raw if request is not None and isinstance(getattr(request, "raw", None), dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    for value in (
        hub.get("stream_replay_safe"),
        hub.get("replay_safe"),
        raw.get("stream_replay_safe"),
        raw.get("replay_safe"),
    ):
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False

def _stream_recovery_request(request: Any, *, recovery: str, emitted_text: str = "") -> Any:
    raw = dict(request.raw or {})
    hub = dict(raw.get("agent_hub") or {})
    hub["stream_recovery_attempt"] = recovery
    raw["agent_hub"] = hub
    partial = str(emitted_text or "").strip()
    if not partial:
        return replace(request, raw=raw, record_session=False)
    messages = [
        *[dict(message) for message in request.messages],
        {
            "role": "assistant",
            "content": partial,
            "agent_hub_partial_response": True,
        },
        {
            "role": "user",
            "content": (
                "Continue from the exact point where the stream stopped. "
                "Do not repeat completed text. Preserve the requested format, JSON/schema "
                "requirements, tool state, and task context."
            ),
            "agent_hub_stream_recovery_instruction": True,
        },
    ]
    return replace(request, messages=messages, raw=raw, record_session=False)

def _trim_stream_overlap(prefix: str, suffix: str) -> str:
    if not prefix or not suffix:
        return suffix
    max_overlap = min(len(prefix), len(suffix), 4000)
    for size in range(max_overlap, 0, -1):
        if prefix[-size:] == suffix[:size]:
            return suffix[size:]
    return suffix

def _safe_header_value(value: Any) -> str:
    return safe_header_value(value)

def _safe_write(handler: AgentHubHandler, text: str) -> bool:
    try:
        handler.wfile.write(text.encode("utf-8"))
        return True
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        return False

def _safe_flush(handler: AgentHubHandler) -> None:
    try:
        handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        return

def _response_token_metadata(response: Any) -> dict[str, Any]:
    return response_token_metadata(response)

def _response_permission_status(response: Any) -> str:
    return response_permission_status(response)

def _wants_agent_mode(payload: dict[str, Any], default: bool = False) -> bool:
    hub_options = payload.get("agent_hub")
    if isinstance(hub_options, dict) and "agent_mode" in hub_options:
        return bool(hub_options["agent_mode"])
    if "agent_mode" in payload:
        return bool(payload["agent_mode"])
    mode = payload.get("mode")
    if isinstance(mode, str) and mode.lower() == "agent":
        return True
    return default

def _payload_mode(payload: dict[str, Any], default_agent: bool = False) -> str:
    hub_options = payload.get("agent_hub")
    if isinstance(hub_options, dict):
        mode = hub_options.get("mode")
        if isinstance(mode, str) and mode.lower() in {"agent", "group-agent", "team-agent", "auto"}:
            return "group-agent" if mode.lower() == "team-agent" else mode.lower()
        if bool(hub_options.get("agent_mode")):
            return "agent"
    mode = payload.get("mode")
    if isinstance(mode, str) and mode.lower() in {"agent", "group-agent", "team-agent", "auto"}:
        return "group-agent" if mode.lower() == "team-agent" else mode.lower()
    if bool(payload.get("agent_mode")):
        return "agent"
    return "agent" if default_agent else "route"

def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, maximum))

__all__ = [
    '_response_headers',
    '_stream_response_headers',
    '_recover_native_stream',
    '_stream_replay_safe',
    '_stream_recovery_request',
    '_trim_stream_overlap',
    '_safe_header_value',
    '_safe_write',
    '_safe_flush',
    '_response_token_metadata',
    '_response_permission_status',
    '_wants_agent_mode',
    '_payload_mode',
    '_positive_int',
]
