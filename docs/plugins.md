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
  "disabled_plugins": []
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

Discovery validates JSON, plugin type, duplicate IDs, and whether entrypoints
stay inside the configured plugin directory. Agent Hub does not execute plugin
code yet. Inspect loaded manifests with `GET /v1/plugins`.
