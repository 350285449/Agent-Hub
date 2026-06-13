from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..capabilities import agent_supports_tools
from ..config import (
    AgentConfig,
    HubConfig,
    _is_local_or_private_url,
    agent_allowed_by_cost_policy,
    is_free_agent,
    normalize_provider,
)
from ..models import HubRequest
from ..provider_presets import provider_defaults_for_agent
from ..tool_compatibility import agent_can_emulate_tools, tool_emulation_can_handle
from .context import estimate_context_tokens
from .health import ProviderHealth


TRANSPARENT_API_SHAPES = {"openai-chat", "openai-responses", "anthropic-messages"}
NO_TOOL_CAPABLE_MODEL = "no_tool_capable_model"
ECHO_DISABLED = "echo_disabled"
CONFIGURATION_ERROR = "configuration_error"
LOCAL_API_KEY_OPTIONAL_PROVIDER_TYPES = {
    "codex-cli",
    "echo",
    "llama-cpp",
    "lm-studio",
    "local-research",
    "localai",
    "ollama",
    "ollama-local",
    "openai-compatible",
    "vllm",
}


@dataclass(slots=True)
class RouterPreflightPolicy:
    """Provider eligibility checks that run before router execution."""

    config: HubConfig
    health_by_agent: dict[str, ProviderHealth] | None = None

    def skip_reason(
        self,
        agent: AgentConfig,
        request: HubRequest,
        *,
        health: ProviderHealth | None = None,
    ) -> str | None:
        health = health if health is not None else self._health_for(agent)
        if (
            _requires_tool_capable_model(request)
            and not _agent_supports_tools(agent)
            and not (
                agent_can_emulate_tools(self.config, agent)
                and tool_emulation_can_handle(self.config, request)
            )
        ):
            if _is_echo_agent(agent):
                return (
                    "Echo is a diagnostic provider and cannot satisfy Cline, Claude Code, "
                    "or OpenAI-compatible tool calls."
                )
            return (
                "This request includes tools, but the configured agent does not advertise "
                "tool/function-call support."
            )

        if _is_echo_agent(agent) and not self.config.debug_echo_enabled:
            return (
                "Echo is disabled by default because it only repeats the task and is not a real model. "
                "Configure a real provider or set debug_echo_enabled=true for diagnostics."
            )

        if not agent_allowed_by_cost_policy(self.config, agent):
            return (
                "Agent provider is disabled because free_only is enabled; "
                "only agents allowed by the configured free-model policy are allowed"
            )

        if _requires_missing_api_key(agent):
            return f"Agent is missing API key env {agent.api_key_env}"

        input_tokens = estimate_input_tokens(request)
        output_tokens = effective_output_tokens(
            self.config,
            request,
            agent,
            input_tokens=input_tokens,
            health=health,
        )
        required_tokens = input_tokens + output_tokens
        quota_reason = _quota_skip_reason(health, required_tokens=required_tokens)
        if quota_reason:
            return quota_reason

        if agent.context_window is None:
            return None

        if required_tokens > agent.context_window:
            return (
                "Agent context window is too small: "
                f"needs about {required_tokens} tokens "
                f"({input_tokens} input + {output_tokens} output), "
                f"has {agent.context_window}"
            )
        return None

    def error_type(
        self,
        agent: AgentConfig,
        request: HubRequest,
        reason: str,
    ) -> str | None:
        if _requires_tool_capable_model(request):
            if (
                not _agent_supports_tools(agent)
                and not (
                    agent_can_emulate_tools(self.config, agent)
                    and tool_emulation_can_handle(self.config, request)
                )
                or _requires_missing_api_key(agent)
                or "free_only" in reason
            ):
                return NO_TOOL_CAPABLE_MODEL
        if _is_echo_agent(agent) and not self.config.debug_echo_enabled:
            return ECHO_DISABLED
        if "missing API key" in reason:
            return CONFIGURATION_ERROR
        lowered = reason.lower()
        if "context window" in lowered or "too small" in lowered:
            return "context_too_large"
        if "rate-limited" in lowered or "remaining requests" in lowered:
            return "temporary_rate_limit"
        if "quota" in lowered or "credits" in lowered:
            return "quota_exhausted"
        if "remaining tokens" in lowered:
            return "context_too_large"
        return None

    def _health_for(self, agent: AgentConfig) -> ProviderHealth | None:
        if self.health_by_agent is None:
            return None
        return self.health_by_agent.get(agent.name)


def estimate_input_tokens(request: HubRequest) -> int:
    return estimate_context_tokens(request)


def expected_output_tokens(request: HubRequest, agent: AgentConfig) -> int:
    if request.max_tokens is not None:
        return _non_negative_int(request.max_tokens, default=0)
    if agent.max_tokens is not None:
        return _non_negative_int(agent.max_tokens, default=0)
    return 0


def effective_output_tokens(
    config: HubConfig,
    request: HubRequest,
    agent: AgentConfig,
    *,
    input_tokens: int,
    health: ProviderHealth | None = None,
) -> int:
    return output_token_budget(
        config,
        request,
        agent,
        input_tokens=input_tokens,
        health=health,
    ).effective


@dataclass(frozen=True, slots=True)
class OutputTokenBudget:
    requested: int
    effective: int
    limit: int | None = None
    adjusted: bool = False
    mode: str = "auto"


def output_token_budget(
    config: HubConfig,
    request: HubRequest,
    agent: AgentConfig,
    *,
    input_tokens: int,
    health: ProviderHealth | None = None,
) -> OutputTokenBudget:
    requested = expected_output_tokens(request, agent)
    mode = _max_tokens_mode(config)
    if requested <= 0:
        return OutputTokenBudget(requested=requested, effective=requested, mode=mode)
    if mode != "auto":
        return OutputTokenBudget(requested=requested, effective=requested, mode=mode)

    limit = model_output_token_limit(agent, input_tokens=input_tokens, health=health)
    if limit is None or limit <= 0:
        return OutputTokenBudget(requested=requested, effective=requested, limit=limit, mode=mode)
    effective = min(requested, limit)
    return OutputTokenBudget(
        requested=requested,
        effective=effective,
        limit=limit,
        adjusted=effective < requested,
        mode=mode,
    )


def model_output_token_limit(
    agent: AgentConfig,
    *,
    input_tokens: int,
    health: ProviderHealth | None = None,
) -> int | None:
    caps: list[int] = []
    input_count = max(0, int(input_tokens or 0))
    if agent.context_window is not None:
        caps.append(max(0, int(agent.context_window) - input_count))
    if health is not None:
        if health.max_output_tokens is not None:
            caps.append(max(0, int(health.max_output_tokens)))
        if health.tokens_remaining is not None:
            caps.append(max(0, int(health.tokens_remaining) - input_count))
    if not caps:
        return None
    return min(caps)


def _max_tokens_mode(config: HubConfig) -> str:
    routing = getattr(config, "routing", {}) or {}
    mode = str(routing.get("max_tokens_mode") or "auto").strip().lower().replace("-", "_")
    return "auto" if mode in {"auto", "automatic", "adaptive", "provider"} else mode


def _non_negative_int(value: object, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _requires_missing_api_key(agent: AgentConfig) -> bool:
    if not agent.api_key_env or agent.resolved_api_key:
        return False
    provider = normalize_provider(agent.provider)
    if provider in {"openai", "anthropic", "gemini"}:
        return True
    if provider == "openai-compatible" and agent.base_url:
        return not _is_local_or_private_agent(agent)
    metadata = provider_defaults_for_agent(agent)
    if metadata and metadata.api_key_env == agent.api_key_env:
        if metadata.base_url:
            return not _is_local_or_private_url(metadata.base_url)
        provider_type = (agent.provider_type or agent.provider).lower()
        return provider_type not in LOCAL_API_KEY_OPTIONAL_PROVIDER_TYPES
    return False


def _is_local_or_private_agent(agent: AgentConfig) -> bool:
    provider = normalize_provider(agent.provider)
    provider_type = (agent.provider_type or agent.provider).lower()
    if provider in {"echo", "local-research"}:
        return True
    if provider_type == "ollama-cloud":
        return False
    return _is_local_or_private_url(agent.base_url)


def _is_echo_agent(agent: AgentConfig) -> bool:
    return normalize_provider(agent.provider) == "echo"


def _agent_supports_tools(agent: AgentConfig) -> bool:
    return agent_supports_tools(agent)


def _requires_tool_capable_model(request: HubRequest) -> bool:
    return request.api_shape in TRANSPARENT_API_SHAPES and _request_has_tools(request)


def _quota_skip_reason(health: ProviderHealth | None, *, required_tokens: int) -> str | None:
    if health is None:
        return None
    now = time.time()
    if health.rate_limit_reset_at is not None and health.rate_limit_reset_at <= now:
        return None
    if health.quota_exhausted and health.cooldown_deadline() > now:
        return _availability_reason("Provider appears to be out of quota or credits", health)
    if health.rate_limited and health.cooldown_deadline() > now:
        return _availability_reason("Provider is temporarily rate-limited", health)
    if health.requests_remaining is not None and health.requests_remaining <= 0:
        return _availability_reason("Provider has no remaining requests from last observed quota metadata", health)
    if health.quota_remaining is not None and health.quota_remaining <= 0:
        return _availability_reason("Provider appears to be out of free-tier quota or credits", health)
    if health.credits_remaining is not None and health.credits_remaining <= 0:
        return _availability_reason("Provider appears to be out of free-tier credits", health)
    if health.tokens_remaining is not None and health.tokens_remaining < required_tokens:
        return (
            "Provider has too few observed remaining tokens: "
            f"needs about {required_tokens}, has {health.tokens_remaining}"
        )
    return None


def _availability_reason(prefix: str, health: ProviderHealth) -> str:
    deadline = max(health.cooldown_deadline(), health.rate_limit_reset_at or 0.0)
    if deadline > time.time():
        return f"{prefix}; retry after {int(deadline - time.time())}s"
    return prefix


def _request_has_tools(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    if isinstance(raw.get("tools"), list) and raw["tools"]:
        return True
    if isinstance(raw.get("functions"), list) and raw["functions"]:
        return True
    if isinstance(raw.get("agent_hub_tools"), list) and raw["agent_hub_tools"]:
        return True
    if isinstance(raw.get("tool_choice"), (str, dict)):
        return True
    if isinstance(raw.get("function_call"), (str, dict)):
        return True
    hub_options = raw.get("agent_hub")
    return isinstance(hub_options, dict) and bool(hub_options.get("agent_mode"))


def _request_has_client_tool_specs(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    return bool(
        (isinstance(raw.get("tools"), list) and raw["tools"])
        or (isinstance(raw.get("functions"), list) and raw["functions"])
    )


__all__ = [
    "CONFIGURATION_ERROR",
    "ECHO_DISABLED",
    "NO_TOOL_CAPABLE_MODEL",
    "RouterPreflightPolicy",
    "TRANSPARENT_API_SHAPES",
    "OutputTokenBudget",
    "effective_output_tokens",
    "estimate_input_tokens",
    "expected_output_tokens",
    "model_output_token_limit",
    "output_token_budget",
    "_agent_supports_tools",
    "_is_echo_agent",
    "_is_local_or_private_agent",
    "_quota_skip_reason",
    "_request_has_client_tool_specs",
    "_request_has_tools",
    "_requires_missing_api_key",
    "_requires_tool_capable_model",
]
