from __future__ import annotations

from typing import Any

from ..config import AgentConfig
from .base import ChatRequest, ChatResponse, ProviderHealth, StreamChunk
from .descriptors import ProviderDescriptor


REQUIRED_PROVIDER_METHODS = (
    "chat",
    "stream",
    "health_check",
    "supports_streaming",
    "supports_tools",
    "supports_vision",
    "context_limit",
    "cost_estimate",
    "normalize_request",
    "normalize_response",
)

CONFORMANCE_DIMENSIONS = (
    "auth",
    "streaming",
    "tools",
    "retries",
    "errors",
    "timeouts",
    "costs",
)


def provider_conformance_report(
    provider_class: type[Any],
    descriptor: ProviderDescriptor | None = None,
    *,
    agent: AgentConfig | None = None,
) -> dict[str, Any]:
    """Return a no-network SDK conformance report for a provider adapter class."""

    descriptor = descriptor or getattr(provider_class, "descriptor", None)
    method_surface_ok = all(hasattr(provider_class, name) for name in REQUIRED_PROVIDER_METHODS)
    checks = [
        _check(
            "adapter_protocol",
            method_surface_ok,
            "Class satisfies the ProviderAdapter protocol method surface.",
        ),
        _check(
            "required_methods",
            method_surface_ok,
            "Provider adapter exposes the stable method surface.",
            missing=[name for name in REQUIRED_PROVIDER_METHODS if not hasattr(provider_class, name)],
        ),
        _check(
            "descriptor_present",
            isinstance(descriptor, ProviderDescriptor),
            "ProviderDescriptor metadata is available.",
        ),
    ]
    if isinstance(descriptor, ProviderDescriptor):
        checks.extend(_descriptor_checks(descriptor))
        checks.extend(_dimension_checks(provider_class, descriptor))
        if agent is None:
            model = descriptor.models[0] if descriptor.models else "conformance-model"
            agent = descriptor.create_agent(name="conformance-provider", model=model)
    if agent is not None:
        checks.extend(_adapter_instance_checks(provider_class, agent))
    passed = sum(1 for check in checks if check["ok"])
    return {
        "object": "agent_hub.provider_conformance",
        "provider_class": f"{provider_class.__module__}.{provider_class.__qualname__}",
        "ok": passed == len(checks),
        "rating": round((passed / max(1, len(checks))) * 10.0, 1),
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "contract": {
            "request": ChatRequest.__name__,
            "response": ChatResponse.__name__,
            "stream_chunk": StreamChunk.__name__,
            "health": ProviderHealth.__name__,
            "required_methods": list(REQUIRED_PROVIDER_METHODS),
            "dimensions": list(CONFORMANCE_DIMENSIONS),
        },
    }


def _descriptor_checks(descriptor: ProviderDescriptor) -> list[dict[str, Any]]:
    return [
        _check("provider_type", bool(descriptor.provider_type), "Descriptor has a provider_type."),
        _check("display_name", bool(descriptor.display_name), "Descriptor has a display_name."),
        _check("adapter_family", bool(descriptor.provider), "Descriptor declares an adapter family."),
        _check(
            "endpoint_or_custom_path",
            bool(descriptor.base_url or descriptor.chat_completions_path),
            "Descriptor declares a base URL or custom chat path.",
            required=False,
        ),
        _check(
            "capabilities_object",
            descriptor.capabilities is not None,
            "Descriptor has provider capabilities metadata.",
        ),
        _check(
            "pricing_object",
            descriptor.pricing is not None,
            "Descriptor has provider pricing metadata.",
        ),
    ]


def _adapter_instance_checks(provider_class: type[Any], agent: AgentConfig) -> list[dict[str, Any]]:
    try:
        instance = provider_class(agent)
    except Exception as exc:
        return [_check("constructs_from_agent_config", False, f"Provider did not construct: {exc}")]
    request = ChatRequest(messages=[])
    try:
        normalized = instance.normalize_request(request)
    except Exception as exc:
        normalized = None
        normalize_error = str(exc)
    else:
        normalize_error = ""
    try:
        health = instance.health_check()
    except Exception as exc:
        health = None
        health_error = str(exc)
    else:
        health_error = ""
    try:
        cost = instance.cost_estimate(1000, 500)
    except Exception as exc:
        cost = None
        cost_error = str(exc)
    else:
        cost_error = ""
    return [
        _check("constructs_from_agent_config", True, "Provider constructs from AgentConfig."),
        _check(
            "normalizes_request",
            isinstance(normalized, ChatRequest),
            "Provider normalizes ChatRequest without network access.",
            error=normalize_error,
        ),
        _check(
            "health_check_shape",
            isinstance(health, ProviderHealth),
            "Provider returns ProviderHealth.",
            error=health_error,
        ),
        _check(
            "cost_estimate_shape",
            cost is None or isinstance(cost, (int, float)),
            "Provider cost estimate is numeric or unknown.",
            error=cost_error,
        ),
    ]


def _dimension_checks(provider_class: type[Any], descriptor: ProviderDescriptor) -> list[dict[str, Any]]:
    capabilities = descriptor.capabilities
    pricing = descriptor.pricing
    has_stream_method = hasattr(provider_class, "stream")
    has_tool_method = hasattr(provider_class, "supports_tools")
    has_error_normalization = hasattr(provider_class, "normalize_response")
    auth_configured = bool(
        descriptor.default_free
        or descriptor.api_key_env
        or descriptor.auth_scheme in {"none", "bearer", "api-key", "header"}
        or descriptor.headers
    )
    return [
        _check(
            "auth",
            auth_configured,
            "Provider declares how authentication is configured or that it is free/local.",
            auth_scheme=descriptor.auth_scheme,
            api_key_env=descriptor.api_key_env,
        ),
        _check(
            "streaming",
            capabilities.supports_streaming is not True or has_stream_method,
            "Streaming-capable providers expose the stream contract.",
            supports_streaming=capabilities.supports_streaming,
        ),
        _check(
            "tools",
            capabilities.supports_tools is not True or has_tool_method,
            "Tool-capable providers expose the tool capability contract.",
            supports_tools=capabilities.supports_tools,
        ),
        _check(
            "retries",
            descriptor.default_cooldown_seconds >= 0,
            "Provider descriptor includes retry/cooldown policy metadata.",
            cooldown_seconds=descriptor.default_cooldown_seconds,
        ),
        _check(
            "errors",
            has_error_normalization,
            "Provider exposes normalized response/error boundary hooks.",
        ),
        _check(
            "timeouts",
            descriptor.default_timeout_seconds > 0,
            "Provider descriptor includes a positive timeout budget.",
            timeout_seconds=descriptor.default_timeout_seconds,
        ),
        _check(
            "costs",
            bool(
                descriptor.default_free
                or pricing.cost_per_million_input is not None
                or pricing.cost_per_million_output is not None
            ),
            "Provider descriptor declares free/local status or token pricing.",
            free=descriptor.default_free,
            currency=pricing.currency,
        ),
    ]


def _check(
    check_id: str,
    ok: bool,
    detail: str,
    *,
    required: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "ok": bool(ok),
        "required": bool(required),
        "detail": detail,
        **{key: value for key, value in extra.items() if value not in (None, "", [], {})},
    }


__all__ = ["CONFORMANCE_DIMENSIONS", "REQUIRED_PROVIDER_METHODS", "provider_conformance_report"]
