from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

from agent_hub.api.compatibility import (
    apply_model_routing,
    attach_internal_client_metadata,
    available_model_ids,
    model_rows,
    openai_model_rows,
    response_headers,
    safe_header_value,
    stream_response_headers,
)
from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.core.router import AgentRouter
from agent_hub.models import FailoverEvent, HubRequest, HubResponse


class ApiCompatibilityPhaseEightTests(unittest.TestCase):
    def test_model_catalog_rows_are_owned_by_api_compatibility_layer(self) -> None:
        config = HubConfig(
            default_route=["tooly"],
            routes=[RouteRule(name="coding", agents=["tooly"])],
            agents={
                "tooly": AgentConfig(
                    name="tooly",
                    provider="openai-compatible",
                    model="tool-model",
                    base_url="http://127.0.0.1:9999",
                    free=True,
                    enabled=True,
                    supports_tools=True,
                )
            },
        )
        router = AgentRouter(config)

        rows = model_rows(config, router)
        ids = {row["id"] for row in rows}
        openai_rows = openai_model_rows(config, router)

        self.assertIn("agent-hub-coding", ids)
        self.assertIn("coding", ids)
        self.assertIn("agent:tooly", ids)
        self.assertIn("tooly", ids)
        self.assertIn("tool-model", ids)
        self.assertIn("agent-hub-coding", available_model_ids(config, router))
        self.assertTrue(all(row["object"] == "model" for row in openai_rows))
        self.assertTrue(all("agent_hub" not in row for row in openai_rows))

    def test_route_alias_stays_listed_while_provider_is_on_cooldown(self) -> None:
        config = HubConfig(
            default_route=["tooly"],
            routes=[RouteRule(name="coding", agents=["tooly"])],
            agents={
                "tooly": AgentConfig(
                    name="tooly",
                    provider="openai-compatible",
                    model="tool-model",
                    base_url="http://127.0.0.1:9999",
                    free=True,
                    enabled=True,
                    supports_tools=True,
                )
            },
        )
        router = AgentRouter(config)
        router.cooldown_agent("tooly", 60)

        rows = model_rows(config, router)
        alias = next(row for row in rows if row["id"] == "agent-hub-coding")

        self.assertTrue(alias["agent_hub"]["available"])
        self.assertEqual(alias["agent_hub"]["recommended_agent"], "tooly")
        self.assertIn("agent-hub-coding", available_model_ids(config, router))
        self.assertIn("agent-hub-coding", {row["id"] for row in openai_model_rows(config, router)})

    def test_coding_alias_stays_hidden_without_tool_capable_visible_agent(self) -> None:
        config = HubConfig(
            compatibility_mode={"emulate_tools": False},
            default_route=["plain"],
            routes=[RouteRule(name="coding", agents=["plain"])],
            agents={
                "plain": AgentConfig(
                    name="plain",
                    provider="openai-compatible",
                    model="plain-model",
                    base_url="http://127.0.0.1:9999",
                    free=True,
                    enabled=True,
                )
            },
        )
        router = AgentRouter(config)

        rows = model_rows(config, router)
        alias = next(row for row in rows if row["id"] == "agent-hub-coding")

        self.assertFalse(alias["agent_hub"]["available"])
        self.assertNotIn("agent-hub-coding", available_model_ids(config, router))
        self.assertNotIn("agent-hub-coding", {row["id"] for row in openai_model_rows(config, router)})

    def test_response_headers_preserve_compatibility_and_context_metadata(self) -> None:
        response = HubResponse(
            request_id="hub-1",
            session_id="s",
            agent="tooly",
            provider="openai-compatible",
            model="tool-model",
            public_model="agent-hub-coding",
            text="ok",
            raw={"agent_hub": {"context_usage": {"estimated_tokens_saved": 12, "suspiciously_empty": True}}},
            failover=[
                FailoverEvent(
                    agent="fallback",
                    provider="echo",
                    model="fallback-model",
                    reason="permission",
                    error_type="permission_required",
                )
            ],
        )

        headers = response_headers(response, _FakeRouter())

        self.assertEqual(headers["X-Agent-Hub-Agent"], "tooly")
        self.assertEqual(headers["X-AgentHub-Permission-Status"], "required")
        self.assertEqual(headers["X-AgentHub-Safe-Mode"], "on")
        self.assertEqual(headers["X-AgentHub-Tokens-Saved"], "12")
        self.assertEqual(headers["X-AgentHub-Context-Warning"], "suspiciously_empty")
        self.assertEqual(headers["X-Agent-Hub-Fallback-Models"], "fallback-model")
        self.assertEqual(headers["X-Agent-Hub-Requests-Remaining"], "7")

    def test_stream_headers_and_safe_header_values_are_compatibility_helpers(self) -> None:
        stream = _Stream(
            agent=_Agent(name="tooly", provider="openai-compatible"),
            model="tool-model",
            failover=[
                FailoverEvent(
                    agent="fallback",
                    provider="echo",
                    model="fallback-model",
                    reason="fallback",
                )
            ],
        )

        headers = stream_response_headers(stream, _FakeRouter())

        self.assertEqual(headers["X-Agent-Hub-Agent"], "tooly")
        self.assertEqual(headers["X-Agent-Hub-Provider-Score"], "0.91")
        self.assertEqual(headers["X-AgentHub-Fallback"], "fallback-model")
        self.assertEqual(safe_header_value("hello\r\nworld"), "hello  world")

    def test_malformed_agent_hub_metadata_is_ignored_when_attaching_internal_metadata(self) -> None:
        request = HubRequest(
            messages=[{"role": "user", "content": "hi"}],
            session_id="s",
            api_shape="openai-chat",
            raw={"model": "agent-hub-auto", "agent_hub": "not-a-dict"},
            metadata={"user_agent": "cline"},
        )

        apply_model_routing(HubConfig(), request)
        updated = attach_internal_client_metadata(request, api_shape="openai-chat")

        self.assertEqual(updated.route, "cloud-agent")
        self.assertEqual(updated.raw["agent_hub"]["mode"], "auto")
        self.assertEqual(updated.raw["agent_hub"]["source"], "cline")
        self.assertTrue(updated.raw["agent_hub"]["health_tracking_enabled"])


class _FakeRouter:
    config = HubConfig(approval_mode="safe")

    def health_snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            "tooly": {
                "requests_remaining": 7,
                "score": 0.91,
            }
        }


@dataclass(slots=True)
class _Agent:
    name: str
    provider: str


@dataclass(slots=True)
class _Stream:
    agent: _Agent
    model: str
    failover: list[FailoverEvent]


if __name__ == "__main__":
    unittest.main()
