from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ..capabilities import agent_supports_tools
from ..config import AgentConfig, HubConfig
from ..models import HubRequest
from ..repository import repo_context_for_request
from ..tools import ToolRegistry
from .routing_policy import _request_has_client_tool_specs
from .task_classifier import classify_task


ToolCandidatePredicate = Callable[[HubRequest], bool]
RepoContextProvider = Callable[..., Any]


class ContextPreparationService:
    """Prepare provider-neutral requests before routing execution.

    The router owns selection; this service owns context enrichment and built-in
    tool exposure so those concerns do not leak into provider ranking.
    """

    def __init__(
        self,
        config: HubConfig,
        *,
        tool_registry: ToolRegistry,
        has_tool_capable_candidate: ToolCandidatePredicate,
        repo_context_provider: RepoContextProvider = repo_context_for_request,
    ) -> None:
        self.config = config
        self.tool_registry = tool_registry
        self.has_tool_capable_candidate = has_tool_capable_candidate
        self.repo_context_for_request = repo_context_provider

    def prepare(self, request: HubRequest, *, include_tools: bool = True) -> HubRequest:
        if include_tools:
            request = self.with_builtin_tool_specs(request)
        return self.with_repo_context(request)

    def with_repo_context(self, request: HubRequest) -> HubRequest:
        if not getattr(self.config, "repo_context_enabled", True):
            return request
        if _agent_runner_managed_request(request):
            return request
        if _request_has_client_tool_specs(request):
            return request
        classification = classify_task(request)
        if not classification.repository_context_needed:
            return request
        if any(message.get("agent_hub_repo_context") for message in request.messages if isinstance(message, dict)):
            return request
        max_files = self.config.repo_context_max_files
        max_chars = self.config.repo_context_max_chars
        if compatibility_reductions_enabled(self.config, request, "reduced_repo_context"):
            max_files = min(max_files, 3)
            max_chars = min(max_chars, 4_000)
        try:
            selection = self.repo_context_for_request(
                request,
                self.config.workspace_dir,
                max_files=max_files,
                max_chars=max_chars,
                ignore_patterns=self.config.repo_ignore_patterns,
            )
        except Exception:
            return request
        message = selection.to_message()
        if message is None:
            return request
        raw = dict(request.raw or {})
        hub = dict(raw.get("agent_hub") or {})
        hub["repo_context"] = selection.to_dict()
        hub["context_strategy"] = classification.context_strategy
        raw["agent_hub"] = hub
        return replace(request, messages=[message, *request.messages], raw=raw)

    def with_builtin_tool_specs(self, request: HubRequest) -> HubRequest:
        if not getattr(self.config, "tool_loop_enabled", True):
            return request
        if request_is_cline(request) and not getattr(self.config, "tool_loop_enabled_for_cline", False):
            return request
        if _agent_runner_managed_request(request):
            return request
        if _request_has_client_tool_specs(request):
            return request
        if request_option(request, "disable_builtin_tools", "disable_agent_hub_tools") is True:
            return request
        classification = classify_task(request)
        if "tools" not in classification.required_capabilities:
            return request
        if not self.has_tool_capable_candidate(request):
            return request
        raw = dict(request.raw or {})
        if isinstance(raw.get("agent_hub_tools"), list) and raw["agent_hub_tools"]:
            return request
        tool_specs = [tool.to_agent_hub_spec() for tool in self.tool_registry.list()]
        if compatibility_reductions_enabled(self.config, request, "minimal_tool_schema"):
            tool_specs = [_minimal_tool_schema(spec) for spec in tool_specs]
        raw["agent_hub_tools"] = tool_specs
        hub = dict(raw.get("agent_hub") or {})
        hub["auto_execute_tools"] = True
        hub["task_classification"] = classification.to_dict()
        raw["agent_hub"] = hub
        return replace(request, raw=raw)


def agent_supports_required_tools(agent: AgentConfig) -> bool:
    return agent_supports_tools(agent)


def request_option(request: HubRequest, *keys: str, default: Any = None) -> Any:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub_options = raw.get("agent_hub")
    for key in keys:
        if isinstance(hub_options, dict) and key in hub_options:
            return hub_options[key]
        if key in raw:
            return raw[key]
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    for key in keys:
        if key in metadata:
            return metadata[key]
    return default


def request_is_cline(request: HubRequest) -> bool:
    source = str(request_option(request, "source", "client", default="")).lower()
    user_agent = str((request.metadata or {}).get("user_agent", "")).lower()
    return "cline" in source or "cline" in user_agent


def compatibility_reductions_enabled(config: HubConfig, request: HubRequest, key: str) -> bool:
    compatibility = getattr(config, "compatibility_mode", {}) or {}
    value = compatibility.get(key)
    if value is not None:
        return bool(value)
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    value = hub.get(key)
    if isinstance(value, bool):
        return value
    return False


def _agent_runner_managed_request(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    return isinstance(raw.get("agent_hub_runtime"), dict)


def _minimal_tool_schema(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name") or "")
    parameters = spec.get("parameters") if isinstance(spec.get("parameters"), dict) else {}
    properties = parameters.get("properties") if isinstance(parameters.get("properties"), dict) else {}
    minimal_properties = {
        key: {"type": value.get("type", "string")} if isinstance(value, dict) else {"type": "string"}
        for key, value in properties.items()
    }
    return {
        "name": name,
        "description": str(spec.get("description") or "")[:160],
        "parameters": {
            "type": parameters.get("type", "object"),
            "properties": minimal_properties,
            **({"required": parameters["required"]} if isinstance(parameters.get("required"), list) else {}),
        },
    }


__all__ = [
    "ContextPreparationService",
    "RepoContextProvider",
    "ToolCandidatePredicate",
    "agent_supports_required_tools",
    "compatibility_reductions_enabled",
    "request_is_cline",
    "request_option",
]
