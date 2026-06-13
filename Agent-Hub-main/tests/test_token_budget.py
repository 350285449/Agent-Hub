from __future__ import annotations

import unittest

from agent_hub.models import HubRequest
from agent_hub.context import request_context_diagnostics
from agent_hub.token_budget import TokenBudgetManager, estimate_messages_tokens


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


if __name__ == "__main__":
    unittest.main()
