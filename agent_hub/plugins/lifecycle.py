from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .discovery import load_plugin_manifest
from .models import MANIFEST_NAMES, PluginLoadError, PluginManifest


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
        source_root, manifest_path = _source_manifest_path(Path(source))
        if manifest_path is None:
            return PluginLifecycleResult(False, "install", "", str(source), "plugin_manifest_not_found")
        loaded = load_plugin_manifest(manifest_path, root=source_root)
        if isinstance(loaded, PluginLoadError):
            return PluginLifecycleResult(False, "install", "", str(source_root), f"invalid_manifest: {loaded.message}")
        manifest = loaded
        plugin_id = manifest.id
        target = self.plugin_dir / _safe_plugin_id(plugin_id)
        if target.exists():
            return PluginLifecycleResult(False, "install", plugin_id, str(target), "plugin_already_installed")
        shutil.copytree(source_root, target)
        self._write_state(plugin_id, {"enabled": bool(manifest.enabled_by_default), "installed": True})
        return PluginLifecycleResult(
            True,
            "install",
            plugin_id,
            str(target),
            "plugin_installed",
            _manifest_audit(manifest),
        )

    def enable(self, plugin_id: str) -> PluginLifecycleResult:
        return self._set_enabled(plugin_id, True)

    def disable(self, plugin_id: str) -> PluginLifecycleResult:
        return self._set_enabled(plugin_id, False)

    def audit(self, plugin_id: str) -> PluginLifecycleResult:
        path = self.plugin_dir / _safe_plugin_id(plugin_id)
        if not path.exists():
            return PluginLifecycleResult(False, "audit", plugin_id, str(path), "plugin_not_installed")
        source_root, manifest_path = _source_manifest_path(path)
        loaded = load_plugin_manifest(manifest_path, root=source_root) if manifest_path is not None else {}
        manifest = loaded if isinstance(loaded, PluginManifest) else None
        state = self._read_state(plugin_id)
        audit = {
            "manifest_present": manifest is not None,
            "id": manifest.id if manifest else plugin_id,
            "type": manifest.type if manifest else "",
            "version": manifest.version if manifest else "",
            "manifest_hash": manifest.manifest_hash if manifest else "",
            "entrypoint": manifest.entrypoint if manifest else None,
            "permissions": list(manifest.permissions) if manifest else [],
            "enabled": bool(state.get("enabled")),
            "code_execution": bool(manifest and manifest.entrypoint),
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


def _source_manifest_path(source: Path) -> tuple[Path, Path | None]:
    source_path = source.expanduser().resolve()
    if source_path.is_file():
        return source_path.parent, source_path if source_path.name in MANIFEST_NAMES else None
    for name in MANIFEST_NAMES:
        manifest = source_path / name
        if manifest.exists():
            return source_path, manifest
    return source_path, None


def _manifest_audit(manifest: PluginManifest) -> dict[str, Any]:
    return {
        "manifest_present": True,
        "id": manifest.id,
        "name": manifest.name,
        "type": manifest.type,
        "version": manifest.version,
        "manifest_hash": manifest.manifest_hash,
        "entrypoint": manifest.entrypoint,
        "permissions": list(manifest.permissions),
        "enabled_by_default": manifest.enabled_by_default,
    }


def _safe_plugin_id(plugin_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in plugin_id)[:120] or "plugin"
