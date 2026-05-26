from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .trust import CAPABILITY_SCOPES, normalize_capability_scopes


@dataclass(slots=True)
class PluginExecutionRequest:
    plugin_id: str
    action: str
    requested_scopes: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PluginExecutionResult:
    ok: bool
    reason: str
    plugin_id: str
    action: str
    granted_scopes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "plugin_id": self.plugin_id,
            "action": self.action,
            "granted_scopes": list(self.granted_scopes),
        }


class PluginExecutionSandbox:
    """Deny-by-default execution interface for future trusted plugin code."""

    def __init__(self, *, execution_enabled: bool = False, granted_scopes: list[str] | None = None) -> None:
        self.execution_enabled = execution_enabled
        self.granted_scopes = normalize_capability_scopes(granted_scopes or [])

    def execute(self, request: PluginExecutionRequest) -> PluginExecutionResult:
        requested = normalize_capability_scopes(request.requested_scopes)
        missing = [scope for scope in requested if scope not in self.granted_scopes]
        if missing:
            return PluginExecutionResult(
                ok=False,
                reason="plugin_capability_scope_denied",
                plugin_id=request.plugin_id,
                action=request.action,
                granted_scopes=self.granted_scopes,
            )
        if not self.execution_enabled:
            return PluginExecutionResult(
                ok=False,
                reason="plugin_execution_disabled",
                plugin_id=request.plugin_id,
                action=request.action,
                granted_scopes=self.granted_scopes,
            )
        return PluginExecutionResult(
            ok=False,
            reason="plugin_code_execution_not_implemented",
            plugin_id=request.plugin_id,
            action=request.action,
            granted_scopes=self.granted_scopes,
        )


def plugin_execution_policy(config: Any, plugin: Any) -> dict[str, Any]:
    trust = getattr(plugin, "trust", {}) if plugin is not None else {}
    scopes = trust.get("granted_scopes") if isinstance(trust, dict) else []
    return {
        "execution_enabled": bool(getattr(config, "plugin_execution_enabled", False)),
        "code_execution": False,
        "capability_scopes": normalize_capability_scopes(scopes if isinstance(scopes, list) else []),
        "available_scopes": sorted(CAPABILITY_SCOPES),
    }


__all__ = [
    "CAPABILITY_SCOPES",
    "PluginExecutionRequest",
    "PluginExecutionResult",
    "PluginExecutionSandbox",
    "plugin_execution_policy",
]
