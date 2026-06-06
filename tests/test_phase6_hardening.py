from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.config_migration import migrate_config_data, migrate_config_file
from agent_hub.enterprise import EnterprisePolicy, enterprise_audit_events, export_enterprise_audit
from agent_hub.observability import record_event
from agent_hub.permissions import PermissionManager, PermissionRequest
from agent_hub.plugins import CAPABILITY_SCOPES, PluginExecutionRequest, PluginExecutionSandbox, discover_plugins, execute_plugin, manifest_hash_from_data
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

    def test_trust_registry_lifecycle_statuses_are_enforced(self) -> None:
        cases = [
            ("provider.trusted", {"status": "trusted"}, True, "trusted_manifest_metadata_registered", "trusted"),
            ("provider.disabled", {"status": "disabled"}, False, "plugin_trust_registry_entry_disabled", "disabled"),
            ("provider.revoked", {"status": "revoked"}, False, "plugin_trust_registry_entry_revoked", "revoked"),
            (
                "provider.expired",
                {"expires_at": time.time() - 10},
                False,
                "plugin_trust_registry_entry_expired",
                "expired",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugins = root / "plugins"
            registry = {"plugins": {}}
            for plugin_id, entry, _trusted, _reason, _status in cases:
                manifest = {
                    "id": plugin_id,
                    "name": plugin_id,
                    "type": "provider",
                    "version": "1.0.0",
                    "enabled_by_default": True,
                }
                plugin_dir = plugins / plugin_id
                plugin_dir.mkdir(parents=True)
                (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
                registry["plugins"][plugin_id] = {
                    "manifest_hash": manifest_hash_from_data(manifest),
                    "issued_at": time.time() - 100,
                    **entry,
                }
            registry_path = root / "trust-registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[plugins],
                plugin_trust_registry=registry_path,
            )

            body = discover_plugins(config).to_dict()
            by_id = {plugin["id"]: plugin for plugin in body["plugins"]}

            for plugin_id, _entry, trusted, reason, status in cases:
                with self.subTest(plugin_id=plugin_id):
                    self.assertEqual(by_id[plugin_id]["trusted"], trusted)
                    self.assertEqual(by_id[plugin_id]["registration_reason"], reason)
                    self.assertEqual(by_id[plugin_id]["trust"]["status"], status)

    def test_trust_registry_publisher_metadata_is_optional_and_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {
                "id": "provider.publisher",
                "name": "Publisher Demo",
                "type": "provider",
                "version": "1.0.0",
                "enabled_by_default": True,
            }
            plugin_dir = root / "plugins" / "publisher"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
            registry_path = root / "trust-registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "plugins": {
                            "provider.publisher": {
                                "manifest_hash": manifest_hash_from_data(manifest),
                                "trusted": True,
                                "publisher": {
                                    "publisher_id": 123,
                                    "publisher_name": ["bad"],
                                    "verified_publisher": "true",
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
                plugin_trust_registry=registry_path,
            )

            plugin = discover_plugins(config).to_dict()["plugins"][0]

            self.assertTrue(plugin["trusted"])
            self.assertEqual(plugin["trust"]["publisher_id"], "")
            self.assertEqual(plugin["trust"]["publisher_name"], "")
            self.assertFalse(plugin["trust"]["verified_publisher"])

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

    def test_plugin_execution_interface_supports_future_backends_without_execution(self) -> None:
        for backend in ("disabled", "local_process", "docker", "wasm"):
            with self.subTest(backend=backend):
                sandbox = PluginExecutionSandbox(
                    execution_enabled=True,
                    backend=backend,
                    granted_scopes=["provider.read"],
                )
                result = sandbox.execute(
                    PluginExecutionRequest(
                        plugin_id="provider.signed",
                        action="inspect",
                        requested_scopes=["provider.read"],
                    )
                )
                self.assertFalse(result.ok)
                if backend == "disabled":
                    self.assertEqual(result.reason, "plugin_execution_disabled")
                elif backend == "local_process":
                    self.assertEqual(result.reason, "plugin_entrypoint_missing")
                else:
                    self.assertEqual(result.reason, "plugin_code_execution_not_implemented")
                self.assertEqual(result.backend, backend)

    def test_trusted_plugin_executes_local_process_json_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "demo"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.py").write_text(
                "\n".join(
                    [
                        "import json, sys",
                        "request = json.loads(sys.stdin.read() or '{}')",
                        "json.dump({'ok': True, 'echo': request['payload'].get('value')}, sys.stdout)",
                    ]
                ),
                encoding="utf-8",
            )
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "tool.demo",
                        "name": "Demo Tool",
                        "type": "tool",
                        "entrypoint": "plugin.py",
                        "enabled_by_default": True,
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
                trusted_plugins=["tool.demo"],
                plugin_execution_enabled=True,
                plugin_capability_grants={"tool.demo": ["tool.register"]},
            )

            discovered = discover_plugins(config).to_dict()["plugins"][0]
            result = execute_plugin(
                config,
                plugin_id="tool.demo",
                action="run",
                payload={"value": "hello"},
                requested_scopes=["tool.register"],
            )

        self.assertTrue(discovered["sandbox"]["code_execution"])
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.reason, "plugin_executed")
        self.assertEqual(result.output["echo"], "hello")

    def test_plugin_execution_enforces_each_capability_scope(self) -> None:
        for scope in sorted(CAPABILITY_SCOPES):
            with self.subTest(scope=scope):
                granted = PluginExecutionSandbox(
                    execution_enabled=False,
                    granted_scopes=[scope],
                ).execute(
                    PluginExecutionRequest(
                        plugin_id="plugin.scope",
                        action="use",
                        requested_scopes=[scope],
                    )
                )
                denied = PluginExecutionSandbox(
                    execution_enabled=False,
                    granted_scopes=[],
                ).execute(
                    PluginExecutionRequest(
                        plugin_id="plugin.scope",
                        action="use",
                        requested_scopes=[scope],
                    )
                )
                self.assertEqual(granted.reason, "plugin_execution_disabled")
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

    def test_enterprise_audit_export_filters_and_applies_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            now = 1_700_000_000.0
            rows = [
                {
                    "type": "enterprise_permission_decision",
                    "actor_id": "alice",
                    "user": "alice",
                    "workspace_id": "workspace-1",
                    "workspace": "workspace-1",
                    "action": "write_file",
                    "target": "a.txt",
                    "allowed": True,
                    "created_at": now - 60,
                    "metadata": {"token": "audit-secret-token"},
                },
                {
                    "type": "enterprise_permission_decision",
                    "actor_id": "alice",
                    "user": "alice",
                    "workspace_id": "workspace-1",
                    "workspace": "workspace-1",
                    "action": "write_file",
                    "target": "b.txt",
                    "allowed": False,
                    "created_at": now - 30,
                },
                {
                    "type": "enterprise_permission_decision",
                    "actor_id": "bob",
                    "user": "bob",
                    "workspace_id": "workspace-2",
                    "workspace": "workspace-2",
                    "action": "run_shell_command",
                    "target": "old",
                    "allowed": True,
                    "created_at": now - (10 * 24 * 60 * 60),
                },
            ]
            for row in rows:
                record_event(state_dir, "enterprise_audit", row)

            allowed = export_enterprise_audit(
                state_dir,
                user="alice",
                workspace="workspace-1",
                action="write_file",
                allowed=True,
                retention_days=7,
                now=now,
            )
            denied = enterprise_audit_events(
                state_dir,
                allowed=False,
                retention_days=7,
                now=now,
            )
            retained = enterprise_audit_events(state_dir, retention_days=7, now=now)

            self.assertEqual(allowed["count"], 1)
            self.assertTrue(allowed["events"][0]["allowed"])
            self.assertNotIn("audit-secret-token", json.dumps(allowed))
            self.assertEqual(len(denied), 1)
            self.assertFalse(denied[0]["allowed"])
            self.assertEqual({event["user"] for event in retained}, {"alice"})


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
            long_secret = "long-token-value-1234567890abcdefABCDEF_verysecret"
            server.router._record_failure(
                config.agents["cloud"],
                error_type="provider_error",
                message=(
                    "Provider said Authorization: Bearer provider-secret-token "
                    f"and sk-provider-secret-123456789 and {long_secret}"
                ),
            )
            for stream in ("events", "workflows", "enterprise_audit"):
                record_event(
                    config.state_dir,
                    stream,
                    {
                        "type": "malicious_provider_error",
                        "message": f"x-api-key=provider-secret-token and ghp_providersecret123456 and {long_secret}",
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
            self.assertNotIn(long_secret, combined)
            self.assertIn("[REDACTED]", combined)

    def test_public_diagnostics_auth_protects_all_diagnostics_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                host="0.0.0.0",
                state_dir=root / "state",
                workspace_dir=root,
                diagnostics_auth_token="diagnostic-secret",
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo", free=True)},
                default_route=["echo"],
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                for path in (
                    "/v1/provider-health",
                    "/v1/events",
                    "/v1/tools",
                    "/v1/workflows/status",
                    "/v1/plugins",
                    "/v1/enterprise/audit",
                ):
                    with self.subTest(path=path):
                        with self.assertRaises(HTTPError) as error:
                            _get_json(f"{base}{path}")
                        self.assertEqual(error.exception.code, 401)
                        error.exception.close()
                        body = _get_json(
                            f"{base}{path}",
                            headers={"Authorization": "Bearer diagnostic-secret"},
                        )
                        self.assertIn("object", body)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


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


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
