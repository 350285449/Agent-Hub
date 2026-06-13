from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.server import AgentHubHTTPServer


class DiagnosticsCacheTests(unittest.TestCase):
    def test_cache_reuses_value_and_tracks_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = _server(Path(tmp))
            calls = 0

            def build() -> dict[str, int]:
                nonlocal calls
                calls += 1
                return {"calls": calls}

            try:
                first, first_hit = server.diagnostics_cache_get("health", 60, build)
                second, second_hit = server.diagnostics_cache_get("health", 60, build)
                stats = server.diagnostics_cache_stats()
            finally:
                server.server_close()

        self.assertFalse(first_hit)
        self.assertTrue(second_hit)
        self.assertEqual(first, {"calls": 1})
        self.assertEqual(second, {"calls": 1})
        self.assertEqual(calls, 1)
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["entries"], 1)
        self.assertEqual(stats["hit_rate"], 0.5)

    def test_cache_invalidation_forces_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = _server(Path(tmp))
            calls = 0

            def build() -> dict[str, int]:
                nonlocal calls
                calls += 1
                return {"calls": calls}

            try:
                server.diagnostics_cache_get("health", 60, build)
                server.invalidate_diagnostics_cache("test")
                refreshed, hit = server.diagnostics_cache_get("health", 60, build)
                stats = server.diagnostics_cache_stats()
            finally:
                server.server_close()

        self.assertFalse(hit)
        self.assertEqual(refreshed, {"calls": 2})
        self.assertEqual(calls, 2)
        self.assertEqual(stats["invalidations"], 1)


def _server(path: Path) -> AgentHubHTTPServer:
    config = HubConfig(
        state_dir=path / "state",
        workspace_dir=path,
        default_route=["echo"],
        agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
    )
    return AgentHubHTTPServer(("127.0.0.1", 0), config)


if __name__ == "__main__":
    unittest.main()
