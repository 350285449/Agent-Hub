from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.models import HubRequest
from agent_hub.router import AgentRouter
from agent_hub.server import BACKEND_FEATURES, BACKEND_VERSION, _apply_model_routing, _model_rows


class ServerCompatibilityTests(unittest.TestCase):
    def test_backend_version_and_features_include_checkpoint_runtime(self) -> None:
        self.assertNotEqual(BACKEND_VERSION, "0.3.2")
        self.assertTrue(BACKEND_FEATURES["workspace_checkpoints"])
        self.assertTrue(BACKEND_FEATURES["validation_repair_loops"])

    def test_model_rows_include_router_aliases_and_agent_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["tooly"],
                routes=[RouteRule(name="coding", agents=["tooly"])],
                agents={
                    "tooly": AgentConfig(
                        name="tooly",
                        provider="openai-compatible",
                        model="tool-model",
                        base_url="https://example.invalid/v1",
                        free=True,
                        enabled=True,
                        supports_tools=True,
                        coding_score=0.9,
                    )
                },
            )

            rows = _model_rows(config, AgentRouter(config))
            ids = {row["id"] for row in rows}

            self.assertIn("agent-hub-coding", ids)
            self.assertIn("coding", ids)
            self.assertIn("tooly", ids)
            self.assertIn("tool-model", ids)

    def test_openai_model_name_can_select_agent_with_route_fallback(self) -> None:
        config = HubConfig(
            routes=[RouteRule(name="coding", agents=["fallback"])],
            agents={
                "chosen": AgentConfig(name="chosen", provider="echo", model="chosen-model"),
                "fallback": AgentConfig(name="fallback", provider="echo", model="fallback-model"),
            },
        )
        request = HubRequest(
            session_id="s",
            route="coding",
            messages=[{"role": "user", "content": "hello"}],
            raw={"model": "chosen-model"},
        )

        _apply_model_routing(config, request)

        self.assertEqual(request.preferred_agent, "chosen")
        self.assertEqual(request.route, "coding")


if __name__ == "__main__":
    unittest.main()
