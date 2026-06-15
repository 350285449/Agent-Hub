from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_hub.architecture import architecture_guardrail_report
from agent_hub.observability_export import observability_integrations, prometheus_lines, to_otlp_span
from agent_hub.orchestration import (
    BoundedSwarmPlan,
    OrchestrationPlan,
    SwarmStage,
    bounded_swarm_plan_from_payload,
    default_agent_roles,
    default_orchestration_primitives,
)
from agent_hub.plugins.lifecycle import PluginLifecycleManager
from agent_hub.plugins.sandbox import PLUGIN_SANDBOX_BACKENDS


class TenTenPhaseContractTests(unittest.TestCase):
    def test_architecture_guardrail_report_is_available_without_blocking_existing_monoliths(self) -> None:
        report = architecture_guardrail_report(Path.cwd(), max_file_lines=1200, enforce=False)

        self.assertEqual(report.object, "agent_hub.architecture_guardrails")
        self.assertTrue(report.ok)
        self.assertGreater(report.checked_files, 0)
        self.assertTrue(all(finding.severity == "advisory" for finding in report.findings))

    def test_agent_roles_and_orchestration_primitives_cover_phase_six(self) -> None:
        roles = {role.id for role in default_agent_roles()}
        primitives = default_orchestration_primitives()
        kinds = {primitive.kind for primitive in primitives}

        self.assertTrue(
            {
                "planner",
                "researcher",
                "coder",
                "reviewer",
                "security_reviewer",
                "validator",
                "documentation_writer",
                "finalizer",
            }.issubset(roles)
        )
        self.assertEqual(kinds, {"stage", "branch", "join", "vote", "critique", "retry", "escalate", "rollback"})
        plan = OrchestrationPlan(primitives, roles=default_agent_roles(), max_concurrency=2, token_budget=1000)
        self.assertFalse(plan.validate())
        self.assertTrue(plan.to_dict()["valid"])

        swarm = bounded_swarm_plan_from_payload({"goal": "ship feature", "max_concurrency": 2})
        self.assertTrue(swarm.to_dict()["valid"])
        unsafe = BoundedSwarmPlan(
            "bad",
            [SwarmStage("vote", "vote", ["planner"], max_parallel=3)],
            max_concurrency=2,
        )
        self.assertIn("vote:max_parallel_exceeds_plan_concurrency", unsafe.validate())
        self.assertIn("vote:validation_gate_required", unsafe.validate())

    def test_plugin_lifecycle_and_sandbox_backends_cover_phase_eight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "demo-provider",
                        "name": "Demo Provider",
                        "type": "provider",
                        "permissions": ["provider.register"],
                    }
                ),
                encoding="utf-8",
            )
            manager = PluginLifecycleManager(Path(tmp) / "plugins")

            install = manager.install(source)
            enable = manager.enable("demo-provider")
            audit = manager.audit("demo-provider")
            disable = manager.disable("demo-provider")
            remove = manager.remove("demo-provider")

            self.assertTrue(install.ok)
            self.assertTrue(enable.ok)
            self.assertTrue(audit.ok)
            self.assertEqual(audit.audit["permissions"], ["provider.register"])
            self.assertTrue(disable.ok)
            self.assertTrue(remove.ok)
            self.assertEqual(PLUGIN_SANDBOX_BACKENDS, {"disabled", "local_process", "docker", "wasm"})

    def test_plugin_lifecycle_rejects_invalid_manifest_on_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "plugin.json").write_text(
                json.dumps({"id": "bad plugin", "type": "provider"}),
                encoding="utf-8",
            )

            result = PluginLifecycleManager(Path(tmp) / "plugins").install(source)

            self.assertFalse(result.ok)
            self.assertIn("invalid_manifest", result.reason)

    def test_observability_export_contracts_cover_phase_ten(self) -> None:
        integrations = {item.id for item in observability_integrations()}
        span = to_otlp_span({"trace_id": "trace_a", "span_id": "span_b", "name": "router.route"})
        lines = prometheus_lines({"counters": {"provider_successes": 3}})

        self.assertEqual(integrations, {"opentelemetry", "prometheus", "grafana", "jaeger"})
        self.assertEqual(span["traceId"], "trace_a")
        self.assertIn('agent_hub_counter{name="provider_successes"} 3', lines)

    def test_security_docs_and_vscode_modules_exist_for_remaining_phases(self) -> None:
        root = Path.cwd()
        expected = [
            "docs/security-boundaries.md",
            "docs/plugin-sandbox.md",
            "docs/provider-data-policy.md",
            "deploy/docker-compose.providers.yml",
            "deploy/grafana/agent-hub-dashboard.json",
            "vscode-extension/src/api/typedClient.js",
            "vscode-extension/src/state/stateManager.js",
            "vscode-extension/src/commands/registry.js",
            "sdk/python/agent_hub_client/__init__.py",
            "sdk/typescript/src/index.ts",
        ]

        for relative in expected:
            self.assertTrue((root / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
