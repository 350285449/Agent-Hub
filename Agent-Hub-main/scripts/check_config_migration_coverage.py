from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_hub.config_migration import detect_config_migrations, migrate_config_data


def main() -> int:
    legacy = {
        "shell_tools_policy": "deny",
        "stream_failure_policy": "fallback_provider",
        "plugins_allowlist": ["provider.demo"],
        "max_prompt_tokens": 4096,
        "enterprise": {
            "enabled": True,
            "default_workspace_id": "workspace-1",
            "users": [{"id": "alice"}],
            "workspaces": [{"id": "workspace-1"}],
            "roles": [{"name": "admin", "permissions": ["*"]}],
            "grants": [{"subject_id": "alice", "workspace_id": "workspace-1", "permission": "*"}],
        },
    }
    expected_new_keys = {
        "shell_command_policy",
        "native_stream_failure_policy",
        "trusted_plugins",
        "max_context_tokens",
        "enterprise_mode_enabled",
        "enterprise_default_workspace_id",
        "enterprise_users",
        "enterprise_workspaces",
        "enterprise_roles",
        "enterprise_permission_grants",
    }
    migrated, migrations = migrate_config_data(legacy)
    detected = detect_config_migrations(legacy)
    failures: list[str] = []
    missing = expected_new_keys - set(migrated)
    if missing:
        failures.append(f"missing migrated keys: {', '.join(sorted(missing))}")
    stale = {"shell_tools_policy", "stream_failure_policy", "plugins_allowlist", "max_prompt_tokens", "enterprise"} & set(migrated)
    if stale:
        failures.append(f"legacy keys were not removed: {', '.join(sorted(stale))}")
    if len(migrations) < len(expected_new_keys):
        failures.append(f"expected at least {len(expected_new_keys)} migrations, got {len(migrations)}")
    if len(detected) != len(migrations):
        failures.append("detect_config_migrations and migrate_config_data disagree on coverage")
    if failures:
        print("Config migration coverage check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Config migration coverage is current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
