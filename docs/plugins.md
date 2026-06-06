# Plugins

Agent Hub includes a plugin SDK foundation for local, community-owned
extensions. Discovery is manifest-first and safe by default; trusted plugins
can opt into bounded local-process JSON execution.

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
whether entrypoints stay inside the configured plugin directory. Only plugins
listed in `trusted_plugins` can register manifest metadata for provider, tool,
workflow, router strategy, or memory/context capabilities. Inspect loaded
manifests, registered metadata, capability coverage, runtime contract details,
and operational readiness with `GET /v1/plugins`.

Safe validation is available without running plugin code:

```sh
curl -X POST http://127.0.0.1:8787/v1/plugins/tool.demo/execute \
  -H "Content-Type: application/json" \
  -d '{"action":"validate","requested_scopes":["tool.register"]}'
```

The validation response reports enabled/trusted/registerable state, sandbox
policy, missing scopes, entrypoint containment, and whether execution would run
if `action="execute"` were requested. This is the recommended first step before
enabling code execution.

Phase 7 also supports a trust registry lifecycle. A registry entry can set
`status` to `trusted`, `disabled`, `revoked`, or `expired`; can pin `id`,
`version`, `manifest_hash`, `issued_at`, and `expires_at`; can include optional
publisher fields `publisher_id`, `publisher_name`, and `verified_publisher`;
and can grant capability scopes such as
`provider.read`, `provider.call`, `tool.register`, `workflow.register`,
`memory.read`, `memory.write`, `filesystem.read`, `filesystem.write`, and
`network.call`. Unsigned entries without a hash are rejected unless
`plugin_allow_unsigned` is explicitly enabled.

Plugin execution remains disabled by default. When `plugin_execution_enabled`
is true, a plugin is trusted, its entrypoint stays inside the plugin directory,
and requested scopes are granted, Agent Hub can run a bounded `local_process`
plugin contract. The entrypoint receives JSON on stdin:

```json
{
  "plugin_id": "tool.demo",
  "action": "run",
  "granted_scopes": ["tool.register"],
  "payload": {"value": "hello"}
}
```

It should return JSON on stdout. Python and Node entrypoints are supported; the
process is launched without a shell. Future sandbox backend names remain
`disabled`, `docker`, and `wasm`, but only `local_process` executes today.
