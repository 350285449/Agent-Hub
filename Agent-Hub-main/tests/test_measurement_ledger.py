import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from agent_hub.application import DiagnosticsApplicationService
from agent_hub.config import AgentConfig, HubConfig
from agent_hub.core.router import AgentRouter
from agent_hub.measurement import (
    metrics_savings,
    record_completed_request,
    usage_ledger_path,
    usage_ledger_summary,
)
from agent_hub.models import HubRequest, ProviderResult


class MeasurementLedgerTests(unittest.TestCase):
    def test_records_actual_usage_named_baselines_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _measurement_config(Path(tmp))
            request = HubRequest(
                session_id="session-1",
                route="coding",
                messages=[{"role": "user", "content": "fix the tests"}],
                record_session=False,
            )

            record_completed_request(
                config=config,
                request_id="hub-test-1",
                request=request,
                agent=config.agents["selected"],
                model="selected-model",
                usage={"prompt_tokens": 1000, "completion_tokens": 500},
                output_text="done",
                latency_seconds=0.25,
                success=True,
                failover=[],
                candidate_scores=[{"agent": "selected"}, {"agent": "cheap"}],
                task_type="coding",
                input_tokens_estimated=900,
                output_tokens_estimated=400,
            )

            ledger_path = usage_ledger_path(config)
            self.assertEqual(ledger_path, Path(tmp) / "usage.sqlite")
            self.assertTrue(ledger_path.exists())
            with closing(sqlite3.connect(ledger_path)) as connection:
                connection.row_factory = sqlite3.Row
                request_row = connection.execute(
                    "SELECT * FROM requests WHERE request_id = ?",
                    ("hub-test-1",),
                ).fetchone()
                baseline_names = {
                    row["baseline_name"]
                    for row in connection.execute(
                        "SELECT baseline_name FROM baseline_comparisons WHERE request_id = ?",
                        ("hub-test-1",),
                    ).fetchall()
                }
                evaluation = connection.execute(
                    "SELECT * FROM evaluations WHERE request_id = ?",
                    ("hub-test-1",),
                ).fetchone()

            self.assertEqual(request_row["measurement_source"], "actual")
            self.assertEqual(request_row["cost_source"], "actual")
            self.assertAlmostEqual(request_row["cost_usd_actual"], 0.001)
            self.assertEqual(
                baseline_names,
                {
                    "vs_user_default_model",
                    "vs_claude_sonnet",
                    "vs_gpt_4_1",
                    "vs_static_routing",
                    "vs_cheapest_model_only",
                },
            )
            self.assertEqual(evaluation["evaluation_method"], "provider_success_only")

            summary = usage_ledger_summary(config)
            self.assertEqual(summary["request_count"], 1)
            self.assertEqual(summary["measurement_sources"]["actual"], 1)
            self.assertTrue(any(row["baseline_name"] == "vs_claude_sonnet" for row in summary["baseline_savings"]))
            self.assertEqual(summary["recent_requests"][0]["input_tokens"], 1000)
            self.assertEqual(summary["recent_requests"][0]["output_tokens"], 500)
            self.assertEqual(summary["recent_requests"][0]["rejected_models"][0]["agent"], "cheap")
            claude_baseline = next(
                row for row in summary["baseline_savings"] if row["baseline_name"] == "vs_claude_sonnet"
            )
            self.assertGreater(claude_baseline["tokens_saved"], 0)

    def test_metrics_savings_cards_are_derived_from_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _measurement_config(Path(tmp))

            record_completed_request(
                config=config,
                request_id="hub-savings-1",
                request=HubRequest(
                    session_id="session-savings",
                    route="coding",
                    messages=[{"role": "user", "content": "fix the tests"}],
                    record_session=False,
                ),
                agent=config.agents["selected"],
                model="selected-model",
                usage={"prompt_tokens": 1000, "completion_tokens": 500},
                output_text="done",
                latency_seconds=0.25,
                success=True,
                failover=[],
                candidate_scores=[{"agent": "selected"}, {"agent": "default"}],
                task_type="coding",
                input_tokens_estimated=900,
                output_tokens_estimated=400,
            )

            savings = metrics_savings(config)

            self.assertEqual(savings["object"], "agent_hub.metrics.savings")
            self.assertGreater(savings["tokens_saved"], 0)
            self.assertGreater(savings["cost_avoided_usd"], 0)
            self.assertEqual(savings["retries_avoided"], 0)
            self.assertEqual(savings["best_model_for_repo"], "openai-compatible / selected-model")

    def test_provider_reported_cost_and_total_tokens_are_captured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _measurement_config(Path(tmp))
            request = HubRequest(
                session_id="session-2",
                route="chat",
                messages=[{"role": "user", "content": "hello"}],
                record_session=False,
            )

            record_completed_request(
                config=config,
                request_id="hub-cost-1",
                request=request,
                agent=config.agents["selected"],
                model="selected-model",
                usage={"input_tokens": 100, "total_tokens": 125, "cost_usd": 0.42},
                output_text="hello",
                latency_seconds=0.1,
                success=True,
                failover=[],
                candidate_scores=[],
                input_tokens_estimated=80,
                output_tokens_estimated=20,
            )

            with closing(sqlite3.connect(usage_ledger_path(config))) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute("SELECT * FROM requests WHERE request_id = ?", ("hub-cost-1",)).fetchone()

            self.assertEqual(row["input_tokens_actual"], 100)
            self.assertEqual(row["output_tokens_actual"], 25)
            self.assertEqual(row["measurement_source"], "actual")
            self.assertEqual(row["cost_source"], "provider_reported")
            self.assertAlmostEqual(row["cost_usd_actual"], 0.42)

    def test_router_success_writes_usage_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                workspace_dir=Path(tmp),
                approval_mode="auto",
                free_only=False,
                default_route=["selected"],
                agents={
                    "selected": AgentConfig(
                        name="selected",
                        provider="openai-compatible",
                        model="selected-model",
                        base_url="http://127.0.0.1:9999",
                        cost_per_million_input=1.0,
                        cost_per_million_output=2.0,
                    )
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    return ProviderResult(
                        text="ok",
                        model=self.agent.model,
                        usage={"prompt_tokens": 100, "completion_tokens": 20},
                        finish_reason="stop",
                    )

            response = AgentRouter(config, provider_factory=Provider).route(
                HubRequest(
                    session_id="router-ledger",
                    messages=[{"role": "user", "content": "hello"}],
                    record_session=False,
                )
            )

            self.assertEqual(response.text, "ok")
            with closing(sqlite3.connect(usage_ledger_path(config))) as connection:
                count = connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
                attempts = connection.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0]
            self.assertEqual(count, 1)
            self.assertEqual(attempts, 1)

    def test_dashboard_and_routing_explanation_use_named_baselines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _measurement_config(Path(tmp))
            record_completed_request(
                config=config,
                request_id="hub-dashboard-1",
                request=HubRequest(
                    session_id="dash",
                    route="coding",
                    messages=[{"role": "user", "content": "diagnose"}],
                    record_session=False,
                ),
                agent=config.agents["selected"],
                model="selected-model",
                usage={},
                output_text="done",
                latency_seconds=0.1,
                success=True,
                failover=[],
                candidate_scores=[{"agent": "selected"}, {"agent": "cheap"}],
                input_tokens_estimated=1000,
                output_tokens_estimated=500,
            )

            dashboard = DiagnosticsApplicationService(config).cost_dashboard_body({})
            self.assertEqual(dashboard["usage_ledger"]["request_count"], 1)
            self.assertEqual(dashboard["summary"]["usage_ledger_requests"], 1)

            decision = AgentRouter(config, provider_factory=_UnusedProvider).decide(
                HubRequest(
                    session_id="explain",
                    route="coding",
                    messages=[{"role": "user", "content": "diagnose"}],
                    record_session=False,
                )
            )
            cost = decision.to_dict()["explanation"]["cost_savings"]
            self.assertEqual(cost["comparison"], "named_estimated_baselines")
            self.assertNotIn("vs_most_expensive_ranked_candidate", str(cost))
            self.assertTrue(any(row["baseline"] == "vs_claude_sonnet" for row in cost["named_baselines"]))


def _measurement_config(root: Path) -> HubConfig:
    return HubConfig(
        state_dir=root / "state",
        workspace_dir=root,
        approval_mode="auto",
        free_only=False,
        default_route=["selected", "claude", "gpt", "cheap", "default"],
        agents={
            "default": AgentConfig(
                name="default",
                provider="openai-compatible",
                model="default-model",
                base_url="http://127.0.0.1:9999",
                cost_per_million_input=2.0,
                cost_per_million_output=4.0,
            ),
            "selected": AgentConfig(
                name="selected",
                provider="openai-compatible",
                model="selected-model",
                base_url="http://127.0.0.1:9999",
                cost_per_million_input=0.5,
                cost_per_million_output=1.0,
            ),
            "claude": AgentConfig(
                name="claude",
                provider="anthropic",
                model="claude-3-5-sonnet",
                cost_per_million_input=3.0,
                cost_per_million_output=15.0,
            ),
            "gpt": AgentConfig(
                name="gpt",
                provider="openai",
                model="gpt-4.1",
                cost_per_million_input=2.0,
                cost_per_million_output=8.0,
            ),
            "cheap": AgentConfig(
                name="cheap",
                provider="openai-compatible",
                model="cheap-model",
                base_url="http://127.0.0.1:9999",
                cost_per_million_input=0.1,
                cost_per_million_output=0.2,
            ),
        },
    )


class _UnusedProvider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        raise AssertionError("Provider should not be called by decide().")


if __name__ == "__main__":
    unittest.main()
