from __future__ import annotations

import time
import unittest

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.core.health import ProviderHealth
from agent_hub.core.router_diagnostics import build_capability_graph, build_provider_status
from agent_hub.core.routing_policy import (
    NO_TOOL_CAPABLE_MODEL,
    RouterPreflightPolicy,
    _request_has_client_tool_specs,
    _request_has_tools,
)
from agent_hub.models import HubRequest


class RouterDecompositionTests(unittest.TestCase):
    def test_preflight_policy_rejects_tool_request_without_tool_capable_agent(self) -> None:
        config = HubConfig()
        agent = AgentConfig(name="plain", provider="openai-compatible", model="m")
        request = HubRequest(
            session_id="s",
            api_shape="openai-chat",
            messages=[{"role": "user", "content": "use a tool"}],
            raw={"tools": [{"type": "function", "function": {"name": "read_file"}}]},
        )

        reason = RouterPreflightPolicy(config).skip_reason(agent, request)

        self.assertIn("does not advertise tool/function-call support", reason or "")
        self.assertEqual(
            RouterPreflightPolicy(config).error_type(agent, request, reason or ""),
            NO_TOOL_CAPABLE_MODEL,
        )
        self.assertTrue(_request_has_tools(request))
        self.assertTrue(_request_has_client_tool_specs(request))

    def test_preflight_policy_uses_health_quota_metadata(self) -> None:
        agent = AgentConfig(name="quota", provider="openai-compatible", model="m", free=True)
        health = ProviderHealth(
            quota_exhausted=True,
            cooldown_until=time.time() + 60,
        )
        request = HubRequest(
            session_id="s",
            messages=[{"role": "user", "content": "hello"}],
        )

        reason = RouterPreflightPolicy(HubConfig(free_only=False)).skip_reason(
            agent,
            request,
            health=health,
        )

        self.assertIn("out of quota", reason or "")

    def test_preflight_policy_preserves_missing_key_configuration_error(self) -> None:
        agent = AgentConfig(
            name="cloud",
            provider="openai",
            model="m",
            api_key_env="AGENT_HUB_MISSING_TEST_KEY",
        )
        request = HubRequest(session_id="s", messages=[{"role": "user", "content": "hello"}])

        config = HubConfig(free_only=False)

        reason = RouterPreflightPolicy(config).skip_reason(agent, request)

        self.assertEqual(reason, "Agent is missing API key env AGENT_HUB_MISSING_TEST_KEY")
        self.assertEqual(
            RouterPreflightPolicy(config).error_type(agent, request, reason or ""),
            "configuration_error",
        )

    def test_router_diagnostics_build_status_and_capability_graph(self) -> None:
        config = HubConfig(
            routes=[RouteRule(name="coding", agents=["tooly"])],
            agents={
                "tooly": AgentConfig(
                    name="tooly",
                    provider="openai-compatible",
                    model="m",
                    supports_function_calling=True,
                    supports_streaming=True,
                    context_window=8192,
                )
            },
        )
        snapshot = {
            "tooly": {
                "available": True,
                "health": "healthy",
                "latency_ms": 12.5,
                "score": 42.0,
                "context_window": 8192,
            }
        }

        status = build_provider_status(config, snapshot)
        graph = build_capability_graph(config, snapshot)

        self.assertTrue(status[0]["supports_tools"])
        self.assertTrue(status[0]["streaming"])
        self.assertEqual(graph["object"], "agent_hub.capability_graph")
        self.assertTrue(graph["nodes"][0]["capabilities"]["tools"])
        self.assertEqual(graph["edges"][0]["route"], "coding")


if __name__ == "__main__":
    unittest.main()
