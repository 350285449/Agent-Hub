from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import HubConfig
from .sandbox import PluginExecutionSandbox
from .models import (
    MANIFEST_NAMES,
    PLUGIN_TYPES,
    DiscoveredPlugin,
    PluginDiscoveryResult,
    PluginLoadError,
    PluginManifest,
)
from .trust import evaluate_plugin_trust, normalize_capability_scopes
from .trust import manifest_hash_from_data


def discover_plugins(config: HubConfig) -> PluginDiscoveryResult:
    directories = plugin_directories(config)
    result = PluginDiscoveryResult(directories=directories)
    if not getattr(config, "plugins_enabled", True):
        return result
    seen: set[str] = set()
    for directory in directories:
        if not directory.exists():
            continue
        try:
            candidates = list(_manifest_candidates(directory))
        except OSError as exc:
            result.errors.append(PluginLoadError(path=directory, message=str(exc)))
            continue
        for path in candidates:
            loaded = load_plugin_manifest(path, root=directory)
            if isinstance(loaded, PluginLoadError):
                result.errors.append(loaded)
                continue
            if loaded.id in seen:
                result.errors.append(PluginLoadError(path=path, message=f"Duplicate plugin id {loaded.id!r}"))
                continue
            seen.add(loaded.id)
            enabled = _plugin_enabled(config, loaded)
            trust = evaluate_plugin_trust(config, loaded)
            sandbox = plugin_sandbox_policy(
                loaded,
                root=directory,
                granted_scopes=trust.granted_scopes,
                execution_enabled=bool(getattr(config, "plugin_execution_enabled", False)),
            )
            registerable, reason = _registration_status(enabled, trust.trusted, sandbox, trust.reason)
            result.plugins.append(
                DiscoveredPlugin(
                    manifest=loaded,
                    enabled=enabled,
                    trusted=trust.trusted,
                    registerable=registerable,
                    registration_reason=reason,
                    sandbox=sandbox,
                    trust=trust.to_dict(),
                )
            )
    result.plugins.sort(key=lambda plugin: plugin.manifest.id)
    return result


def plugin_directories(config: HubConfig) -> list[Path]:
    configured = [Path(path).expanduser().resolve() for path in getattr(config, "plugin_dirs", [])]
    local = (Path(config.workspace_dir) / ".agent-hub" / "plugins").expanduser().resolve()
    paths: list[Path] = []
    for path in [*configured, local]:
        if path not in paths:
            paths.append(path)
    return paths


def load_plugin_manifest(path: str | Path, *, root: str | Path | None = None) -> PluginManifest | PluginLoadError:
    manifest_path = Path(path).expanduser().resolve()
    root_path = Path(root).expanduser().resolve() if root is not None else manifest_path.parent
    if not _within(manifest_path, root_path):
        return PluginLoadError(path=manifest_path, message="Manifest escapes configured plugin directory")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return PluginLoadError(path=manifest_path, message=str(exc))
    except json.JSONDecodeError as exc:
        return PluginLoadError(path=manifest_path, message=f"Invalid JSON: {exc.msg}")
    if not isinstance(data, dict):
        return PluginLoadError(path=manifest_path, message="Manifest must be a JSON object")
    try:
        return _manifest_from_dict(data, manifest_path)
    except ValueError as exc:
        return PluginLoadError(path=manifest_path, message=str(exc))


def plugin_sandbox_policy(
    manifest: PluginManifest,
    *,
    root: str | Path,
    granted_scopes: list[str] | None = None,
    execution_enabled: bool = False,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    entrypoint = None
    entrypoint_allowed = False
    if manifest.entrypoint:
        candidate = (manifest.path.parent / manifest.entrypoint).resolve() if manifest.path else root_path
        entrypoint = str(candidate)
        entrypoint_allowed = _within(candidate, root_path)
    else:
        entrypoint_allowed = True
    scopes = normalize_capability_scopes(granted_scopes or [])
    execution = PluginExecutionSandbox(
        execution_enabled=execution_enabled,
        granted_scopes=scopes,
    )
    return {
        "manifest_only": True,
        "code_execution": False,
        "execution_enabled": execution.execution_enabled,
        "root": str(root_path),
        "entrypoint": entrypoint,
        "entrypoint_allowed": entrypoint_allowed,
        "allowed_permissions": list(manifest.permissions),
        "capability_scopes": scopes,
    }


def _manifest_candidates(directory: Path) -> list[Path]:
    candidates: list[Path] = []
    for name in MANIFEST_NAMES:
        direct = directory / name
        if direct.exists():
            candidates.append(direct)
    for child in directory.iterdir():
        if not child.is_dir():
            continue
        for name in MANIFEST_NAMES:
            candidate = child / name
            if candidate.exists():
                candidates.append(candidate)
                break
    return candidates


def _manifest_from_dict(data: dict[str, Any], path: Path) -> PluginManifest:
    allowed = {
        "id",
        "name",
        "type",
        "version",
        "enabled_by_default",
        "entrypoint",
        "description",
        "permissions",
        "metadata",
        "signature",
        "manifest_hash",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"Unknown manifest keys: {', '.join(unknown)}")
    plugin_id = str(data.get("id") or data.get("name") or "").strip()
    if not plugin_id:
        raise ValueError("Plugin id is required")
    if not _safe_plugin_id(plugin_id):
        raise ValueError("Plugin id may only contain letters, numbers, dots, underscores, and dashes")
    plugin_type = str(data.get("type") or "").strip().lower().replace("-", "_")
    if plugin_type not in PLUGIN_TYPES:
        raise ValueError(f"Plugin type must be one of {', '.join(sorted(PLUGIN_TYPES))}")
    name = str(data.get("name") or plugin_id).strip()
    if data.get("permissions") is not None and not isinstance(data.get("permissions"), list):
        raise ValueError("Plugin permissions must be an array of strings")
    if data.get("metadata") is not None and not isinstance(data.get("metadata"), dict):
        raise ValueError("Plugin metadata must be an object")
    if data.get("entrypoint") is not None and not isinstance(data.get("entrypoint"), str):
        raise ValueError("Plugin entrypoint must be a relative path string")
    permissions = [
        str(permission)
        for permission in data.get("permissions", [])
        if isinstance(permission, str) and permission.strip()
    ]
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return PluginManifest(
        id=plugin_id,
        name=name,
        type=plugin_type,
        version=str(data.get("version") or "0.1.0"),
        enabled_by_default=bool(data.get("enabled_by_default", False)),
        entrypoint=str(data.get("entrypoint")) if data.get("entrypoint") else None,
        signature=str(data.get("signature") or ""),
        description=str(data.get("description") or ""),
        permissions=permissions,
        metadata=dict(metadata),
        manifest_hash=manifest_hash_from_data(data),
        path=path,
    )


def _plugin_enabled(config: HubConfig, manifest: PluginManifest) -> bool:
    disabled = set(getattr(config, "disabled_plugins", []) or [])
    enabled = set(getattr(config, "enabled_plugins", []) or [])
    if manifest.id in disabled:
        return False
    if enabled:
        return manifest.id in enabled
    return manifest.enabled_by_default


def _registration_status(
    enabled: bool,
    trusted: bool,
    sandbox: dict[str, Any],
    trust_reason: str = "",
) -> tuple[bool, str]:
    if not enabled:
        return False, "plugin_disabled"
    if not trusted:
        return False, trust_reason or "plugin_untrusted"
    if not bool(sandbox.get("entrypoint_allowed")):
        return False, "entrypoint_escapes_plugin_directory"
    return True, trust_reason or "trusted_manifest_metadata_registered"


def _safe_plugin_id(value: str) -> bool:
    return bool(value) and all(
        character.isalnum() or character in {".", "_", "-"}
        for character in value
    )


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


__all__ = [
    "discover_plugins",
    "load_plugin_manifest",
    "plugin_directories",
    "plugin_sandbox_policy",
]
