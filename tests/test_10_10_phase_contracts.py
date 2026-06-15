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
        self.assertIn("function_findings", report.to_dict())
        self.assertIn("import_cycle_findings", report.to_dict())
        self.assertIn("layer_violation_findings", report.to_dict())
        self.assertIn("api_stability_findings", report.to_dict())

    def test_architecture_guardrail_report_covers_function_cycles_layers_and_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "agent_hub"
            (package / "core").mkdir(parents=True)
            (package / "api").mkdir()
            (package / "providers").mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "core" / "__init__.py").write_text("", encoding="utf-8")
            (package / "api" / "__init__.py").write_text("", encoding="utf-8")
            (package / "providers" / "__init__.py").write_text("", encoding="utf-8")
            (package / "core" / "domain.py").write_text(
                "from agent_hub.api.entry import handler\n",
                encoding="utf-8",
            )
            (package / "api" / "entry.py").write_text(
                "from agent_hub.core.domain import model\n\n"
                "def handler():\n"
                "    return 'ok'\n",
                encoding="utf-8",
            )
            (package / "providers" / "base.py").write_text(
                "class ChatRequest:\n"
                "    pass\n",
                encoding="utf-8",
            )
            (package / "core" / "large.py").write_text(
                "def large_function():\n"
                + "".join(f"    value_{index} = {index}\n" for index in range(4))
                + "    return value_0\n",
                encoding="utf-8",
            )

            report = architecture_guardrail_report(
                root,
                max_file_lines=50,
                max_function_lines=3,
                enforce=True,
                public_api={"agent_hub.providers.base": ["ChatRequest", "ChatResponse"]},
            )

        self.assertFalse(report.ok)
        self.assertEqual(report.function_findings[0].function, "large_function")
        self.assertTrue(report.import_cycle_findings)
        self.assertEqual(report.layer_violation_findings[0].source, "agent_hub.core.domain")
        self.assertEqual(report.api_stability_findings[0].name, "ChatResponse")
        self.assertEqual(report.to_dict()["max_function_lines"], 3)

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
