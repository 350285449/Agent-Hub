from __future__ import annotations

import unittest

from agent_hub.api.compatibility import (
    apply_model_routing,
    compatibility_endpoint,
    debug_api_shape,
    model_lookup_error,
    request_from_compat_payload,
    response_for_shape,
)
from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.models import HubRequest, HubResponse


class ApiCompatibilityPhaseSevenTests(unittest.TestCase):
    def test_endpoint_registry_maps_compatibility_paths(self) -> None:
        self.assertEqual(compatibility_endpoint("/v1/chat/completions").api_shape, "openai-chat")
        self.assertEqual(compatibility_endpoint("/v1/responses").response_shape, "openai-responses")
        self.assertTrue(compatibility_endpoint("/v1/agent").agent_mode_default)
        self.assertIsNone(compatibility_endpoint("/unknown"))

    def test_header_metadata_and_client_compatibility_are_attached_to_requests(self) -> None:
        request = request_from_compat_payload(
            {
                "model": "agent-hub-coding",
                "messages": [{"role": "user", "content": "hello"}],
            },
            {
                "User-Agent": "Cline/1.0",
                "X-Agent-Hub-Session-ID": "session-from-header",
            },
            api_shape="openai-chat",
        )

        self.assertEqual(request.session_id, "session-from-header")
        self.assertEqual(request.route, "coding")
        self.assertEqual(request.metadata["source"], "cline")
        self.assertEqual(request.metadata["client_compatibility"], "openai")
        self.assertTrue(request.raw["agent_hub"]["health_tracking_enabled"])

    def test_model_routing_and_lookup_errors_live_in_api_compatibility_layer(self) -> None:
        config = HubConfig(
            routes=[RouteRule(name="coding", agents=["tooly"])],
            agents={"tooly": AgentConfig(name="tooly", provider="echo", model="tool-model")},
        )
        request = HubRequest(
            session_id="s",
            api_shape="openai-chat",
            raw={"model": "agent:tooly"},
            messages=[{"role": "user", "content": "hello"}],
        )

        apply_model_routing(config, request)

        self.assertEqual(request.preferred_agent, "tooly")
        self.assertIsNone(model_lookup_error(config, request))
        self.assertEqual(
            model_lookup_error(
                config,
                HubRequest(
                    session_id="s",
                    api_shape="openai-chat",
                    raw={"model": "agent:missing"},
                    messages=[],
                ),
            )["type"],
            "model_not_found",
        )

    def test_response_for_shape_preserves_existing_payload_shapes(self) -> None:
        response = HubResponse(
            request_id="hub-1",
            session_id="s",
            agent="tooly",
            provider="echo",
            model="echo",
            public_model="agent-hub-coding",
            text="hello",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )

        self.assertEqual(response_for_shape(response, "openai-chat")["object"], "chat.completion")
        self.assertEqual(response_for_shape(response, "openai-responses")["object"], "response")
        self.assertEqual(response_for_shape(response, "anthropic-messages")["type"], "message")
        self.assertEqual(response_for_shape(response, "native")["object"], "agent_hub.response")

    def test_debug_api_shape_inference_is_in_compatibility_layer(self) -> None:
        self.assertEqual(debug_api_shape({"input": "hello"}), "openai-responses")
        self.assertEqual(debug_api_shape({"messages": [], "system": "x", "model": "claude"}), "anthropic-messages")


if __name__ == "__main__":
    unittest.main()
