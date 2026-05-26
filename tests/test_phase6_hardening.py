from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.config_migration import migrate_config_data, migrate_config_file
from agent_hub.enterprise import EnterprisePolicy, enterprise_audit_events
from agent_hub.observability import record_event
from agent_hub.permissions import PermissionManager, PermissionRequest
from agent_hub.plugins import PluginExecutionRequest, PluginExecutionSandbox, discover_plugins, manifest_hash_from_data
from agent_hub.server import AgentHubHTTPServer


class PhaseSixPluginTrustTests(unittest.TestCase):
    def test_trust_registry_hash_allows_metadata_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {
                "id": "provider.signed",
                "name": "Signed Provider",
                "type": "provider",
                "version": "1.0.0",
                "enabled_by_default": True,
                "metadata": {"models": ["signed-model"]},
            }
            plugin_dir = root / "plugins" / "signed"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
            registry = {
                "plugins": {
                    "provider.signed": {
                        "version": "1.0.0",
                        "manifest_hash": manifest_hash_from_data(manifest),
                        "trusted": True,
                        "capability_scopes": ["provider.read", "network.call"],
                    }
                }
            }
            registry_path = root / "trust-registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
                plugin_trust_registry=registry_path,
            )

            body = discover_plugins(config).to_dict()

            self.assertEqual(body["registered_count"], 1)
            plugin = body["plugins"][0]
            self.assertTrue(plugin["trusted"])
            self.assertEqual(plugin["trust"]["source"], "trust_registry")
            self.assertEqual(plugin["sandbox"]["capability_scopes"], ["provider.read", "network.call"])

    def test_trust_registry_hash_mismatch_blocks_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "signed"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "tool.signed",
                        "name": "Signed Tool",
                        "type": "tool",
                        "version": "1.0.0",
                        "enabled_by_default": True,
                    }
                ),
                encoding="utf-8",
            )
            registry_path = root / "trust-registry.json"
            registry_path.write_text(
                json.dumps({"plugins": {"tool.signed": {"manifest_hash": "sha256:bad", "trusted": True}}}),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
                plugin_trust_registry=registry_path,
            )

            body = discover_plugins(config).to_dict()

            self.assertEqual(body["registered_count"], 0)
            self.assertEqual(body["plugins"][0]["registration_reason"], "plugin_trust_registry_hash_mismatch")

    def test_plugin_execution_interface_denies_by_default_and_checks_scopes(self) -> None:
        sandbox = PluginExecutionSandbox(
            execution_enabled=False,
            granted_scopes=["provider.read"],
        )

        disabled = sandbox.execute(
            PluginExecutionRequest(
                plugin_id="provider.signed",
                action="inspect",
                requested_scopes=["provider.read"],
            )
        )
        denied = sandbox.execute(
            PluginExecutionRequest(
                plugin_id="provider.signed",
                action="call",
                requested_scopes=["provider.call"],
            )
        )

        self.assertFalse(disabled.ok)
        self.assertEqual(disabled.reason, "plugin_execution_disabled")
        self.assertFalse(denied.ok)
        self.assertEqual(denied.reason, "plugin_capability_scope_denied")


class PhaseSixEnterpriseAuditTests(unittest.TestCase):
    def test_enterprise_audit_logs_allow_and_deny_with_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                enterprise_mode_enabled=True,
                enterprise_users=[{"id": "alice", "roles": ["writer"]}],
                enterprise_roles=[{"name": "writer", "permissions": ["file_write"]}],
            )
            policy = EnterprisePolicy.from_config(config)
            request = PermissionRequest(
                action="write_file",
                category="file_write",
                description="Write a file",
                resource="Authorization: Bearer audit-secret-token",
            )

            allowed = PermissionManager(
                "auto",
                enterprise_policy=policy,
                enterprise_user_id="alice",
                enterprise_workspace_id="default",
            ).check(request)
            denied = PermissionManager(
                "auto",
                enterprise_policy=policy,
                enterprise_user_id="bob",
                enterprise_workspace_id="default",
            ).check(request)
            events = enterprise_audit_events(config.state_dir)
            combined = json.dumps(events)

            self.assertTrue(allowed.allowed)
            self.assertFalse(denied.allowed)
            self.assertEqual([event["allowed"] for event in events], [True, False])
            self.assertNotIn("audit-secret-token", combined)


class PhaseSixDiagnosticsTests(unittest.TestCase):
    def test_all_diagnostics_endpoints_redact_secret_like_provider_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "demo"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "provider.demo",
                        "name": "Demo",
                        "type": "provider",
                        "enabled_by_default": True,
                        "metadata": {"last_error": "Bearer plugin-secret-token"},
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
                trusted_plugins=["provider.demo"],
                agents={
                    "cloud": AgentConfig(
                        name="cloud",
                        provider="openai-compatible",
                        model="cloud-model",
                        base_url="https://example.invalid/v1",
                        api_key="sk-provider-secret-123456789",
                    )
                },
                default_route=["cloud"],
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            server.router._record_failure(
                config.agents["cloud"],
                error_type="provider_error",
                message="Provider said Authorization: Bearer provider-secret-token and sk-provider-secret-123456789",
            )
            for stream in ("events", "workflows", "enterprise_audit"):
                record_event(
                    config.state_dir,
                    stream,
                    {
                        "type": "malicious_provider_error",
                        "message": "x-api-key=provider-secret-token and ghp_providersecret123456",
                    },
                )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                combined = "\n".join(
                    json.dumps(_get_json(f"{base}{path}"))
                    for path in (
                        "/v1/provider-health",
                        "/v1/events",
                        "/v1/tools",
                        "/v1/workflows/status",
                        "/v1/plugins",
                        "/v1/enterprise/audit",
                    )
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertNotIn("provider-secret-token", combined)
            self.assertNotIn("sk-provider-secret-123456789", combined)
            self.assertNotIn("ghp_providersecret123456", combined)
            self.assertIn("[REDACTED]", combined)


class PhaseSixConfigMigrationTests(unittest.TestCase):
    def test_config_migration_detects_and_writes_deprecated_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "shell_tools_policy": "deny",
                        "stream_failure_policy": "fallback_provider",
                        "plugins_allowlist": ["provider.demo"],
                        "enterprise": {
                            "enabled": True,
                            "users": [{"id": "alice"}],
                            "roles": [{"name": "admin", "permissions": ["*"]}],
                        },
                    }
                ),
                encoding="utf-8",
            )

            migrated, migrations = migrate_config_data(json.loads(path.read_text(encoding="utf-8")))
            report = migrate_config_file(path, write=True)
            saved = json.loads(path.read_text(encoding="utf-8"))

            self.assertGreaterEqual(len(migrations), 3)
            self.assertEqual(migrated["shell_command_policy"], "deny")
            self.assertEqual(migrated["native_stream_failure_policy"], "fallback_provider")
            self.assertEqual(migrated["trusted_plugins"], ["provider.demo"])
            self.assertTrue(saved["enterprise_mode_enabled"])
            self.assertTrue(report["changed"])


def _get_json(url: str) -> dict:
    request = Request(url)
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
