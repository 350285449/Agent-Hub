from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from agent_hub.application import (
    AgentApplicationService,
    AdaptiveApplicationService,
    AnalyticsMaintenanceService,
    DiagnosticsApplicationService,
    RoutingProfileApplicationService,
    WorkflowTemplateApplicationService,
)
from agent_hub.config import AgentConfig, HubConfig, MCPServerConfig, RouteRule
from agent_hub.core.router import AgentRouter
from agent_hub.evaluation import BenchmarkResult, ProviderScoreStore
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.observability import record_event
from agent_hub.plugins.registration import apply_plugin_registrations, register_plugin_tools
from agent_hub.runtime_usability import (
    runtime_route_smoke,
    runtime_usability_body,
    save_runtime_usability_record,
)
from agent_hub.tools import ToolCall, ToolExecutionContext, ToolExecutionPipeline, ToolRegistry


class ApplicationServiceTests(unittest.TestCase):
    def test_agent_service_crud_normalizes_and_redacts_agent_config(self) -> None:
        config = HubConfig()
        service = AgentApplicationService(config)

        created = service.create_agent(
            {
                "name": "custom.coder",
                "provider": "openai-compatible",
                "provider_type": "lm-studio",
                "model": "local-coder",
                "api_key": "sk-local-secret",
                "supports_tools": True,
                "add_to_default_route": True,
            }
        )
        updated = service.update_agent("custom.coder", {"model": "local-coder-v2", "enabled": False})
        listed = service.list_agents()
        self.assertIn("custom.coder", config.default_route)
        deleted = service.delete_agent("custom.coder")

        self.assertTrue(created["created"])
        self.assertNotIn("api_key", created["data"])
        self.assertTrue(created["data"]["has_api_key"])
        self.assertEqual(updated["data"]["model"], "local-coder-v2")
        self.assertFalse(updated["data"]["enabled"])
        self.assertTrue(updated["data"]["has_api_key"])
        self.assertEqual(listed["count"], 1)
        self.assertTrue(deleted["deleted"])
        self.assertNotIn("custom.coder", config.agents)
        self.assertNotIn("custom.coder", config.default_route)

    def test_workflow_template_service_layers_local_templates_over_builtins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(state_dir=Path(tmp) / "state")
            service = WorkflowTemplateApplicationService(config)

            initial = service.list_templates()
            created = service.create_template(
                {
                    "id": "release-review",
                    "workflow": "review",
                    "pattern": "team_reviewed",
                    "description": "Review a release candidate.",
                    "stages": [
                        {"name": "triage", "role": "planner", "preference": "reasoning"},
                        {"name": "audit", "role": "reviewer", "preference": "reliable"},
                    ],
                }
            )
            fetched = service.get_template("release-review")
            updated = service.update_template("release-review", {"enabled": False})
            deleted = service.delete_template("release-review")

        self.assertTrue(any(row["id"] == "code" for row in initial["data"]))
        self.assertTrue(any(row["id"] == "preset:bug_fixer" for row in initial["data"]))
        self.assertTrue(created["created"])
        self.assertEqual(fetched["data"]["pattern"], "team_reviewed")
        self.assertEqual(len(fetched["data"]["stages"]), 2)
        self.assertFalse(updated["data"]["enabled"])
        self.assertTrue(deleted["deleted"])

    def test_trusted_workflow_plugin_registers_readonly_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "workflow-demo"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "workflow.release",
                        "name": "Release Workflow",
                        "type": "workflow",
                        "enabled_by_default": True,
                        "metadata": {
                            "template_id": "release-hardening",
                            "workflow": "review",
                            "pattern": "team_reviewed",
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
                trusted_plugins=["workflow.release"],
            )

            body = WorkflowTemplateApplicationService(config).list_templates()

        template = next(row for row in body["data"] if row["id"] == "release-hardening")
        self.assertEqual(template["source"], "plugin")
        self.assertEqual(template["plugin_id"], "workflow.release")
        self.assertEqual(template["pattern"], "team_reviewed")

    def test_trusted_provider_plugin_registration_adds_runtime_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "provider-demo"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "provider.demo",
                        "name": "Provider Demo",
                        "type": "provider",
                        "enabled_by_default": True,
                        "metadata": {
                            "agent_name": "demo-agent",
                            "provider_type": "demo-compatible",
                            "base_url": "http://127.0.0.1:9999/v1",
                            "models": ["demo-model"],
                            "supports_streaming": True,
                            "add_to_default_route": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
                trusted_plugins=["provider.demo"],
            )

            report = apply_plugin_registrations(config)

        self.assertEqual(report["provider_count"], 1)
        self.assertIn("demo-agent", config.agents)
        self.assertEqual(config.agents["demo-agent"].provider_type, "demo-compatible")
        self.assertEqual(config.agents["demo-agent"].model, "demo-model")
        self.assertTrue(config.agents["demo-agent"].supports_streaming)
        self.assertIn("demo-agent", config.default_route)

    def test_trusted_tool_plugin_registration_adds_policy_gated_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "tool-demo"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "tool.demo",
                        "name": "Tool Demo",
                        "type": "tool",
                        "enabled_by_default": True,
                        "permissions": ["read"],
                        "metadata": {
                            "tools": [
                                {
                                    "name": "plugin.demo.lookup",
                                    "description": "Lookup demo data.",
                                    "input_schema": {
                                        "type": "object",
                                        "properties": {"query": {"type": "string"}},
                                    },
                                    "permissions": ["read"],
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
                trusted_plugins=["tool.demo"],
                approval_mode="auto",
            )
            registry = ToolRegistry()

            report = register_plugin_tools(registry, config)
            result = ToolExecutionPipeline(registry).execute(
                ToolCall(name="plugin.demo.lookup", arguments={"query": "x"}),
                ToolExecutionContext(config=config),
            )

        self.assertEqual(report["tool_count"], 1)
        self.assertIn("plugin.demo.lookup", registry.names())
        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["status"], "execution_policy_gated")

    def test_routing_profile_service_applies_profile_to_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(state_dir=Path(tmp) / "state")
            service = RoutingProfileApplicationService(config)

            profiles = service.list_profiles()
            created = service.create_profile(
                {
                    "id": "low-cost-ci",
                    "label": "Low Cost CI",
                    "routing_mode": "cheapest",
                    "fallback_policy": {"max_provider_attempts": 2, "order": "cost_first"},
                }
            )
            request = service.apply_to_request(
                HubRequest(
                    session_id="profile",
                    messages=[{"role": "user", "content": "explain this"}],
                    raw={"agent_hub": {"routing_profile": "low-cost-ci"}},
                )
            )
            deleted = service.delete_profile("low-cost-ci")

        self.assertTrue(any(row["id"] == "private" for row in profiles["data"]))
        private = next(row for row in profiles["data"] if row["id"] == "private")
        self.assertEqual(private["metadata"]["strategy_id"], "private")
        self.assertIn("score_weights", private["metadata"])
        self.assertTrue(any(row["id"] == "cheapest" for row in profiles["strategies"]))
        self.assertTrue(created["created"])
        self.assertEqual(request.raw["routing_mode"], "cheapest")
        self.assertEqual(request.raw["agent_hub"]["fallback_policy"]["max_provider_attempts"], 2)
        self.assertEqual(request.metadata["routing_profile"]["id"], "low-cost-ci")
        self.assertTrue(deleted["deleted"])

    def test_trusted_router_strategy_plugin_registers_readonly_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "strategy-demo"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "strategy.low-latency",
                        "name": "Low Latency Strategy",
                        "type": "router_strategy",
                        "enabled_by_default": True,
                        "metadata": {
                            "profile_id": "low-latency-plugin",
                            "routing_mode": "fastest",
                            "fallback_policy": {"max_provider_attempts": 3, "order": "latency_first"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
                trusted_plugins=["strategy.low-latency"],
            )

            body = RoutingProfileApplicationService(config).list_profiles()

        profile = next(row for row in body["data"] if row["id"] == "low-latency-plugin")
        self.assertEqual(profile["source"], "plugin")
        self.assertEqual(profile["plugin_id"], "strategy.low-latency")
        self.assertEqual(profile["routing_mode"], "fastest")
        self.assertEqual(profile["fallback_policy"]["max_provider_attempts"], 3)

    def test_adaptive_service_runs_auto_and_records_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            router = AgentRouter(config, provider_factory=_Provider)
            service = AdaptiveApplicationService(
                config,
                router=router,
                agent_runner=_UnusedRunner(),
                team_agent_runner=_UnusedRunner(),
                workflow_engine=_UnusedRunner(),
            )

            response = service.execute_auto(
                HubRequest(session_id="s", messages=[{"role": "user", "content": "hello"}])
            )
            feedback, status = service.record_feedback_payload(
                {"request_id": response.request_id, "rating": "up", "workflow_success": True}
            )
            optimization = service.optimization_summary()
            simulation = service.simulate_request(
                HubRequest(session_id="sim", messages=[{"role": "user", "content": "large architecture migration"}])
            )

            self.assertEqual(response.raw["agent_hub"]["workflow_selection"]["pattern"], "direct_route")
            self.assertEqual(status, 200)
            self.assertTrue(feedback["matched"])
            self.assertEqual(optimization["object"], "agent_hub.optimization")
            self.assertEqual(optimization["workflow_success_rate"]["successes"], 1)
            self.assertTrue(optimization["adaptive_routing_enabled"])
            self.assertEqual(simulation["object"], "agent_hub.routing_simulation")
            self.assertEqual(simulation["workflow_selection"]["pattern"], "team_reviewed")
            self.assertTrue(simulation["role_plan"])

    def test_adaptive_service_validates_feedback_payloads(self) -> None:
        service = AdaptiveApplicationService(
            HubConfig(),
            router=_RouterWithAdaptiveStore(HubConfig()),
            agent_runner=_UnusedRunner(),
            team_agent_runner=_UnusedRunner(),
            workflow_engine=_UnusedRunner(),
        )

        missing_id, missing_status = service.record_feedback_payload({"rating": "up"})
        bad_workflow, bad_status = service.record_feedback_payload(
            {"request_id": "hub-missing", "rating": "up", "workflow_success": "yes"}
        )

        self.assertEqual(missing_status, 400)
        self.assertEqual(missing_id["error"]["type"], "invalid_feedback")
        self.assertEqual(bad_status, 400)
        self.assertEqual(bad_workflow["error"]["type"], "invalid_feedback")

    def test_diagnostics_service_reads_provider_scores_from_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            ProviderScoreStore(config.state_dir).save_results(
                [
                    BenchmarkResult(
                        agent="coder",
                        provider="openai-compatible",
                        model="coder-test",
                        task_type="coding",
                        score=0.91,
                        latency_ms=12,
                        ok=True,
                    )
                ]
            )

            body = DiagnosticsApplicationService(config).provider_scores_body()

            self.assertEqual(body["object"], "agent_hub.provider_scores")
            self.assertEqual(body["data"]["coder"]["overall_score"], 0.91)

    def test_diagnostics_dashboards_explain_missing_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            router = AgentRouter(config, provider_factory=_Provider)
            service = DiagnosticsApplicationService(config)

            leaderboard = service.model_leaderboard_body(router)
            costs = service.cost_dashboard_body({})
            benchmarks = service.benchmark_results_body()

            self.assertEqual(leaderboard["summary"]["data_state"], "baseline_ready")
            self.assertEqual(leaderboard["summary"]["baseline_agent_count"], 1)
            self.assertIsNone(leaderboard["empty_state"])
            self.assertEqual(leaderboard["data"][0]["measurement_status"], "configured_baseline")
            self.assertGreater(leaderboard["data"][0]["ranking_score"], 0)
            self.assertEqual(costs["summary"]["data_state"], "partial_pricing_waiting_for_usage")
            self.assertEqual(costs["summary"]["configured_agents"], 1)
            self.assertEqual(costs["pricing_catalog"][0]["pricing_status"], "missing")
            self.assertIsNone(costs["empty_state"])
            self.assertEqual(benchmarks["summary"]["data_state"], "baseline_ready")
            self.assertEqual(benchmarks["summary"]["snapshot_result_count"], 1)
            self.assertGreaterEqual(benchmarks["operational_readiness"]["rating"], 8.5)
            self.assertEqual(benchmarks["measurement_plan"]["preferred_route"], "coding")
            self.assertEqual(
                benchmarks["coverage_snapshot"]["results"][0]["measurement_status"],
                "configured_baseline",
            )
            self.assertIsNone(benchmarks["empty_state"])

    def test_benchmark_dashboard_reads_personal_proof_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            reports_dir = config.state_dir / "benchmark_reports"
            reports_dir.mkdir(parents=True)
            (reports_dir / "benchmark-report.json").write_text(
                json.dumps(
                    {
                        "object": "agent_hub.benchmark_proof",
                        "route": "coding",
                        "task_count": 50,
                        "baseline": {"agent": "claude", "provider": "anthropic", "model": "sonnet"},
                        "baseline_summary": {"success_rate": 0.82},
                        "agent_hub_summary": {"success_rate": 0.84},
                        "comparison": {
                            "cost_reduction": 38.2,
                            "latency_reduction": 17.4,
                            "success_delta": 2.0,
                        },
                        "results": [{"task_type": "debugging"}],
                    }
                ),
                encoding="utf-8",
            )

            benchmarks = DiagnosticsApplicationService(config).benchmark_results_body()

            self.assertEqual(benchmarks["summary"]["data_state"], "measured_ready")
            self.assertEqual(benchmarks["summary"]["report_count"], 1)
            self.assertEqual(benchmarks["reports"][0]["summary"]["winner"], "Agent-Hub routing")
            self.assertEqual(benchmarks["reports"][0]["summary"]["comparison"]["cost_reduction"], 38.2)

    def test_readiness_score_rewards_real_route_ready_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _runtime_config(Path(tmp))
            router = AgentRouter(config, provider_factory=_Provider)
            service = DiagnosticsApplicationService(config)
            provider_health = {"coder": {"available": True, "success_count": 1}}
            runtime = runtime_usability_body(
                config,
                provider_health,
                route_smoke=runtime_route_smoke(
                    research_ok=True,
                    coding_ok=True,
                    coding_agent="coder",
                ),
            )

            readiness = service.readiness_body(
                router,
                provider_health=provider_health,
                runtime_usability=runtime,
            )

            self.assertEqual(readiness["object"], "agent_hub.readiness")
            self.assertGreaterEqual(readiness["rating"], 9.0)
            self.assertEqual(readiness["state"], "production_ready")
            self.assertEqual(readiness["feature_status"]["provider_routing"]["state"], "ready")
            self.assertEqual(readiness["runtime_usability"]["state"], "ready")
            self.assertTrue(any(item["id"] == "security_guardrails" for item in readiness["items"]))

    def test_runtime_usability_requires_verified_coding_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _runtime_config(Path(tmp))

            runtime = runtime_usability_body(
                config,
                {"coder": {"available": False}},
                route_smoke=runtime_route_smoke(research_ok=True, coding_ok=False),
            )

        self.assertEqual(runtime["state"], "needs_local_model")
        self.assertFalse(runtime["ready"])
        self.assertFalse(runtime["checks"][1]["ok"])

    def test_runtime_usability_does_not_mask_failed_latest_smoke_with_old_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _runtime_config(Path(tmp))

            runtime = runtime_usability_body(
                config,
                {"coder": {"available": True, "success_count": 3}},
                route_smoke=runtime_route_smoke(
                    research_ok=True,
                    coding_ok=False,
                    coding_error="Provider requires approval.",
                ),
            )

        checks = {item["id"]: item for item in runtime["checks"]}
        self.assertEqual(runtime["state"], "degraded")
        self.assertTrue(checks["verified_coding_provider"]["ok"])
        self.assertFalse(checks["route_smoke_recorded"]["ok"])
        self.assertIn("did not verify", checks["route_smoke_recorded"]["detail"])

    def test_readiness_does_not_claim_production_ready_without_runtime_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _runtime_config(Path(tmp))
            router = AgentRouter(config, provider_factory=_Provider)
            readiness = DiagnosticsApplicationService(config).readiness_body(
                router,
                provider_health={"coder": {"available": True, "success_count": 1}},
            )

        self.assertNotEqual(readiness["state"], "production_ready")
        self.assertEqual(readiness["runtime_usability"]["state"], "degraded")
        self.assertLess(readiness["runtime_usability"]["score"], 100)
        self.assertEqual(readiness["contract_readiness"]["state"], "production_ready")
        self.assertEqual(readiness["next_step"]["id"], "runtime_usability")

    def test_readiness_treats_cooling_down_provider_as_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            router = AgentRouter(config, provider_factory=_Provider)
            service = DiagnosticsApplicationService(config)

            readiness = service.readiness_body(
                router,
                provider_health={"coder": {"available": True, "cooldown_until": time.time() + 3600}},
            )

            provider_status = readiness["feature_status"]["provider_routing"]
            self.assertEqual(provider_status["state"], "needs_setup")
            self.assertEqual(provider_status["active_count"], 0)
            self.assertEqual(provider_status["blocked"][0]["agent"], "coder")
            self.assertEqual(provider_status["blocked"][0]["reason"], "provider cooling down")

    def test_plugins_body_exposes_policy_and_mcp_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            config.mcp_servers = [
                MCPServerConfig(
                    name="local-tools",
                    command="node",
                    tools=[{"name": "repo_search", "description": "Search the repository"}],
                )
            ]

            body = DiagnosticsApplicationService(config).plugins_body()

            self.assertEqual(body["object"], "agent_hub.plugins")
            self.assertEqual(body["state"], "discovery_ready")
            self.assertFalse(body["execution_policy"]["plugin_execution_enabled"])
            self.assertEqual(body["mcp"]["state"], "configured_execution_disabled")
            self.assertEqual(body["mcp"]["declared_tool_count"], 1)
            self.assertEqual(body["mcp"]["servers"][0]["status"], "policy_gated")
            self.assertEqual(body["mcp"]["tools"][0]["qualified_name"], "mcp.local-tools.repo_search")
            self.assertIn("runtime_contract", body)
            self.assertGreaterEqual(body["operational_readiness"]["rating"], 8.5)
            self.assertEqual(body["runtime_contract"]["validate_action"]["runs_plugin_code"], False)
            self.assertIn("execution disabled by policy", body["mcp"]["warnings"])

            mcp = DiagnosticsApplicationService(config).mcp_status_body()

            self.assertEqual(mcp["object"], "agent_hub.mcp_status")
            self.assertTrue(mcp["maturity"]["per_tool_permissions"])
            self.assertGreaterEqual(mcp["operational_readiness"]["rating"], 8.5)
            self.assertEqual(mcp["tools"][0]["call_example"]["name"], "mcp.local-tools.repo_search")

    def test_plugins_body_exposes_capability_inventory_and_execution_maturity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "provider-demo"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "provider.demo",
                        "name": "Provider Demo",
                        "type": "provider",
                        "enabled_by_default": True,
                        "metadata": {"provider_type": "demo-compatible"},
                    }
                ),
                encoding="utf-8",
            )
            config = _config(root)
            config.plugin_dirs = [root / "plugins"]
            config.trusted_plugins = ["provider.demo"]
            config.plugin_capability_grants = {"provider.demo": ["provider.read"]}

            body = DiagnosticsApplicationService(config).plugins_body()

            self.assertEqual(body["summary"]["registered_count"], 1)
            self.assertEqual(body["summary"]["capability_type_count"], 1)
            self.assertEqual(body["capability_inventory"]["registered_count"], 1)
            self.assertEqual(body["capability_inventory"]["registered"][0]["capability"], "providers")
            self.assertEqual(body["capability_inventory"]["registered"][0]["id"], "provider.demo")
            self.assertEqual(body["maturity"]["trusted_metadata_registration"], True)
            self.assertEqual(body["maturity"]["policy_gated_local_process_execution"], True)
            self.assertEqual(body["maturity"]["live_runtime_registration"], True)
            checks = {check["id"]: check for check in body["operational_readiness"]["checks"]}
            self.assertTrue(checks["capability_registration_inventory"]["ok"])
            self.assertTrue(checks["execution_capability_inventory"]["ok"])
            self.assertGreaterEqual(body["operational_readiness"]["rating"], 9.5)

    def test_inbox_status_reports_queue_and_recent_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            config.inbox_dir = root / "inbox"
            config.outbox_dir = root / "outbox"
            config.archive_dir = root / "archive"
            config.inbox_dir.mkdir()
            config.outbox_dir.mkdir()
            config.archive_dir.mkdir()
            (config.inbox_dir / "task.json").write_text('{"message":"hello"}', encoding="utf-8")
            (config.inbox_dir / "task.processing.json").write_text('{"message":"busy"}', encoding="utf-8")
            (config.outbox_dir / "done.json").write_text('{"ok":true}', encoding="utf-8")
            (config.archive_dir / "old.json").write_text('{"archived":true}', encoding="utf-8")

            body = DiagnosticsApplicationService(config).inbox_status_body()

            self.assertEqual(body["object"], "agent_hub.inbox_status")
            self.assertEqual(body["state"], "pending")
            self.assertEqual(body["counts"]["pending"], 1)
            self.assertEqual(body["counts"]["processing"], 1)
            self.assertEqual(body["counts"]["invalid_pending"], 0)
            self.assertTrue(body["queue_health"]["ready_to_process"])
            self.assertEqual(body["counts"]["recent_outputs"], 1)
            self.assertEqual(body["counts"]["archived"], 1)
            self.assertEqual(body["pending"][0]["name"], "task.json")
            self.assertTrue(body["pending"][0]["valid"])
            self.assertEqual(body["submission"]["endpoint"], "/v1/inbox/submit")
            self.assertIn("process_once", body["commands"])
            self.assertGreaterEqual(body["operational_readiness"]["rating"], 8.5)

    def test_inbox_status_marks_invalid_pending_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            config.inbox_dir = root / "inbox"
            config.outbox_dir = root / "outbox"
            config.archive_dir = root / "archive"
            config.inbox_dir.mkdir()
            config.outbox_dir.mkdir()
            config.archive_dir.mkdir()
            (config.inbox_dir / "broken.json").write_text("{", encoding="utf-8")

            body = DiagnosticsApplicationService(config).inbox_status_body()

            self.assertEqual(body["state"], "needs_attention")
            self.assertEqual(body["counts"]["invalid_pending"], 1)
            self.assertFalse(body["queue_health"]["ready_to_process"])
            self.assertEqual(body["queue_health"]["invalid_files"], ["broken.json"])

    def test_extension_contract_body_exposes_required_backend_features(self) -> None:
        body = DiagnosticsApplicationService(HubConfig()).extension_contract_body()

        self.assertEqual(body["object"], "agent_hub.extension_contract")
        self.assertTrue(body["summary"]["ok"], body["contract"])
        self.assertGreater(body["summary"]["required_count"], 0)
        self.assertEqual(body["summary"]["missing_count"], 0)
        self.assertTrue(body["maturity"]["machine_readable"])

    def test_feature_scorecard_rates_local_contracts_10_of_10(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _echo_config(Path(tmp))
            router = AgentRouter(config)

            body = DiagnosticsApplicationService(config).feature_scorecard_body(router)

        self.assertEqual(body["object"], "agent_hub.feature_scorecard")
        self.assertEqual(body["rating"], 10.0)
        self.assertTrue(body["all_local_areas_10"], body["blockers"])
        self.assertEqual(len(body["areas"]), 12)
        self.assertEqual({area["rating"] for area in body["areas"]}, {10.0})
        self.assertIn("runtime_usability", body["honesty"])

    def test_enterprise_status_summarizes_policy_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                enterprise_mode_enabled=True,
                enterprise_users=[{"id": "alice", "roles": ["developer"]}],
                enterprise_roles=[{"name": "developer", "permissions": ["workspace_cloud"]}],
                enterprise_permission_grants=[
                    {"subject_id": "alice", "workspace_id": "default", "permission": "workspace_cloud"}
                ],
            )
            service = DiagnosticsApplicationService(config)

            body = service.enterprise_status_body()

        self.assertEqual(body["object"], "agent_hub.enterprise_status")
        self.assertEqual(body["state"], "ready")
        self.assertEqual(body["summary"]["users"], 1)
        self.assertEqual(body["summary"]["grants"], 1)
        self.assertEqual(body["warnings"], [])
        self.assertGreaterEqual(body["operational_readiness"]["rating"], 8.5)
        self.assertEqual(body["policy_coverage"]["matrix"][0]["user"], "alice")
        self.assertIn("workspace_cloud", body["policy_coverage"]["permission_names"])

    def test_production_check_passes_for_route_ready_guarded_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _runtime_config(Path(tmp))
            config.agents["coder"].supports_tools = True
            config.agents["coder"].supports_function_calling = True
            save_runtime_usability_record(
                config,
                {
                    "route_smoke": runtime_route_smoke(
                        research_ok=True,
                        coding_ok=True,
                        coding_agent="coder",
                    )
                },
            )
            router = AgentRouter(config, provider_factory=_Provider)
            service = DiagnosticsApplicationService(config)

            report = service.production_check_body(
                router,
                provider_health={"coder": {"available": True, "success_count": 1}},
            )

            self.assertEqual(report["object"], "agent_hub.production_check")
            self.assertTrue(report["ok"])
            self.assertGreaterEqual(report["rating"], 9.0)
            self.assertTrue(any(check["id"] == "vscode_backend_contract" for check in report["checks"]))

    def test_production_check_flags_auto_approval_as_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            config.agents["coder"].supports_tools = True
            config.agents["coder"].supports_function_calling = True
            config.approval_mode = "auto"
            router = AgentRouter(config, provider_factory=_Provider)

            report = DiagnosticsApplicationService(config).production_check_body(
                router,
                provider_health={"coder": {"available": True}},
            )

            checks = {check["id"]: check for check in report["checks"]}
            self.assertFalse(checks["security_guardrails"]["ok"])
            self.assertFalse(report["ok"])
            self.assertLess(report["score"], 100)

    def test_production_check_reports_readiness_and_metadata_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            config.expose_routing_details = True
            router = AgentRouter(config, provider_factory=_Provider)

            report = DiagnosticsApplicationService(config).production_check_body(
                router,
                provider_health={"coder": {"available": True}},
            )

            checks = {check["id"]: check for check in report["checks"]}
            self.assertFalse(checks["readiness_warnings"]["ok"])
            self.assertFalse(checks["compatibility_metadata_policy"]["ok"])
            self.assertLess(report["score"], 100)

    def test_analytics_maintenance_compacts_events_adaptive_and_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = time.time()
            config = HubConfig(
                state_dir=root / "state",
                analytics_retention_days=7,
                analytics_max_events_per_stream=2,
                adaptive_retention_days=7,
                session_retention_days=7,
                session_max_records=2,
            )
            record_event(config.state_dir, "routing", {"type": "old", "time": now - 20 * 86400})
            record_event(config.state_dir, "routing", {"type": "recent-1", "time": now - 10})
            record_event(config.state_dir, "routing", {"type": "recent-2", "time": now - 5})
            record_event(config.state_dir, "routing", {"type": "recent-3", "time": now - 1})
            adaptive_path = config.state_dir / "adaptive_learning.json"
            adaptive_path.parent.mkdir(parents=True, exist_ok=True)
            adaptive_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "updated_at": now,
                        "aggregates": {"global|coder": {"attempts": 3, "last_seen_at": now - 30 * 86400}},
                        "workflow_patterns": {},
                        "role_agents": {},
                        "request_index": {
                            "old": {"request_id": "old", "updated_at": now - 30 * 86400},
                            "recent": {"request_id": "recent", "updated_at": now},
                        },
                        "recent_decisions": [
                            {"request_id": "old", "time": now - 30 * 86400},
                            {"request_id": "recent", "time": now},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            sessions = config.state_dir / "sessions"
            sessions.mkdir(parents=True)
            for name, updated_at in {
                "old": now - 30 * 86400,
                "recent": now,
                "recent-2": now - 1,
            }.items():
                (sessions / f"{name}.json").write_text(
                    json.dumps({"session_id": name, "updated_at": updated_at}),
                    encoding="utf-8",
                )

            report = AnalyticsMaintenanceService(config).compact(now=now)

            self.assertTrue(report["enabled"])
            self.assertGreaterEqual(report["removed_count"], 3)
            routing_lines = (config.state_dir / "routing_decisions.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(routing_lines), 2)
            adaptive = json.loads(adaptive_path.read_text(encoding="utf-8"))
            self.assertEqual(list(adaptive["request_index"].keys()), ["recent"])
            self.assertEqual(adaptive["recent_decisions"][0]["request_id"], "recent")
            self.assertIn("global|coder", adaptive["aggregates"])
            self.assertFalse((sessions / "old.json").exists())

    def test_analytics_maintenance_can_be_disabled(self) -> None:
        config = HubConfig(analytics_compaction_enabled=False)

        report = AnalyticsMaintenanceService(config).compact()

        self.assertFalse(report["enabled"])
        self.assertEqual(report["removed_count"], 0)


class _Provider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        return ProviderResult(
            text="ok",
            model=self.agent.model,
            usage={"prompt_tokens": 1, "completion_tokens": 1},
        )


class _UnusedRunner:
    def run(self, request: HubRequest) -> ProviderResult:
        raise AssertionError("runner should not be used for direct_route")

    def execute(self, kind: str, request: HubRequest) -> ProviderResult:
        raise AssertionError("workflow engine should not be used for direct_route")


class _RouterWithAdaptiveStore:
    def __init__(self, config: HubConfig) -> None:
        self.adaptive_learning = AgentRouter(config, provider_factory=_Provider).adaptive_learning


def _config(root: Path) -> HubConfig:
    return HubConfig(
        state_dir=root / "state",
        repo_context_enabled=False,
        default_route=["coder"],
        agents={
            "coder": AgentConfig(
                name="coder",
                provider="openai-compatible",
                model="coder-test",
                base_url="http://127.0.0.1:9999",
            )
        },
    )


def _runtime_config(root: Path) -> HubConfig:
    return HubConfig(
        state_dir=root / "state",
        repo_context_enabled=False,
        default_route=["coder"],
        routes=[
            RouteRule(name="research", agents=["local-research"]),
            RouteRule(name="coding", agents=["coder"]),
            RouteRule(name="cloud-agent", agents=["coder"]),
        ],
        agents={
            "coder": AgentConfig(
                name="coder",
                provider="openai-compatible",
                model="coder-test",
                base_url="http://127.0.0.1:9999",
            ),
            "local-research": AgentConfig(
                name="local-research",
                provider="local-research",
                provider_type="local-research",
                model="local-research",
                free=True,
            ),
        },
    )


def _echo_config(root: Path) -> HubConfig:
    config = HubConfig(
        state_dir=root / "state",
        inbox_dir=root / "inbox",
        outbox_dir=root / "outbox",
        archive_dir=root / "archive",
        workspace_dir=root,
        default_route=["echo"],
        routes=[RouteRule(name="cloud-agent", agents=["echo"])],
        agents={
            "echo": AgentConfig(
                name="echo",
                provider="echo",
                provider_type="echo",
                model="echo",
                enabled=True,
                free=True,
            )
        },
        debug_echo_enabled=True,
    )
    config.ensure_dirs()
    return config


if __name__ == "__main__":
    unittest.main()
