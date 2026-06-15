from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from agent_hub.models import HubRequest
from agent_hub.config import AgentConfig, HubConfig
from agent_hub.context import request_context_diagnostics
from agent_hub.token_budget import (
    TokenBudgetLedger,
    TokenBudgetManager,
    estimate_messages_tokens,
    token_budget_ledger_summary,
)
from agent_hub.token_pooling import simulate_token_pooling


class TokenBudgetManagerTests(unittest.TestCase):
    def test_context_modes_change_effective_budget(self) -> None:
        minimal = TokenBudgetManager("minimal").effective_input_budget(
            configured_budget=10_000,
            provider_budget=20_000,
        )
        deep = TokenBudgetManager("deep").effective_input_budget(
            configured_budget=10_000,
            provider_budget=20_000,
        )

        self.assertLess(minimal.effective_budget, deep.effective_budget)
        self.assertEqual(minimal.mode, "minimal")
        self.assertEqual(deep.mode, "deep")

    def test_request_context_mode_is_normalized(self) -> None:
        manager = TokenBudgetManager.from_request(
            HubRequest(
                session_id="s",
                messages=[],
                raw={"agent_hub": {"context_mode": "deep"}},
            )
        )

        self.assertEqual(manager.mode, "deep")

    def test_estimator_handles_structured_messages(self) -> None:
        tokens = estimate_messages_tokens(
            [{"role": "user", "content": [{"type": "text", "text": "hello world"}]}]
        )

        self.assertGreater(tokens, 1)

    def test_context_diagnostics_marks_protected_client_state(self) -> None:
        request = HubRequest(
            session_id="s",
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "fix this"}],
                    "task_progress": [{"title": "inspect"}],
                    "active_files": ["tests/test_cli.py"],
                }
            ],
            raw={"agent_hub": {"cline_compatibility_mode": True}},
        )

        diagnostics = request_context_diagnostics(request)

        self.assertGreater(diagnostics["protected_token_count"], 0)
        self.assertEqual(diagnostics["preserved_todo_count"], 1)
        self.assertEqual(diagnostics["active_files_detected"], ["tests/test_cli.py"])

    def test_token_budget_ledger_records_stage_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            budget = TokenBudgetManager("balanced").effective_input_budget(
                configured_budget=10_000,
                provider_budget=8_000,
            )

            row = TokenBudgetLedger(state_dir).record_stage(
                request_id="req-1",
                workflow="reviewed_worker",
                role="coder",
                stage="plan",
                status="actual",
                budget=budget,
                usage={"input_tokens": 1000, "output_tokens": 120, "tokens_saved": 300},
            )
            summary = token_budget_ledger_summary(state_dir)

            self.assertEqual(row["effective_budget"], budget.effective_budget)
            self.assertEqual(summary["count"], 1)
            self.assertEqual(summary["totals"]["input_tokens"], 1000)
            self.assertEqual(summary["totals"]["output_tokens"], 120)
            self.assertEqual(summary["totals"]["tokens_saved"], 300)
            self.assertEqual(summary["by_stage"]["plan"], 1)
            self.assertEqual(summary["by_workflow"]["reviewed_worker"], 1)

    def test_token_pooling_simulation_requires_user_owned_terms_confirmed_pools(self) -> None:
        config = HubConfig(
            token_pooling_enabled=True,
            agents={
                "cloud-a": AgentConfig(name="cloud-a", provider="openai", model="gpt-a"),
                "cloud-b": AgentConfig(name="cloud-b", provider="openai", model="gpt-b"),
            },
            token_pooling_pools=[
                {
                    "id": "owned",
                    "provider": "openai",
                    "agents": ["cloud-a"],
                    "remaining_tokens": 10_000,
                    "user_owned_quota": True,
                    "terms_confirmed": True,
                },
                {
                    "id": "unconfirmed",
                    "provider": "openai",
                    "agents": ["cloud-b"],
                    "remaining_tokens": 20_000,
                    "user_owned_quota": False,
                    "terms_confirmed": False,
                },
            ],
        )

        body = simulate_token_pooling(config, {"provider": "openai", "estimated_tokens": 2000})

        self.assertEqual(body["object"], "agent_hub.token_pool_simulation")
        self.assertTrue(body["dry_run"])
        self.assertTrue(body["policy"]["no_limit_bypass"])
        self.assertEqual(body["selected"]["id"], "owned")
        blocked = next(row for row in body["candidates"] if row["id"] == "unconfirmed")
        self.assertFalse(blocked["eligible"])
        self.assertIn("user_owned_quota_not_confirmed", blocked["reasons"])

    def test_token_pooling_simulation_reports_disabled_without_selection(self) -> None:
        config = HubConfig(
            token_pooling_enabled=False,
            token_pooling_pools=[
                {
                    "id": "owned",
                    "provider": "openai",
                    "remaining_tokens": 10_000,
                    "user_owned_quota": True,
                    "terms_confirmed": True,
                }
            ],
        )

        body = simulate_token_pooling(config, {"provider": "openai", "estimated_tokens": 100})

        self.assertIsNone(body["selected"])
        self.assertIn("token_pooling_disabled", body["warnings"])


if __name__ == "__main__":
    unittest.main()
