from __future__ import annotations

from typing import Any

from ..config import HubConfig
from ..observability import record_event
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
    if not bool(getattr(config, "workspace_trusted", True)):
        result = _denied(plugin_id, action, "workspace_untrusted")
        _record_plugin_audit(config, result)
        return result
    discovered = next(
        (plugin for plugin in discover_plugins(config).plugins if plugin.manifest.id == plugin_id),
        None,
    )
    if discovered is None:
        result = _denied(plugin_id, action, "plugin_not_found")
        _record_plugin_audit(config, result)
        return result
    normalized_action = str(action or "execute").strip().lower()
    if normalized_action in {"validate", "preflight", "dry_run", "dry-run"}:
        result = _validate_plugin(discovered, action, requested_scopes=requested_scopes)
        _record_plugin_audit(config, result)
        return result
    if not discovered.enabled:
        result = _denied(plugin_id, action, "plugin_disabled")
        _record_plugin_audit(config, result)
        return result
    if not discovered.trusted:
        result = _denied(plugin_id, action, "plugin_untrusted")
        _record_plugin_audit(config, result)
        return result
    sandbox_policy = discovered.sandbox
    if not sandbox_policy.get("code_execution"):
        result = _denied(plugin_id, action, "plugin_execution_disabled")
        _record_plugin_audit(config, result)
        return result
    sandbox = PluginExecutionSandbox(
        execution_enabled=True,
        granted_scopes=list(sandbox_policy.get("capability_scopes") or []),
        backend=str(sandbox_policy.get("backend") or "disabled"),
        entrypoint=sandbox_policy.get("entrypoint"),
    )
    result = sandbox.execute(
        PluginExecutionRequest(
            plugin_id=plugin_id,
            action=action,
            requested_scopes=list(requested_scopes or []),
            payload=dict(payload or {}),
        )
    )
    _record_plugin_audit(config, result)
    return result


def _record_plugin_audit(config: HubConfig, result: PluginExecutionResult) -> None:
    event = {
        "type": "audit",
        "action": "plugin_invoked",
        "plugin_id": result.plugin_id,
        "plugin_action": result.action,
        "ok": result.ok,
        "reason": result.reason,
        "backend": result.backend,
        "denied": not result.ok,
    }
    record_event(config.state_dir, "plugin_audit", event)
    record_event(config.state_dir, "audit", event)


def _denied(plugin_id: str, action: str, reason: str) -> PluginExecutionResult:
    return PluginExecutionResult(
        ok=False,
        reason=reason,
        plugin_id=plugin_id,
        action=action,
    )


def _validate_plugin(
    discovered: Any,
    action: str,
    *,
    requested_scopes: list[str] | None = None,
) -> PluginExecutionResult:
    sandbox = discovered.sandbox if isinstance(discovered.sandbox, dict) else {}
    granted_scopes = [
        str(scope)
        for scope in sandbox.get("capability_scopes", [])
        if isinstance(scope, str)
    ]
    requested = [str(scope) for scope in requested_scopes or [] if isinstance(scope, str)]
    missing_scopes = [scope for scope in requested if scope not in granted_scopes]
    checks = {
        "manifest_loaded": True,
        "enabled": bool(discovered.enabled),
        "trusted": bool(discovered.trusted),
        "registerable": bool(discovered.registerable),
        "entrypoint_stays_in_plugin_dir": bool(sandbox.get("entrypoint_allowed", True)),
        "requested_scopes_granted": not missing_scopes,
    }
    execution_would_run = bool(
        checks["enabled"]
        and checks["trusted"]
        and checks["entrypoint_stays_in_plugin_dir"]
        and sandbox.get("code_execution")
        and not missing_scopes
    )
    ok = bool(
        checks["manifest_loaded"]
        and checks["enabled"]
        and checks["trusted"]
        and checks["entrypoint_stays_in_plugin_dir"]
        and not missing_scopes
    )
    return PluginExecutionResult(
        ok=ok,
        reason="plugin_validated" if ok else "plugin_validation_failed",
        plugin_id=discovered.manifest.id,
        action=action,
        granted_scopes=granted_scopes,
        backend=str(sandbox.get("backend") or "disabled"),
        output={
            "checks": checks,
            "manifest": discovered.manifest.to_dict(),
            "registration_reason": discovered.registration_reason,
            "sandbox": sandbox,
            "requested_scopes": requested,
            "missing_scopes": missing_scopes,
            "execution_would_run": execution_would_run,
            "execute_endpoint": f"/v1/plugins/{discovered.manifest.id}/execute",
        },
    )


__all__ = ["execute_plugin"]
