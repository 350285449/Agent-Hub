from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
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
    output: Any = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "plugin_id": self.plugin_id,
            "action": self.action,
            "granted_scopes": list(self.granted_scopes),
            "backend": self.backend,
            "output": self.output,
            "error": self.error,
        }


class PluginExecutionSandbox:
    """Deny-by-default execution interface for trusted local-process plugins."""

    def __init__(
        self,
        *,
        execution_enabled: bool = False,
        granted_scopes: list[str] | None = None,
        backend: str = "disabled",
        entrypoint: str | Path | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.execution_enabled = execution_enabled
        self.granted_scopes = normalize_capability_scopes(granted_scopes or [])
        self.backend = normalize_sandbox_backend(backend)
        self.entrypoint = Path(entrypoint).expanduser().resolve() if entrypoint else None
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 120.0))

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
        if self.backend == "local_process":
            return self._execute_local_process(request)
        return PluginExecutionResult(
            ok=False,
            reason="plugin_code_execution_not_implemented",
            plugin_id=request.plugin_id,
            action=request.action,
            granted_scopes=self.granted_scopes,
            backend=self.backend,
        )

    def _execute_local_process(self, request: PluginExecutionRequest) -> PluginExecutionResult:
        if self.entrypoint is None or not self.entrypoint.is_file():
            return PluginExecutionResult(
                ok=False,
                reason="plugin_entrypoint_missing",
                plugin_id=request.plugin_id,
                action=request.action,
                granted_scopes=self.granted_scopes,
                backend=self.backend,
            )
        command = _entrypoint_command(self.entrypoint)
        if not command:
            return PluginExecutionResult(
                ok=False,
                reason="plugin_entrypoint_type_unsupported",
                plugin_id=request.plugin_id,
                action=request.action,
                granted_scopes=self.granted_scopes,
                backend=self.backend,
            )
        payload = {
            "plugin_id": request.plugin_id,
            "action": request.action,
            "granted_scopes": list(self.granted_scopes),
            "payload": dict(request.payload),
        }
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.entrypoint.parent),
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                shell=False,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return PluginExecutionResult(
                ok=False,
                reason="plugin_process_failed",
                plugin_id=request.plugin_id,
                action=request.action,
                granted_scopes=self.granted_scopes,
                backend=self.backend,
                error=str(exc)[:1000],
            )
        stdout = (completed.stdout or "")[:1_000_000]
        stderr = (completed.stderr or "")[:4000]
        try:
            output = json.loads(stdout) if stdout.strip() else None
        except json.JSONDecodeError:
            output = stdout
        return PluginExecutionResult(
            ok=completed.returncode == 0,
            reason="plugin_executed" if completed.returncode == 0 else "plugin_process_failed",
            plugin_id=request.plugin_id,
            action=request.action,
            granted_scopes=self.granted_scopes,
            backend=self.backend,
            output=output,
            error=stderr,
        )


def plugin_execution_policy(config: Any, plugin: Any) -> dict[str, Any]:
    trust = getattr(plugin, "trust", {}) if plugin is not None else {}
    scopes = trust.get("granted_scopes") if isinstance(trust, dict) else []
    sandbox = getattr(plugin, "sandbox", {}) if plugin is not None else {}
    backend = normalize_sandbox_backend(
        sandbox.get("backend") if isinstance(sandbox, dict) else "disabled"
    )
    execution_enabled = bool(getattr(config, "plugin_execution_enabled", False))
    return {
        "execution_enabled": execution_enabled,
        "code_execution": bool(execution_enabled and backend == "local_process"),
        "capability_scopes": normalize_capability_scopes(scopes if isinstance(scopes, list) else []),
        "available_scopes": sorted(CAPABILITY_SCOPES),
        "available_backends": sorted(PLUGIN_SANDBOX_BACKENDS),
        "backend": backend,
    }


def normalize_sandbox_backend(value: Any) -> str:
    backend = str(value or "disabled").strip().lower().replace("-", "_")
    if backend in PLUGIN_SANDBOX_BACKENDS:
        return backend
    return "disabled"


def _entrypoint_command(entrypoint: Path) -> list[str]:
    suffix = entrypoint.suffix.lower()
    if suffix == ".py":
        return [sys.executable, str(entrypoint)]
    if suffix in {".js", ".mjs", ".cjs"}:
        return ["node", str(entrypoint)]
    return []


__all__ = [
    "CAPABILITY_SCOPES",
    "PluginExecutionRequest",
    "PluginExecutionResult",
    "PluginExecutionSandbox",
    "PLUGIN_SANDBOX_BACKENDS",
    "normalize_sandbox_backend",
    "plugin_execution_policy",
]
