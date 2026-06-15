from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


PluginLifecycleAction = Literal["install", "enable", "disable", "audit", "remove"]


@dataclass(slots=True)
class PluginLifecycleResult:
    ok: bool
    action: PluginLifecycleAction
    plugin_id: str
    path: str = ""
    reason: str = ""
    audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.plugin_lifecycle",
            "ok": self.ok,
            "action": self.action,
            "plugin_id": self.plugin_id,
            "path": self.path,
            "reason": self.reason,
            "audit": dict(self.audit),
        }


class PluginLifecycleManager:
    """Local plugin lifecycle manager with manifest-first safety checks."""

    def __init__(self, plugin_dir: str | Path) -> None:
        self.plugin_dir = Path(plugin_dir)
        self.plugin_dir.mkdir(parents=True, exist_ok=True)

    def install(self, source: str | Path) -> PluginLifecycleResult:
        source_path = Path(source)
        manifest = _read_manifest(source_path)
        plugin_id = str(manifest.get("id") or source_path.name)
        target = self.plugin_dir / _safe_plugin_id(plugin_id)
        if target.exists():
            return PluginLifecycleResult(False, "install", plugin_id, str(target), "plugin_already_installed")
        shutil.copytree(source_path, target)
        self._write_state(plugin_id, {"enabled": bool(manifest.get("enabled_by_default")), "installed": True})
        return PluginLifecycleResult(True, "install", plugin_id, str(target), "plugin_installed")

    def enable(self, plugin_id: str) -> PluginLifecycleResult:
        return self._set_enabled(plugin_id, True)

    def disable(self, plugin_id: str) -> PluginLifecycleResult:
        return self._set_enabled(plugin_id, False)

    def audit(self, plugin_id: str) -> PluginLifecycleResult:
        path = self.plugin_dir / _safe_plugin_id(plugin_id)
        if not path.exists():
            return PluginLifecycleResult(False, "audit", plugin_id, str(path), "plugin_not_installed")
        manifest = _read_manifest(path)
        state = self._read_state(plugin_id)
        audit = {
            "manifest_present": bool(manifest),
            "entrypoint": manifest.get("entrypoint"),
            "permissions": list(manifest.get("permissions") or []),
            "enabled": bool(state.get("enabled")),
            "code_execution": bool(manifest.get("entrypoint")),
        }
        return PluginLifecycleResult(True, "audit", plugin_id, str(path), "plugin_audited", audit)

    def remove(self, plugin_id: str) -> PluginLifecycleResult:
        path = self.plugin_dir / _safe_plugin_id(plugin_id)
        if not path.exists():
            return PluginLifecycleResult(False, "remove", plugin_id, str(path), "plugin_not_installed")
        shutil.rmtree(path)
        self._state_path(plugin_id).unlink(missing_ok=True)
        return PluginLifecycleResult(True, "remove", plugin_id, str(path), "plugin_removed")

    def _set_enabled(self, plugin_id: str, enabled: bool) -> PluginLifecycleResult:
        path = self.plugin_dir / _safe_plugin_id(plugin_id)
        if not path.exists():
            return PluginLifecycleResult(False, "enable" if enabled else "disable", plugin_id, str(path), "plugin_not_installed")
        state = self._read_state(plugin_id)
        state["enabled"] = enabled
        state["installed"] = True
        self._write_state(plugin_id, state)
        return PluginLifecycleResult(True, "enable" if enabled else "disable", plugin_id, str(path), "plugin_enabled" if enabled else "plugin_disabled")

    def _state_path(self, plugin_id: str) -> Path:
        return self.plugin_dir / f".{_safe_plugin_id(plugin_id)}.state.json"

    def _read_state(self, plugin_id: str) -> dict[str, Any]:
        try:
            return json.loads(self._state_path(plugin_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_state(self, plugin_id: str, state: dict[str, Any]) -> None:
        self._state_path(plugin_id).write_text(json.dumps(state, indent=2), encoding="utf-8")


def _read_manifest(path: Path) -> dict[str, Any]:
    for name in ("agent-hub-plugin.json", "plugin.json", ".agent-hub-plugin.json"):
        manifest = path / name
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}
    return {}


def _safe_plugin_id(plugin_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in plugin_id)[:120] or "plugin"
