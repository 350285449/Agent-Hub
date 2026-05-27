# Plugins

Agent Hub includes a plugin SDK foundation for local, community-owned
extensions. This pass is manifest-only and safe by default.

Supported manifest types:

- `provider`
- `tool`
- `workflow`
- `router_strategy`
- `memory_context`

Local plugin directories:

```json
{
  "plugins_enabled": true,
  "plugin_dirs": [".agent-hub/plugins"],
  "enabled_plugins": ["provider.demo"],
  "trusted_plugins": ["provider.demo"],
  "disabled_plugins": [],
  "plugin_trust_registry": ".agent-hub/plugin-trust.json",
  "plugin_signature_key_env": "AGENT_HUB_PLUGIN_SIGNATURE_KEY",
  "plugin_allow_unsigned": false,
  "plugin_execution_enabled": false,
  "plugin_capability_grants": {
    "provider.demo": ["provider.read", "network.call"]
  }
}
```

Manifest filenames can be `agent-hub-plugin.json`, `plugin.json`, or
`.agent-hub-plugin.json`.

Example:

```json
{
  "id": "provider.demo",
  "name": "Demo Provider",
  "type": "provider",
  "version": "0.1.0",
  "entrypoint": "provider.py",
  "enabled_by_default": false,
  "permissions": ["network"]
}
```

Discovery validates JSON, manifest keys, plugin type, duplicate IDs, and
whether entrypoints stay inside the configured plugin directory. Agent Hub does
not execute plugin code yet. Only plugins listed in `trusted_plugins` can
register manifest metadata for provider, tool, workflow, router strategy, or
memory/context capabilities. Inspect loaded manifests and registered metadata
with `GET /v1/plugins`.

Phase 7 also supports a trust registry lifecycle. A registry entry can set
`status` to `trusted`, `disabled`, `revoked`, or `expired`; can pin `id`,
`version`, `manifest_hash`, `issued_at`, and `expires_at`; can include optional
publisher fields `publisher_id`, `publisher_name`, and `verified_publisher`;
and can grant capability scopes such as
`provider.read`, `provider.call`, `tool.register`, `workflow.register`,
`memory.read`, `memory.write`, `filesystem.read`, `filesystem.write`, and
`network.call`. Unsigned entries without a hash are rejected unless
`plugin_allow_unsigned` is explicitly enabled.

Plugin execution remains disabled by default. The sandbox interface checks
requested scopes against configured grants and then denies execution unless
`plugin_execution_enabled` is enabled. Future sandbox backends are named
`disabled`, `local_process`, `docker`, and `wasm`, but unrestricted third-party
imports are not run by Agent Hub.
