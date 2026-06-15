from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .commands_config import _load_or_default_config_dict, _write_config_dict
from .config import HubConfig
from .plugins import PluginLifecycleManager
from .plugins.trust import normalize_capability_scopes


def _install_plugin(
    config: HubConfig,
    config_path: str,
    source: str,
    *,
    enable: bool = False,
    trust: bool = False,
    scopes: list[str] | None = None,
    as_json: bool = False,
) -> int:
    """Install a local plugin directory into the workspace plugin store."""

    manager = PluginLifecycleManager(Path(config.workspace_dir) / ".agent-hub" / "plugins")
    result = manager.install(source)
    if not result.ok:
        body = result.to_dict()
        if as_json:
            print(json.dumps(body, indent=2, ensure_ascii=False))
        else:
            print(f"Plugin install failed: {result.reason}")
        return 1

    plugin_id = result.plugin_id
    if enable:
        manager.enable(plugin_id)
    config_update = _update_plugin_config(
        Path(config_path),
        plugin_id,
        enable=enable,
        trust=trust,
        scopes=scopes or [],
    )
    body = {
        **result.to_dict(),
        "enabled": enable,
        "trusted": trust,
        "config": config_update,
        "next_steps": _plugin_next_steps(plugin_id, enable=enable, trust=trust),
    }
    if as_json:
        print(json.dumps(body, indent=2, ensure_ascii=False))
    else:
        print(f"Installed plugin {plugin_id} -> {result.path}")
        if enable:
            print("enabled: yes")
        if trust:
            print("trusted: yes")
        if config_update.get("scopes"):
            print("scopes: " + ", ".join(config_update["scopes"]))
        print("Run `agent-hub doctor --json` or GET /v1/plugins to inspect registration.")
    return 0


def _update_plugin_config(
    config_path: Path,
    plugin_id: str,
    *,
    enable: bool,
    trust: bool,
    scopes: list[str],
) -> dict[str, Any]:
    data = _load_or_default_config_dict(config_path)
    data["plugins_enabled"] = True
    if enable:
        _append_unique_string(data, "enabled_plugins", plugin_id)
        _remove_string(data, "disabled_plugins", plugin_id)
    if trust:
        _append_unique_string(data, "trusted_plugins", plugin_id)
    normalized_scopes = normalize_capability_scopes(scopes)
    if normalized_scopes:
        grants = data.setdefault("plugin_capability_grants", {})
        if not isinstance(grants, dict):
            data["plugin_capability_grants"] = grants = {}
        existing = [
            str(item)
            for item in grants.get(plugin_id, [])
            if isinstance(item, str)
        ]
        grants[plugin_id] = normalize_capability_scopes([*existing, *normalized_scopes])
    _write_config_dict(config_path, data)
    return {
        "path": str(config_path),
        "plugins_enabled": True,
        "enabled": enable,
        "trusted": trust,
        "scopes": normalized_scopes,
    }


def _append_unique_string(data: dict[str, Any], key: str, value: str) -> None:
    values = data.setdefault(key, [])
    if not isinstance(values, list):
        data[key] = values = []
    if value not in values:
        values.append(value)


def _remove_string(data: dict[str, Any], key: str, value: str) -> None:
    values = data.get(key)
    if isinstance(values, list):
        data[key] = [item for item in values if item != value]


def _plugin_next_steps(plugin_id: str, *, enable: bool, trust: bool) -> list[str]:
    steps: list[str] = []
    if not enable:
        steps.append(f"Enable with `agent-hub install <path> --enable` or add {plugin_id!r} to enabled_plugins.")
    if not trust:
        steps.append(f"Trust only after review by adding {plugin_id!r} to trusted_plugins or a trust registry.")
    steps.append("Plugin code execution remains disabled unless plugin_execution_enabled is true and scopes are granted.")
    return steps


__all__ = ["_install_plugin"]
