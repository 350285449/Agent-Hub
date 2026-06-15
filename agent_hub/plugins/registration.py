from __future__ import annotations

import re
from typing import Any

from ..config import AgentConfig, HubConfig
from ..tools.registry import ToolRegistry
from ..tools.types import Tool, ToolCall, ToolResult
from .discovery import discover_plugins
from .models import DiscoveredPlugin


def apply_plugin_registrations(config: HubConfig) -> dict[str, Any]:
    """Apply trusted manifest-only plugin registrations to the runtime config."""

    discovery = discover_plugins(config)
    registered_providers: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for plugin in discovery.plugins:
        if not plugin.registerable:
            skipped.append(_skip(plugin, plugin.registration_reason or "not_registerable"))
            continue
        if plugin.manifest.type != "provider":
            skipped.append(_skip(plugin, "live_registration_not_supported_for_capability_type"))
            continue
        providers = _provider_agents_from_plugin(plugin)
        if not providers:
            skipped.append(_skip(plugin, "provider_plugin_declares_no_models"))
            continue
        for agent in providers:
            if agent.name in config.agents:
                skipped.append(_skip(plugin, "agent_already_configured", agent=agent.name))
                continue
            config.agents[agent.name] = agent
            if _metadata_bool(plugin.manifest.metadata, "add_to_default_route", False):
                config.default_route.append(agent.name)
            registered_providers.append(
                {
                    "plugin_id": plugin.manifest.id,
                    "agent": agent.name,
                    "provider": agent.provider,
                    "provider_type": agent.provider_type,
                    "model": agent.model,
                }
            )
    report = {
        "object": "agent_hub.plugin_runtime_registrations",
        "provider_count": len(registered_providers),
        "providers": registered_providers,
        "skipped": skipped,
    }
    config.initialization_report["plugin_runtime_registrations"] = report
    return report


def register_plugin_tools(registry: ToolRegistry, config: HubConfig) -> dict[str, Any]:
    """Register trusted plugin-declared tool specs without executing plugin code."""

    discovery = discover_plugins(config)
    registered: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for plugin in discovery.plugins:
        if not plugin.registerable:
            skipped.append(_skip(plugin, plugin.registration_reason or "not_registerable"))
            continue
        if plugin.manifest.type != "tool":
            continue
        tools = _tools_from_plugin(plugin)
        if not tools:
            skipped.append(_skip(plugin, "tool_plugin_declares_no_tools"))
            continue
        for tool in tools:
            if registry.get(tool.name) is not None:
                skipped.append(_skip(plugin, "tool_already_registered", agent=tool.name))
                continue
            registry.register(tool)
            registered.append(
                {
                    "plugin_id": plugin.manifest.id,
                    "tool": tool.name,
                    "permission": tool.permission,
                    "permissions": tool.effective_permissions(),
                }
            )
    report = {
        "object": "agent_hub.plugin_tool_registrations",
        "tool_count": len(registered),
        "tools": registered,
        "skipped": skipped,
    }
    config.initialization_report["plugin_tool_registrations"] = report
    return report


def _provider_agents_from_plugin(plugin: DiscoveredPlugin) -> list[AgentConfig]:
    metadata = plugin.manifest.metadata if isinstance(plugin.manifest.metadata, dict) else {}
    models = _models(metadata)
    agents: list[AgentConfig] = []
    for index, model in enumerate(models):
        name = str(metadata.get("agent_name") or metadata.get("name") or "").strip()
        if not name:
            suffix = "" if len(models) == 1 else f"-{_slug(model)}"
            name = f"{plugin.manifest.id}{suffix}"
        if len(models) > 1 and index > 0 and name in {agent.name for agent in agents}:
            name = f"{name}-{index + 1}"
        agents.append(
            AgentConfig(
                name=name,
                provider=str(metadata.get("provider") or "openai-compatible"),
                provider_type=_optional_string(metadata.get("provider_type")) or plugin.manifest.id,
                model=model,
                enabled=_metadata_bool(metadata, "enabled", True),
                free=_optional_bool(metadata.get("free")),
                api_key_env=_optional_string(metadata.get("api_key_env")),
                base_url=_optional_string(metadata.get("base_url")),
                chat_completions_path=_optional_string(metadata.get("chat_completions_path")),
                timeout_seconds=_float_with_default(metadata.get("timeout_seconds"), 120.0),
                cooldown_seconds=_float_with_default(metadata.get("cooldown_seconds"), 120.0),
                context_window=_optional_int(metadata.get("context_window")),
                coding_score=_optional_float(metadata.get("coding_score")),
                reasoning_score=_optional_float(metadata.get("reasoning_score")),
                speed_score=_optional_float(metadata.get("speed_score")),
                cost_per_million_input=_optional_float(metadata.get("cost_per_million_input")),
                cost_per_million_output=_optional_float(metadata.get("cost_per_million_output")),
                supports_tools=_optional_bool(metadata.get("supports_tools")),
                supports_json=_optional_bool(metadata.get("supports_json")),
                supports_streaming=_optional_bool(metadata.get("supports_streaming")),
                supports_vision=_optional_bool(metadata.get("supports_vision")),
                supports_function_calling=_optional_bool(metadata.get("supports_function_calling")),
                priority=_float_with_default(metadata.get("priority"), 0.0),
                privacy_mode=str(metadata.get("privacy_mode") or "safe_for_code"),
                local_only=_metadata_bool(metadata, "local_only", False),
                safe_for_code=_metadata_bool(metadata, "safe_for_code", True),
                safe_for_secrets=_metadata_bool(metadata, "safe_for_secrets", False),
                never_send_workspace_files=_metadata_bool(metadata, "never_send_workspace_files", False),
            )
        )
    return agents


def _tools_from_plugin(plugin: DiscoveredPlugin) -> list[Tool]:
    metadata = plugin.manifest.metadata if isinstance(plugin.manifest.metadata, dict) else {}
    declarations = metadata.get("tools")
    rows = declarations if isinstance(declarations, list) else [metadata]
    tools: list[Tool] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or plugin.manifest.id).strip()
        if not name:
            continue
        description = str(row.get("description") or plugin.manifest.description or plugin.manifest.name).strip()
        input_schema = row.get("input_schema") or row.get("parameters") or {}
        if not isinstance(input_schema, dict):
            input_schema = {}
        output_schema = row.get("output_schema") or row.get("output") or {}
        if not isinstance(output_schema, dict):
            output_schema = {}
        permissions = [
            str(item).strip()
            for item in row.get("permissions", plugin.manifest.permissions)
            if isinstance(item, str) and item.strip()
        ] if isinstance(row.get("permissions", plugin.manifest.permissions), list) else []
        permission = str(row.get("permission") or (permissions[0] if permissions else "read")).strip()
        tools.append(
            Tool(
                name=name,
                description=description,
                input_schema=input_schema or {"type": "object", "properties": {}},
                output_schema=output_schema,
                executor=_plugin_tool_executor(plugin.manifest.id),
                read_only=_metadata_bool(row, "read_only", permission == "read"),
                permission=permission,
                permissions=permissions,
                metadata={
                    "plugin_id": plugin.manifest.id,
                    "plugin_tool": True,
                    "execution_policy": "plugin_execution_endpoint_required",
                    **(dict(row.get("metadata")) if isinstance(row.get("metadata"), dict) else {}),
                },
            )
        )
    return tools


def _plugin_tool_executor(plugin_id: str):
    def execute(call: ToolCall, context: Any) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=False,
            error=(
                "Plugin tool execution is policy-gated. Use the plugin execution "
                f"endpoint for trusted plugin '{plugin_id}' with explicit scopes."
            ),
            metadata={
                "plugin_id": plugin_id,
                "status": "execution_policy_gated",
                "execute_endpoint": f"/v1/plugins/{plugin_id}/execute",
            },
        )

    return execute


def _models(metadata: dict[str, Any]) -> list[str]:
    raw = metadata.get("models")
    if isinstance(raw, list):
        models = [str(item).strip() for item in raw if str(item or "").strip()]
        if models:
            return models[:20]
    model = str(metadata.get("model") or "").strip()
    return [model] if model else []


def _skip(plugin: DiscoveredPlugin, reason: str, *, agent: str = "") -> dict[str, Any]:
    row = {"plugin_id": plugin.manifest.id, "type": plugin.manifest.type, "reason": reason}
    if agent:
        row["agent"] = agent
    return row


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return text[:48] or "model"


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}
    return bool(value)


def _metadata_bool(metadata: dict[str, Any], key: str, default: bool) -> bool:
    parsed = _optional_bool(metadata.get(key))
    return default if parsed is None else parsed


def _float_with_default(value: Any, default: float) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed


__all__ = ["apply_plugin_registrations", "register_plugin_tools"]
