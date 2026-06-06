from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from agent_hub.application import AdaptiveApplicationService, DiagnosticsApplicationService
from agent_hub.config import AgentConfig, HubConfig, MCPServerConfig
from agent_hub.core.router import AgentRouter
from agent_hub.evaluation import BenchmarkResult, ProviderScoreStore
from agent_hub.models import HubRequest, ProviderResult


class ApplicationServiceTests(unittest.TestCase):
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

    def test_readiness_score_rewards_real_route_ready_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            router = AgentRouter(config, provider_factory=_Provider)
            service = DiagnosticsApplicationService(config)

            readiness = service.readiness_body(
                router,
                provider_health={"coder": {"available": True}},
            )

            self.assertEqual(readiness["object"], "agent_hub.readiness")
            self.assertGreaterEqual(readiness["rating"], 9.0)
            self.assertEqual(readiness["state"], "production_ready")
            self.assertEqual(readiness["feature_status"]["provider_routing"]["state"], "ready")
            self.assertTrue(any(item["id"] == "security_guardrails" for item in readiness["items"]))

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
            config = _config(Path(tmp))
            config.agents["coder"].supports_tools = True
            config.agents["coder"].supports_function_calling = True
            router = AgentRouter(config, provider_factory=_Provider)
            service = DiagnosticsApplicationService(config)

            report = service.production_check_body(
                router,
                provider_health={"coder": {"available": True}},
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


if __name__ == "__main__":
    unittest.main()
