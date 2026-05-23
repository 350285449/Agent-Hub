from __future__ import annotations

import json
import threading
import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.models import HubRequest
from agent_hub.router import AgentRouter
from agent_hub.server import (
    BACKEND_FEATURES,
    BACKEND_VERSION,
    AgentHubHTTPServer,
    _apply_model_routing,
    _model_rows,
)


class ServerCompatibilityTests(unittest.TestCase):
    def test_backend_version_and_features_include_checkpoint_runtime(self) -> None:
        self.assertNotEqual(BACKEND_VERSION, "0.3.2")
        self.assertTrue(BACKEND_FEATURES["workspace_checkpoints"])
        self.assertTrue(BACKEND_FEATURES["validation_repair_loops"])
        self.assertTrue(BACKEND_FEATURES["strict_repository_context"])
        self.assertTrue(BACKEND_FEATURES["grouped_patch_enforcement"])
        self.assertTrue(BACKEND_FEATURES["repository_context_scoring"])
        self.assertTrue(BACKEND_FEATURES["agent_context_compaction"])
        self.assertTrue(BACKEND_FEATURES["context_usage_bar"])

    def test_health_includes_context_enforcement_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="strict",
                context_change_bar_threshold=5,
                agent_context_budget_tokens=16000,
                agent_context_compaction_enabled=True,
                prefer_multi_file_patches=True,
                default_route=["echo"],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
            )
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_address[1]}/health", timeout=5) as response:
                    data = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(data["context_change_bar"]["mode"], "strict")
            self.assertEqual(data["context_change_bar"]["threshold"], 5)
            self.assertTrue(data["agent_context_compaction"]["enabled"])
            self.assertEqual(data["agent_context_compaction"]["budget_tokens"], 16000)
            self.assertTrue(data["grouped_patch_enforcement"]["enabled"])
            self.assertEqual(data["repository_context_scoring"]["strict_minimum"], 6)
            self.assertTrue(data["features"]["repository_context_scoring"])

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
