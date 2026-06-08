from __future__ import annotations

from ...models import ErrorCategory, FailoverEvent
from ..routing_policy import CONFIGURATION_ERROR, ECHO_DISABLED, NO_TOOL_CAPABLE_MODEL


ERROR_TYPE_ALIASES = {
    "configuration": CONFIGURATION_ERROR,
    "rate_limited": "temporary_rate_limit",
    "context_limit": "context_too_large",
    "temporary_unavailable": "provider_overloaded",
    "authentication": "authentication_error",
    "model_unavailable": "provider_unavailable",
    "network": "provider_unavailable",
    "timeout": "provider_unavailable",
    "provider_error": "unknown_error",
}


def _canonical_error_type(error_type: str | None) -> str:
    if not error_type:
        return ""
    return ERROR_TYPE_ALIASES.get(error_type, error_type)


def _no_fallback_reason(failover: list[FailoverEvent]) -> str:
    if not failover:
        return _no_model_available_message()
    no_tool_events = [
        event
        for event in failover
        if event.error_type == NO_TOOL_CAPABLE_MODEL
    ]
    if no_tool_events and len(no_tool_events) == len(failover):
        return _no_tool_capable_message(no_tool_events)
    permission_events = [
        event
        for event in failover
        if event.error_type in {"permission_required", "permission_denied"}
    ]
    if permission_events and len(permission_events) == len(failover):
        latest = permission_events[-1]
        if latest.error_type == "permission_denied":
            return f"Permission denied before using {latest.agent}: {latest.reason}"
        return (
            "Provider requires approval. Set approval_mode=auto or enable "
            f"cline_compatibility_mode for trusted providers. Provider: {latest.agent}. {latest.reason}"
        )
    echo_events = [
        event
        for event in failover
        if event.error_type == ECHO_DISABLED
    ]
    if echo_events and len(echo_events) == len(failover):
        return (
            "Echo is disabled by default and no real provider is available for this route. "
            "Configure an OpenAI-compatible, Anthropic, Gemini, or local provider, or set "
            "debug_echo_enabled=true only for diagnostics."
        )
    quota_events = [
        event
        for event in failover
        if _canonical_error_type(event.error_type) in {"quota_exhausted", "temporary_rate_limit"}
    ]
    if quota_events and len(quota_events) == len([event for event in failover if event.retryable]):
        latest = quota_events[-1]
        return (
            "No fallback model is currently available; providers are rate-limited "
            f"or out of free-tier quota. Last failure from {latest.agent}: {latest.reason}"
        )
    real_failures = [event for event in failover if event.error_type != ECHO_DISABLED]
    if echo_events and real_failures:
        latest = real_failures[-1]
        return (
            "No real fallback model is available; echo is disabled by default. "
            f"Last real provider failure from {latest.agent}: {latest.reason}"
        )
    return failover[-1].reason


def _route_error_type(failover: list[FailoverEvent]) -> str | None:
    if not failover:
        return None
    no_tool_events = [event for event in failover if event.error_type == NO_TOOL_CAPABLE_MODEL]
    if no_tool_events and len(no_tool_events) == len(failover):
        return NO_TOOL_CAPABLE_MODEL
    configuration_events = [
        event
        for event in failover
        if _canonical_error_type(event.error_type) == CONFIGURATION_ERROR
        or "missing API key env " in event.reason
    ]
    if configuration_events and len(configuration_events) == len(failover):
        return CONFIGURATION_ERROR
    echo_events = [event for event in failover if event.error_type == ECHO_DISABLED]
    if echo_events and len(echo_events) == len(failover):
        return CONFIGURATION_ERROR
    permission_events = [
        event
        for event in failover
        if event.error_type in {"permission_required", "permission_denied"}
    ]
    if permission_events and len(permission_events) == len(failover):
        return permission_events[-1].error_type
    invalid_events = [event for event in failover if event.error_type == "invalid_provider_response"]
    if invalid_events and len(invalid_events) == len(failover):
        return "invalid_provider_response"
    retryable_events = [event for event in failover if event.retryable and event.error_type]
    if retryable_events and len(retryable_events) == len(failover):
        return _canonical_error_type(retryable_events[-1].error_type)
    return None


def _router_error_category(error_type: str | None) -> str:
    error_type = _canonical_error_type(error_type)
    if error_type in {CONFIGURATION_ERROR, ECHO_DISABLED, NO_TOOL_CAPABLE_MODEL}:
        return ErrorCategory.CONFIGURATION
    if error_type in {"permission_required", "permission_denied"}:
        return ErrorCategory.PERMISSION
    if error_type == "invalid_provider_response":
        return ErrorCategory.VALIDATION
    if error_type in {"context_too_large", "output_too_large"}:
        return ErrorCategory.CONTEXT_LIMIT
    if error_type in {"temporary_rate_limit", "quota_exhausted"}:
        return ErrorCategory.RATE_LIMIT if error_type == "temporary_rate_limit" else ErrorCategory.QUOTA
    if error_type in {"provider_unavailable", "provider_overloaded"}:
        return ErrorCategory.NETWORK
    if error_type == "authentication_error":
        return ErrorCategory.CONFIGURATION
    return ErrorCategory.PROVIDER if error_type else ErrorCategory.UNKNOWN


def _router_user_message(message: str, suggested_fix: str | None) -> str:
    if suggested_fix:
        return f"{message} Suggested fix: {suggested_fix}"
    return message


def _route_status_code(error_type: str | None) -> int | None:
    if error_type in {NO_TOOL_CAPABLE_MODEL, CONFIGURATION_ERROR}:
        return 400
    return None


def _suggested_fix(error_type: str | None, failover: list[FailoverEvent]) -> str | None:
    missing_keys = _missing_key_names(failover)
    if error_type == NO_TOOL_CAPABLE_MODEL:
        return _no_tool_capable_fix(failover)
    if missing_keys:
        return (
            f"Set {', '.join(missing_keys)} or disable that provider. "
            "For Cline, use model agent-hub-coding against the Agent Hub OpenAI endpoint."
        )
    if error_type == CONFIGURATION_ERROR:
        return _no_model_available_fix()
    return None


def _no_model_available_message() -> str:
    return (
        "No usable model is available for this request. Enable a provider in Agent Hub "
        "settings, add an API key, or start a local Ollama/LM Studio model. For Cline, "
        "use model agent-hub-coding."
    )


def _no_model_available_fix() -> str:
    return (
        "Open the Agent Hub sidebar, add an API key or start Ollama/LM Studio, then click "
        "Start Server. Cline base URL: http://127.0.0.1:8787/v1, model: agent-hub-coding. "
        "Claude Code endpoint: http://127.0.0.1:8787/v1/messages."
    )


def _no_tool_capable_message(events: list[FailoverEvent]) -> str:
    checked = _checked_model_summary(events)
    fix = _no_tool_capable_fix(events)
    if checked:
        return (
            "No tool-capable model is available for this Cline/OpenAI-compatible request. "
            f"Checked: {checked}. Suggested fix: {fix}"
        )
    return (
        "No tool-capable model is available for this Cline/OpenAI-compatible request. "
        f"Suggested fix: {fix}"
    )


def _no_tool_capable_fix(events: list[FailoverEvent]) -> str:
    missing_keys = _missing_key_names(events)
    if missing_keys:
        keys = ", ".join(missing_keys)
        return (
            f"Set {keys}, enable that provider, or configure a local OpenAI-compatible "
            "coding model with supports_tools=true on the selected route."
        )
    return (
        "Configure an enabled non-echo provider on the selected route with "
        "supports_tools=true or supports_function_calling=true, such as OpenAI, "
        "Anthropic, Gemini, or a local OpenAI-compatible server that supports tools."
    )


def _checked_model_summary(events: list[FailoverEvent]) -> str:
    parts: list[str] = []
    for event in events[:6]:
        parts.append(f"{event.agent} ({event.provider}/{event.model}: {event.reason})")
    if len(events) > 6:
        parts.append(f"{len(events) - 6} more")
    return "; ".join(parts)


def _missing_key_names(events: list[FailoverEvent]) -> list[str]:
    names: list[str] = []
    marker = "missing API key env "
    for event in events:
        if marker not in event.reason:
            continue
        key = event.reason.split(marker, 1)[1].strip().split()[0].strip(".,;:")
        if key and key not in names:
            names.append(key)
    return names


__all__ = [
    "ERROR_TYPE_ALIASES",
    "_canonical_error_type",
    "_checked_model_summary",
    "_missing_key_names",
    "_no_fallback_reason",
    "_no_model_available_fix",
    "_no_model_available_message",
    "_no_tool_capable_fix",
    "_no_tool_capable_message",
    "_route_error_type",
    "_route_status_code",
    "_router_error_category",
    "_router_user_message",
    "_suggested_fix",
]
