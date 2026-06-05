from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.application import AdaptiveApplicationService, DiagnosticsApplicationService
from agent_hub.config import AgentConfig, HubConfig
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

            self.assertEqual(leaderboard["summary"]["data_state"], "waiting_for_benchmarks_or_traffic")
            self.assertEqual(leaderboard["empty_state"]["title"], "No measured model outcomes yet")
            self.assertEqual(costs["summary"]["data_state"], "waiting_for_priced_usage")
            self.assertEqual(costs["empty_state"]["title"], "No known cost data yet")
            self.assertEqual(benchmarks["summary"]["data_state"], "waiting_for_benchmark_reports")
            self.assertEqual(benchmarks["empty_state"]["title"], "No benchmark reports yet")

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
