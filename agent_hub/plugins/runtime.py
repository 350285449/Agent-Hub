from __future__ import annotations

from typing import Any

from ..config import HubConfig
from .discovery import discover_plugins
from .sandbox import PluginExecutionRequest, PluginExecutionResult, PluginExecutionSandbox


def execute_plugin(
    config: HubConfig,
    *,
    plugin_id: str,
    action: str,
    payload: dict[str, Any] | None = None,
    requested_scopes: list[str] | None = None,
) -> PluginExecutionResult:
    discovered = next(
        (plugin for plugin in discover_plugins(config).plugins if plugin.manifest.id == plugin_id),
        None,
    )
    if discovered is None:
        return _denied(plugin_id, action, "plugin_not_found")
    if not discovered.enabled:
        return _denied(plugin_id, action, "plugin_disabled")
    if not discovered.trusted:
        return _denied(plugin_id, action, "plugin_untrusted")
    sandbox_policy = discovered.sandbox
    if not sandbox_policy.get("code_execution"):
        return _denied(plugin_id, action, "plugin_execution_disabled")
    sandbox = PluginExecutionSandbox(
        execution_enabled=True,
        granted_scopes=list(sandbox_policy.get("capability_scopes") or []),
        backend=str(sandbox_policy.get("backend") or "disabled"),
        entrypoint=sandbox_policy.get("entrypoint"),
    )
    return sandbox.execute(
        PluginExecutionRequest(
            plugin_id=plugin_id,
            action=action,
            requested_scopes=list(requested_scopes or []),
            payload=dict(payload or {}),
        )
    )


def _denied(plugin_id: str, action: str, reason: str) -> PluginExecutionResult:
    return PluginExecutionResult(
        ok=False,
        reason=reason,
        plugin_id=plugin_id,
        action=action,
    )


__all__ = ["execute_plugin"]
