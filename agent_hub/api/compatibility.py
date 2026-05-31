from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..config import HubConfig
from ..models import HubRequest, HubResponse
from ..payloads import (
    anthropic_message_response,
    anthropic_stream_events,
    openai_chat_response,
    openai_response_response,
    openai_response_stream_events,
    openai_stream_events,
    request_from_payload,
)


API_SHAPES = {"native", "openai-chat", "openai-responses", "anthropic-messages"}
ROUTE_MODEL_ALIASES = {
    "agent-hub": "cloud-agent",
    "agent-hub-cloud": "cloud-agent",
    "agent-hub-coding": "coding",
    "agent-hub-tools": "coding",
    "agent-hub-agent": "coding",
    "agent-hub-local": "local-agent",
    "agent-hub-research": "research",
}


@dataclass(frozen=True, slots=True)
class CompatibilityEndpoint:
    api_shape: str
    response_shape: str
    agent_mode_default: bool = False


POST_ENDPOINTS: dict[str, CompatibilityEndpoint] = {
    "/agent": CompatibilityEndpoint("native", "native", agent_mode_default=True),
    "/v1/agent": CompatibilityEndpoint("native", "native", agent_mode_default=True),
    "/api/v1/chat/completions": CompatibilityEndpoint("openai-chat", "openai-chat"),
    "/openrouter/v1/chat/completions": CompatibilityEndpoint("openai-chat", "openai-chat"),
    "/v1/route": CompatibilityEndpoint("native", "native"),
    "/v1/chat/completions": CompatibilityEndpoint("openai-chat", "openai-chat"),
    "/v1/responses": CompatibilityEndpoint("openai-responses", "openai-responses"),
    "/v1/messages": CompatibilityEndpoint("anthropic-messages", "anthropic-messages"),
}


def compatibility_endpoint(path: str) -> CompatibilityEndpoint | None:
    return POST_ENDPOINTS.get(path)


def request_from_compat_payload(
    payload: dict[str, Any],
    headers: Any,
    *,
    api_shape: str,
) -> HubRequest:
    with_metadata = payload_with_header_metadata(payload, headers)
    request = request_from_payload(with_metadata, api_shape=api_shape)
    return attach_internal_client_metadata(request, api_shape=api_shape)


def request_from_header_payload(
    payload: dict[str, Any],
    headers: Any,
    *,
    api_shape: str,
) -> HubRequest:
    return request_from_payload(payload_with_header_metadata(payload, headers), api_shape=api_shape)


def debug_api_shape(payload: dict[str, Any]) -> str:
    shape = payload.get("api_shape") or payload.get("response_shape")
    if isinstance(shape, str) and shape in API_SHAPES:
        return shape
    if "messages" in payload and ("anthropic_version" in payload or "system" in payload and "model" in payload):
        return "anthropic-messages"
    if "input" in payload:
        return "openai-responses"
    if "messages" in payload:
        return "openai-chat"
    return "native"


def response_for_shape(
    response: HubResponse,
    response_shape: str,
    *,
    include_raw: bool = False,
    include_routing_details: bool = False,
) -> dict[str, Any]:
    if response_shape == "openai-chat":
        return openai_chat_response(response, include_routing_details=include_routing_details)
    if response_shape == "anthropic-messages":
        return anthropic_message_response(response, include_routing_details=include_routing_details)
    if response_shape == "openai-responses":
        return openai_response_response(response, include_routing_details=include_routing_details)
    return response.to_native_dict(
        include_raw=include_raw,
        include_routing_details=include_routing_details,
    )


def apply_model_routing(config: HubConfig, request: HubRequest) -> None:
    if not isinstance(request.raw, dict):
        return
    model = request.raw.get("model")
    if not isinstance(model, str) or not model.strip():
        return
    normalized = model.strip().lower()
    if request.route is None and normalized in ROUTE_MODEL_ALIASES:
        request.route = ROUTE_MODEL_ALIASES[normalized]
        return
    for prefix in ("agent:", "agent-hub-agent:"):
        if request.preferred_agent is None and normalized.startswith(prefix):
            agent_name = model.strip()[len(prefix) :].strip()
            if agent_name:
                request.preferred_agent = agent_name
                return
    if request.route is None and normalized.startswith("agent-hub/"):
        route_name = normalized.split("/", 1)[1].strip()
        if route_name:
            request.route = route_name
            return
    route_names = {route.name.lower(): route.name for route in config.routes}
    if request.route is None and normalized in route_names:
        request.route = route_names[normalized]
        return
    agent_names = {agent.name.lower(): agent.name for agent in config.agents.values()}
    if request.preferred_agent is None and normalized in agent_names:
        request.preferred_agent = agent_names[normalized]
        return
    if request.preferred_agent is None:
        for agent in config.agents.values():
            if agent.model.lower() == normalized:
                request.preferred_agent = agent.name
                return


def model_lookup_error(config: HubConfig, request: HubRequest) -> dict[str, Any] | None:
    if request.api_shape not in {"openai-chat", "openai-responses", "anthropic-messages"}:
        return None
    raw = request.raw if isinstance(request.raw, dict) else {}
    model = raw.get("model")
    if not isinstance(model, str) or not model.strip():
        return None
    normalized = model.strip().lower()
    known_routes = {route.name.lower() for route in config.routes}
    known_agents = {agent.name.lower() for agent in config.agents.values()}
    known_models = {agent.model.lower() for agent in config.agents.values()}
    known_aliases = set(ROUTE_MODEL_ALIASES)
    if normalized in known_routes | known_agents | known_models | known_aliases:
        return None
    for prefix in ("agent:", "agent-hub-agent:"):
        if normalized.startswith(prefix):
            target = model.strip()[len(prefix) :].strip().lower()
            if target in known_agents:
                return None
    if normalized.startswith("agent:") or normalized.startswith("agent-hub"):
        return {
            "message": f"Model {model!r} was not found in Agent Hub routes or agents.",
            "type": "model_not_found",
            "suggested_fix": "Use /v1/models, agent-hub-coding, a configured route name, or agent:<agent-name>.",
        }
    return None


def payload_with_header_metadata(payload: dict[str, Any], headers: Any) -> dict[str, Any]:
    metadata = dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
    for header_name, key in (
        ("X-Agent-Hub-Session-ID", "session_id"),
        ("X-Session-ID", "session_id"),
        ("X-Conversation-ID", "conversation_id"),
        ("X-Thread-ID", "thread_id"),
    ):
        value = headers.get(header_name)
        if isinstance(value, str) and value.strip() and not has_session_key(metadata):
            metadata[key] = value.strip()
            break
    user_agent = headers.get("User-Agent")
    if isinstance(user_agent, str) and user_agent.strip():
        metadata.setdefault("user_agent", user_agent.strip()[:300])
        client = known_client_from_user_agent(user_agent)
        if client:
            metadata.setdefault("client", client)
            metadata.setdefault("source", client)
    for header_name, key in (
        ("X-Agent-Hub-Client", "client"),
        ("X-Cline-Version", "cline_version"),
        ("X-Continue-Version", "continue_version"),
        ("Anthropic-Version", "anthropic_version"),
        ("OpenAI-Organization", "openai_compatible_header"),
    ):
        value = headers.get(header_name)
        if isinstance(value, str) and value.strip():
            metadata.setdefault(key, value.strip()[:200])
    if not metadata:
        return payload
    copied = dict(payload)
    copied["metadata"] = metadata
    return copied


def attach_internal_client_metadata(request: HubRequest, *, api_shape: str) -> HubRequest:
    metadata = dict(request.metadata or {})
    raw = dict(request.raw or {})
    hub = dict(raw.get("agent_hub") or {})
    user_agent = str(metadata.get("user_agent") or "")
    detected_client = (
        str(metadata.get("source") or metadata.get("client") or "").strip()
        or known_client_from_user_agent(user_agent)
    )
    if api_shape == "openai-chat" and detected_client == "cline":
        metadata.setdefault("source", "cline")
        metadata.setdefault("client", "cline")
        metadata.setdefault("client_compatibility", "openai")
        metadata["health_tracking_enabled"] = True
    elif api_shape in {"openai-chat", "openai-responses", "anthropic-messages"}:
        metadata.setdefault("source", detected_client or api_shape)
        metadata.setdefault("client_compatibility", compatibility_label(api_shape))
        metadata["health_tracking_enabled"] = True
    else:
        metadata.setdefault("source", detected_client or "native")
        metadata.setdefault("client_compatibility", compatibility_label(api_shape))
        metadata.setdefault("health_tracking_enabled", True)
    hub.setdefault("source", metadata.get("source"))
    hub.setdefault("client_compatibility", metadata.get("client_compatibility"))
    hub.setdefault("health_tracking_enabled", True)
    raw["agent_hub"] = hub
    return replace(request, metadata=metadata, raw=raw)


def compatibility_label(api_shape: str) -> str:
    if api_shape in {"openai-chat", "openai-responses"}:
        return "openai"
    if api_shape == "anthropic-messages":
        return "anthropic"
    return "native"


def known_client_from_user_agent(value: str) -> str:
    lowered = value.lower()
    for marker, client in (
        ("cline", "cline"),
        ("continue", "continue"),
        ("claude-code", "claude-code"),
        ("claude_code", "claude-code"),
        ("vscode", "vscode"),
        ("visual studio code", "vscode"),
    ):
        if marker in lowered:
            return client
    return ""


def has_session_key(data: dict[str, Any]) -> bool:
    return any(
        isinstance(data.get(key), str) and str(data.get(key)).strip()
        for key in ("session_id", "conversation_id", "thread_id")
    )


__all__ = [
    "CompatibilityEndpoint",
    "ROUTE_MODEL_ALIASES",
    "apply_model_routing",
    "attach_internal_client_metadata",
    "compatibility_endpoint",
    "compatibility_label",
    "debug_api_shape",
    "has_session_key",
    "known_client_from_user_agent",
    "model_lookup_error",
    "payload_with_header_metadata",
    "request_from_compat_payload",
    "request_from_header_payload",
    "response_for_shape",
    "anthropic_stream_events",
    "openai_response_stream_events",
    "openai_stream_events",
]
