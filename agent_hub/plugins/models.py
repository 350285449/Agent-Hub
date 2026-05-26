from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PLUGIN_TYPES = {
    "provider",
    "tool",
    "workflow",
    "router_strategy",
    "memory_context",
}
MANIFEST_NAMES = ("agent-hub-plugin.json", "plugin.json", ".agent-hub-plugin.json")


@dataclass(slots=True)
class PluginManifest:
    id: str
    name: str
    type: str
    version: str = "0.1.0"
    enabled_by_default: bool = False
    entrypoint: str | None = None
    description: str = ""
    permissions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "version": self.version,
            "enabled_by_default": self.enabled_by_default,
            "description": self.description,
            "permissions": list(self.permissions),
            "metadata": dict(self.metadata),
        }
        if self.entrypoint:
            data["entrypoint"] = self.entrypoint
        if self.path is not None:
            data["path"] = str(self.path)
        return data


@dataclass(slots=True)
class PluginLoadError:
    path: Path
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": str(self.path), "message": self.message}


@dataclass(slots=True)
class DiscoveredPlugin:
    manifest: PluginManifest
    enabled: bool
    sandbox: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.manifest.to_dict(),
            "enabled": self.enabled,
            "sandbox": dict(self.sandbox),
        }


@dataclass(slots=True)
class PluginDiscoveryResult:
    plugins: list[DiscoveredPlugin] = field(default_factory=list)
    errors: list[PluginLoadError] = field(default_factory=list)
    directories: list[Path] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.plugins",
            "directories": [str(path) for path in self.directories],
            "plugins": [plugin.to_dict() for plugin in self.plugins],
            "errors": [error.to_dict() for error in self.errors],
            "count": len(self.plugins),
            "enabled_count": sum(1 for plugin in self.plugins if plugin.enabled),
        }


__all__ = [
    "DiscoveredPlugin",
    "MANIFEST_NAMES",
    "PLUGIN_TYPES",
    "PluginDiscoveryResult",
    "PluginLoadError",
    "PluginManifest",
]
