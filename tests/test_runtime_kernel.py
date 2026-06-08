from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.core.router import AgentRouter
from agent_hub.runtime_kernel import AgentHubRuntimeKernel, normalize_route


class RuntimeKernelTests(unittest.TestCase):
    def test_normalize_route_collapses_dynamic_segments(self) -> None:
        self.assertEqual(normalize_route("/v1/routing-decision/abc123abc123"), "/v1/routing-decision/:id")
        self.assertEqual(normalize_route("/v1/plugins/local-tool/execute"), "/v1/plugins/:id/execute")
        self.assertEqual(normalize_route("/v1/models?verbose=true"), "/v1/models")

    def test_record_request_tracks_latency_errors_cache_and_subsystems(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["echo"],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
                debug_echo_enabled=True,
            )
            router = AgentRouter(config)
            kernel = AgentHubRuntimeKernel(slow_request_threshold_ms=10.0)

            kernel.begin_request()
            kernel.record_request(
                method="GET",
                path="/v1/routing-decision/abc123abc123",
                status=404,
                duration_ms=18.5,
                cache_state="miss",
            )
            body = kernel.snapshot(
                config=config,
                router=router,
                diagnostics_cache={
                    "object": "agent_hub.diagnostics_cache",
                    "enabled": True,
                    "entries": 1,
                    "hits": 0,
                    "misses": 1,
                    "hit_rate": 0.0,
                },
            )

        telemetry = body["request_telemetry"]
        self.assertEqual(body["object"], "agent_hub.runtime_kernel")
        self.assertGreaterEqual(body["operational_score"], 70)
        self.assertEqual(telemetry["total_requests"], 1)
        self.assertEqual(telemetry["in_flight"], 0)
        self.assertEqual(telemetry["status_codes"]["404"], 1)
        self.assertEqual(telemetry["cache_states"]["miss"], 1)
        self.assertEqual(telemetry["routes"][0]["path"], "/v1/routing-decision/:id")
        self.assertEqual(telemetry["routes"][0]["error_count"], 1)
        self.assertEqual(telemetry["recent_slow_requests"][0]["status"], 404)
        self.assertEqual(body["pressure"]["object"], "agent_hub.runtime_kernel.pressure")
        self.assertTrue(body["pressure"]["signals"])
        self.assertEqual(body["service_map"]["object"], "agent_hub.runtime_kernel.service_map")
        self.assertTrue(body["service_map"]["nodes"])
        self.assertTrue(body["service_map"]["edges"])
        self.assertEqual(body["primary_next_action"], body["next_actions"][0])
        self.assertTrue(body["next_actions"])
        self.assertTrue(all(row.get("title") for row in body["next_actions"]))
        self.assertEqual(body["timeline"][0]["type"], "client_error")
        self.assertTrue(any(row["type"] == "boot" for row in body["timeline"]))
        subsystem_ids = {row["id"] for row in body["subsystems"]}
        self.assertIn("http_server", subsystem_ids)
        self.assertIn("provider_pool", subsystem_ids)
        self.assertIn("diagnostics_cache", subsystem_ids)

    def test_low_cache_hit_rate_is_not_pressure_when_latency_is_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["echo"],
                agents={"echo": AgentConfig(name="echo", provider="echo", model="echo")},
                debug_echo_enabled=True,
            )
            router = AgentRouter(config)
            kernel = AgentHubRuntimeKernel()
            for _index in range(12):
                kernel.begin_request()
                kernel.record_request(
                    method="GET",
                    path="/health",
                    status=200,
                    duration_ms=20.0,
                    cache_state="miss",
                )

            body = kernel.snapshot(
                config=config,
                router=router,
                diagnostics_cache={
                    "object": "agent_hub.diagnostics_cache",
                    "enabled": True,
                    "entries": 1,
                    "hits": 0,
                    "misses": 12,
                    "hit_rate": 0.0,
                },
            )

        cache_signal = next(row for row in body["pressure"]["signals"] if row["id"] == "cache")
        self.assertEqual(cache_signal["state"], "nominal")
        self.assertEqual(body["pressure"]["state"], "nominal")


if __name__ == "__main__":
    unittest.main()
