from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

from ..config import HubConfig, normalize_provider
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
from ..tool_compatibility import tool_compatibility_mode


API_SHAPES = {"native", "openai-chat", "openai-responses", "anthropic-messages"}
ROUTE_MODEL_ALIASES = {
    "agent-hub": "cloud-agent",
    "agent-hub-cloud": "cloud-agent",
    "agent-hub-coding": "coding",
    "agent-hub-tools": "coding",
    "agent-hub-agent": "coding",
    "agent-hub-auto": "cloud-agent",
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


def error_response_for_shape(
    error: dict[str, Any],
    response_shape: str,
    *,
    agent_hub: dict[str, Any] | None = None,
    failover: list[dict[str, Any]] | None = None,
    include_routing_details: bool = False,
) -> dict[str, Any]:
    public_error = {
        "message": str(error.get("message") or "Agent Hub request failed."),
        "type": str(error.get("type") or "agent_hub_error"),
    }
    if error.get("code") is not None:
        public_error["code"] = error.get("code")
    if error.get("param") is not None:
        public_error["param"] = error.get("param")
    if response_shape == "anthropic-messages":
        body: dict[str, Any] = {
            "type": "error",
            "error": {
                "type": public_error["type"],
                "message": public_error["message"],
            },
        }
    else:
        body = {"error": dict(error)}
    if include_routing_details:
        if agent_hub:
            body["agent_hub"] = agent_hub
        if failover:
            body["failover"] = failover
    return body


def openai_chat_sse_frames(
    response: HubResponse,
    *,
    include_routing_details: bool = False,
) -> list[str]:
    return [
        sse_data_frame(event)
        for event in openai_stream_events(
            response,
            include_routing_details=include_routing_details,
        )
    ]


def anthropic_sse_frames(
    response: HubResponse,
    *,
    include_routing_details: bool = False,
) -> list[str]:
    frames: list[str] = []
    for name, event in anthropic_stream_events(
        response,
        include_routing_details=include_routing_details,
    ):
        frames.append(sse_named_event_frame(name, event))
    return frames


def openai_response_sse_frames(
    response: HubResponse,
    *,
    include_routing_details: bool = False,
) -> list[str]:
    return [
        sse_data_frame(event)
        for event in openai_response_stream_events(
            response,
            include_routing_details=include_routing_details,
        )
    ]


def sse_data_frame(data: dict[str, Any] | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"data: {payload}\n\n"


def sse_named_event_frame(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\n" f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def response_headers(response: Any, router: Any) -> dict[str, str]:
    health = router.health_snapshot().get(response.agent, {})
    fallback_models = [
        event.model
        for event in response.failover
        if event and event.model
    ]
    fallback_chain = ",".join(fallback_models)
    token_metadata = response_token_metadata(response)
    permission_status = response_permission_status(response)
    safe_mode = "on" if router.config.approval_mode == "safe" else "off"
    context_warning = (
        "suspiciously_empty"
        if token_metadata.get("suspiciously_empty")
        else ""
    )
    values = {
        "X-Agent-Hub-Agent": response.agent,
        "X-Agent-Hub-Provider": response.provider,
        "X-Agent-Hub-Model": response.model,
        "X-Agent-Hub-Active-Model": response.model,
        "X-Agent-Hub-Requests-Remaining": health.get("requests_remaining"),
        "X-Agent-Hub-Tokens-Remaining": health.get("tokens_remaining"),
        "X-Agent-Hub-Credits-Remaining": health.get("credits_remaining"),
        "X-Agent-Hub-Quota-Remaining": health.get("quota_remaining"),
        "X-Agent-Hub-Reset-At": health.get("rate_limit_reset_at"),
        "X-Agent-Hub-Cooldown-Until": health.get("cooldown_until"),
        "X-Agent-Hub-Fallback-Models": fallback_chain,
        "X-AgentHub-Provider": response.provider,
        "X-AgentHub-Model": response.model,
        "X-AgentHub-Fallback": fallback_chain,
        "X-AgentHub-Tokens-Saved": token_metadata.get("estimated_tokens_saved"),
        "X-AgentHub-Requests-Remaining": health.get("requests_remaining"),
        "X-AgentHub-Permission-Status": permission_status,
        "X-AgentHub-Safe-Mode": safe_mode,
        "X-AgentHub-Context-Warning": context_warning,
    }
    return {
        name: safe_header_value(value)
        for name, value in values.items()
        if safe_header_value(value)
    }


def stream_response_headers(stream: Any, router: Any) -> dict[str, str]:
    health = router.health_snapshot().get(stream.agent.name, {})
    fallback_models = [
        event.model
        for event in stream.failover
        if event and event.model
    ]
    values = {
        "X-Agent-Hub-Agent": stream.agent.name,
        "X-Agent-Hub-Provider": stream.agent.provider,
        "X-Agent-Hub-Model": stream.model,
        "X-Agent-Hub-Active-Model": stream.model,
        "X-Agent-Hub-Provider-Score": health.get("score"),
        "X-Agent-Hub-Fallback-Models": ",".join(fallback_models),
        "X-AgentHub-Provider": stream.agent.provider,
        "X-AgentHub-Model": stream.model,
        "X-AgentHub-Fallback": ",".join(fallback_models),
    }
    return {
        name: safe_header_value(value)
        for name, value in values.items()
        if safe_header_value(value)
    }


def safe_header_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:1000]


def response_token_metadata(response: Any) -> dict[str, Any]:
    raw = response.raw if isinstance(getattr(response, "raw", None), dict) else {}
    metadata = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    context_usage = metadata.get("context_usage") if isinstance(metadata, dict) else None
    if isinstance(context_usage, dict):
        return context_usage
    token_budget = metadata.get("token_budget") if isinstance(metadata, dict) else None
    return token_budget if isinstance(token_budget, dict) else {}


def response_permission_status(response: Any) -> str:
    if any(event.error_type == "permission_denied" for event in getattr(response, "failover", [])):
        return "denied"
    if any(event.error_type == "permission_required" for event in getattr(response, "failover", [])):
        return "required"
    raw = response.raw if isinstance(getattr(response, "raw", None), dict) else {}
    metadata = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    steps = metadata.get("steps") if isinstance(metadata, dict) else []
    if isinstance(steps, list):
        for step in steps:
            result = step.get("result") if isinstance(step, dict) and isinstance(step.get("result"), dict) else {}
            if result.get("approval_required"):
                return "required"
            if result.get("permission_denied"):
                return "denied"
    return "allowed"


def available_model_ids(config: HubConfig, router: Any) -> list[str]:
    ids: list[str] = []
    for row in model_rows(config, router):
        metadata = row.get("agent_hub") if isinstance(row, dict) else None
        if isinstance(metadata, dict) and metadata.get("available") is False:
            continue
        model_id = row.get("id") if isinstance(row, dict) else None
        if isinstance(model_id, str) and model_id not in ids:
            ids.append(model_id)
    return ids


def openai_model_rows(
    config: HubConfig,
    router: Any,
    *,
    include_routing_details: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in model_rows(config, router):
        metadata = row.get("agent_hub") if isinstance(row, dict) else None
        if isinstance(metadata, dict) and metadata.get("available") is False:
            continue
        public_row = {
            "id": row["id"],
            "object": "model",
            "created": row.get("created", 0),
            "owned_by": row.get("owned_by", "agent-hub"),
        }
        if include_routing_details and isinstance(metadata, dict):
            public_row["agent_hub"] = metadata
        rows.append(public_row)
    return rows


def model_rows(config: HubConfig, router: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    health = router.health_snapshot()
    for model_id, route_name in ROUTE_MODEL_ALIASES.items():
        if route_name not in {route.name for route in config.routes}:
            continue
        recommendation = router.recommend(
            HubRequest(
                session_id="models",
                route=route_name,
                messages=[{"role": "user", "content": "select an agent model"}],
                record_session=False,
            ),
            limit=1,
            needs_tools=route_name in {"coding", "local-agent"},
        )
        row = {
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": "agent-hub",
            "agent_hub": {
                "type": "route",
                "route": route_name,
                "recommended_agent": recommendation[0]["agent"] if recommendation else None,
                "recommended_model": recommendation[0]["model"] if recommendation else None,
                "available": bool(recommendation)
                and route_has_visible_agent(config, route_name),
                "recommended_health": (
                    health.get(recommendation[0]["agent"], {}) if recommendation else {}
                ),
            },
        }
        rows.append(row)
        seen.add(model_id)

    for route in config.routes:
        if route.name in seen:
            continue
        rows.append(
            {
                "id": route.name,
                "object": "model",
                "created": 0,
                "owned_by": "agent-hub",
                "agent_hub": {
                    "type": "route",
                    "route": route.name,
                    "available": route_has_visible_agent(config, route.name),
                },
            }
        )
        seen.add(route.name)

    for agent in config.agents.values():
        if not agent_visible_in_models(config, agent):
            continue
        for model_id in (f"agent:{agent.name}", agent.name, agent.model):
            if model_id in seen:
                continue
            rows.append(
                {
                    "id": model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "agent-hub" if model_id.startswith("agent:") else agent.provider,
                    "agent_hub": {
                        "type": "agent_alias" if model_id.startswith("agent:") else "agent",
                        "agent": agent.name,
                        "provider_type": agent.provider_type,
                        "free": agent.free,
                        "context_window": agent.context_window,
                        "coding_score": agent.coding_score,
                        "reasoning_score": agent.reasoning_score,
                        "speed_score": agent.speed_score,
                        "supports_tools": bool(agent.supports_tools or agent.supports_function_calling),
                        "effective_supports_tools": tool_compatibility_mode(config, agent)
                        in {"native", "emulated"},
                        "tool_compatibility": tool_compatibility_mode(config, agent),
                        "health": health.get(agent.name, {}),
                    },
                }
            )
            seen.add(model_id)
    return rows


def route_has_visible_agent(config: HubConfig, route_name: str) -> bool:
    route = next((item for item in config.routes if item.name == route_name), None)
    if route is None:
        return False
    return any(
        agent_visible_in_models(config, config.agents[name])
        for name in route.agents
        if name in config.agents
    )


def agent_visible_in_models(config: HubConfig, agent: Any) -> bool:
    if not getattr(agent, "enabled", False):
        return False
    if normalize_provider(getattr(agent, "provider", "")) == "echo":
        return bool(config.debug_echo_enabled)
    return True


def apply_model_routing(config: HubConfig, request: HubRequest) -> None:
    if not isinstance(request.raw, dict):
        return
    model = request.raw.get("model")
    if not isinstance(model, str) or not model.strip():
        return
    normalized = model.strip().lower()
    if normalized == "agent-hub-auto":
        request.route = request.route or ROUTE_MODEL_ALIASES[normalized]
        raw = request.raw if isinstance(request.raw, dict) else {}
        hub = dict(raw.get("agent_hub")) if isinstance(raw.get("agent_hub"), dict) else {}
        hub["mode"] = "auto"
        raw["agent_hub"] = hub
        request.raw = raw
        return
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
    metadata = dict(request.metadata) if isinstance(request.metadata, dict) else {}
    raw = dict(request.raw) if isinstance(request.raw, dict) else {}
    hub = dict(raw.get("agent_hub")) if isinstance(raw.get("agent_hub"), dict) else {}
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
    "agent_visible_in_models",
    "anthropic_sse_frames",
    "apply_model_routing",
    "attach_internal_client_metadata",
    "available_model_ids",
    "compatibility_endpoint",
    "compatibility_label",
    "debug_api_shape",
    "error_response_for_shape",
    "has_session_key",
    "known_client_from_user_agent",
    "model_lookup_error",
    "model_rows",
    "openai_chat_sse_frames",
    "openai_model_rows",
    "openai_response_sse_frames",
    "payload_with_header_metadata",
    "request_from_compat_payload",
    "request_from_header_payload",
    "response_headers",
    "response_permission_status",
    "response_token_metadata",
    "response_for_shape",
    "route_has_visible_agent",
    "safe_header_value",
    "sse_data_frame",
    "sse_named_event_frame",
    "stream_response_headers",
    "anthropic_stream_events",
    "openai_response_stream_events",
    "openai_stream_events",
]
