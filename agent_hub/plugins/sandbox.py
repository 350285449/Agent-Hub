from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .trust import CAPABILITY_SCOPES, normalize_capability_scopes


PLUGIN_SANDBOX_BACKENDS = {
    "disabled",
    "local_process",
    "docker",
    "wasm",
}


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
    backend: str = "disabled"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "plugin_id": self.plugin_id,
            "action": self.action,
            "granted_scopes": list(self.granted_scopes),
            "backend": self.backend,
        }


class PluginExecutionSandbox:
    """Deny-by-default execution interface for future trusted plugin code."""

    def __init__(
        self,
        *,
        execution_enabled: bool = False,
        granted_scopes: list[str] | None = None,
        backend: str = "disabled",
    ) -> None:
        self.execution_enabled = execution_enabled
        self.granted_scopes = normalize_capability_scopes(granted_scopes or [])
        self.backend = normalize_sandbox_backend(backend)

    def execute(self, request: PluginExecutionRequest) -> PluginExecutionResult:
        raw_requested = [
            str(scope or "").strip()
            for scope in request.requested_scopes
            if str(scope or "").strip()
        ]
        invalid = [scope for scope in raw_requested if scope not in CAPABILITY_SCOPES]
        if invalid:
            return PluginExecutionResult(
                ok=False,
                reason="plugin_capability_scope_denied",
                plugin_id=request.plugin_id,
                action=request.action,
                granted_scopes=self.granted_scopes,
                backend=self.backend,
            )
        requested = normalize_capability_scopes(raw_requested)
        missing = [scope for scope in requested if scope not in self.granted_scopes]
        if missing:
            return PluginExecutionResult(
                ok=False,
                reason="plugin_capability_scope_denied",
                plugin_id=request.plugin_id,
                action=request.action,
                granted_scopes=self.granted_scopes,
                backend=self.backend,
            )
        if self.backend == "disabled" or not self.execution_enabled:
            return PluginExecutionResult(
                ok=False,
                reason="plugin_execution_disabled",
                plugin_id=request.plugin_id,
                action=request.action,
                granted_scopes=self.granted_scopes,
                backend=self.backend,
            )
        return PluginExecutionResult(
            ok=False,
            reason="plugin_code_execution_not_implemented",
            plugin_id=request.plugin_id,
            action=request.action,
            granted_scopes=self.granted_scopes,
            backend=self.backend,
        )


def plugin_execution_policy(config: Any, plugin: Any) -> dict[str, Any]:
    trust = getattr(plugin, "trust", {}) if plugin is not None else {}
    scopes = trust.get("granted_scopes") if isinstance(trust, dict) else []
    return {
        "execution_enabled": bool(getattr(config, "plugin_execution_enabled", False)),
        "code_execution": False,
        "capability_scopes": normalize_capability_scopes(scopes if isinstance(scopes, list) else []),
        "available_scopes": sorted(CAPABILITY_SCOPES),
        "available_backends": sorted(PLUGIN_SANDBOX_BACKENDS),
        "backend": "disabled",
    }


def normalize_sandbox_backend(value: Any) -> str:
    backend = str(value or "disabled").strip().lower().replace("-", "_")
    if backend in PLUGIN_SANDBOX_BACKENDS:
        return backend
    return "disabled"


__all__ = [
    "CAPABILITY_SCOPES",
    "PluginExecutionRequest",
    "PluginExecutionResult",
    "PluginExecutionSandbox",
    "PLUGIN_SANDBOX_BACKENDS",
    "normalize_sandbox_backend",
    "plugin_execution_policy",
]
