from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub import AgentHub
from agent_hub.config import AgentConfig, HubConfig
from agent_hub.models import HubRequest, HubResponse


class LibraryModeTests(unittest.TestCase):
    def test_agent_hub_route_builds_library_request(self) -> None:
        config = HubConfig(
            agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
            default_route=["echo"],
        )
        router = _FakeRouter()
        hub = AgentHub(config, router=router)

        response = hub.route("fix failing tests", route="coding", session_id="s1")

        self.assertEqual(response.text, "ok")
        self.assertIsNotNone(router.request)
        self.assertEqual(router.request.api_shape, "library")
        self.assertEqual(router.request.messages, [{"role": "user", "content": "fix failing tests"}])
        self.assertEqual(router.request.route, "coding")
        self.assertEqual(router.request.session_id, "s1")

    def test_agent_hub_load_uses_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                """
                {
                  "state_dir": ".agent-hub/state",
                  "workspace_dir": ".",
                  "agents": [
                    {"name": "echo", "provider": "echo", "model": "echo"}
                  ],
                  "default_route": ["echo"]
                }
                """,
                encoding="utf-8",
            )

            hub = AgentHub.load(path, auto_detect=False)

            self.assertIn("echo", hub.config.agents)


class _FakeRouter:
    def __init__(self) -> None:
        self.request: HubRequest | None = None

    def route(self, request: HubRequest) -> HubResponse:
        self.request = request
        return HubResponse(
            request_id="r1",
            session_id=request.session_id,
            agent="echo",
            provider="echo",
            model="echo",
            text="ok",
        )


if __name__ == "__main__":
    unittest.main()
