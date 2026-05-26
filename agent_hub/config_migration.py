from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ConfigMigration:
    old_key: str
    new_key: str
    reason: str
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "old_key": self.old_key,
            "new_key": self.new_key,
            "reason": self.reason,
            "applied": self.applied,
        }


def detect_config_migrations(data: dict[str, Any]) -> list[ConfigMigration]:
    _migrated, migrations = migrate_config_data(data, apply=False)
    return migrations


def migrate_config_data(data: dict[str, Any], *, apply: bool = True) -> tuple[dict[str, Any], list[ConfigMigration]]:
    migrated = dict(data)
    migrations: list[ConfigMigration] = []

    _move_key(
        migrated,
        migrations,
        "shell_tools_policy",
        "shell_command_policy",
        "Shell policy was renamed when tool permissions were centralized.",
        apply=apply,
    )
    _move_key(
        migrated,
        migrations,
        "stream_failure_policy",
        "native_stream_failure_policy",
        "Native streaming recovery policy is now explicit.",
        apply=apply,
    )
    _move_key(
        migrated,
        migrations,
        "plugins_allowlist",
        "trusted_plugins",
        "Plugin trust now uses explicit trusted plugin IDs or a trust registry.",
        apply=apply,
    )
    _move_key(
        migrated,
        migrations,
        "max_prompt_tokens",
        "max_context_tokens",
        "Prompt budgeting is now expressed as a context-token ceiling.",
        apply=apply,
    )

    enterprise = migrated.get("enterprise")
    if isinstance(enterprise, dict):
        mapping = {
            "enabled": "enterprise_mode_enabled",
            "default_workspace_id": "enterprise_default_workspace_id",
            "users": "enterprise_users",
            "workspaces": "enterprise_workspaces",
            "roles": "enterprise_roles",
            "grants": "enterprise_permission_grants",
        }
        for old, new in mapping.items():
            if old not in enterprise:
                continue
            migrations.append(
                ConfigMigration(
                    old_key=f"enterprise.{old}",
                    new_key=new,
                    reason="Enterprise policy config is now flat HubConfig data.",
                    applied=apply and new not in migrated,
                )
            )
            if apply and new not in migrated:
                migrated[new] = enterprise[old]
        if apply:
            migrated.pop("enterprise", None)

    return migrated, migrations


def migrate_config_file(
    path: str | Path,
    *,
    output_path: str | Path | None = None,
    write: bool = False,
) -> dict[str, Any]:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Agent Hub config must be a JSON object")
    migrated, migrations = migrate_config_data(raw, apply=True)
    target = Path(output_path) if output_path is not None else source
    if write:
        target.write_text(json.dumps(migrated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "path": str(source),
        "output_path": str(target),
        "changed": migrated != raw,
        "migrations": [migration.to_dict() for migration in migrations],
        "config": migrated,
    }


def _move_key(
    data: dict[str, Any],
    migrations: list[ConfigMigration],
    old_key: str,
    new_key: str,
    reason: str,
    *,
    apply: bool,
) -> None:
    if old_key not in data:
        return
    applied = apply and new_key not in data
    migrations.append(ConfigMigration(old_key=old_key, new_key=new_key, reason=reason, applied=applied))
    if apply:
        if new_key not in data:
            data[new_key] = data[old_key]
        data.pop(old_key, None)


__all__ = [
    "ConfigMigration",
    "detect_config_migrations",
    "migrate_config_data",
    "migrate_config_file",
]
