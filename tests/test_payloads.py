from __future__ import annotations

import unittest

from agent_hub.models import HubResponse
from agent_hub.payloads import (
    anthropic_message_response,
    openai_chat_response,
    request_from_anthropic_messages,
    request_from_native,
    request_from_openai_chat,
)


class PayloadTests(unittest.TestCase):
    def test_native_task_becomes_user_message(self) -> None:
        request = request_from_native({"session_id": "s1", "task": "Build it", "context": "Repo"})

        self.assertEqual(request.session_id, "s1")
        self.assertTrue(request.use_session_history)
        self.assertEqual(request.messages[0]["role"], "user")
        self.assertIn("Repo", request.messages[0]["content"])
        self.assertIn("Build it", request.messages[0]["content"])

    def test_openai_payload_reads_hub_options(self) -> None:
        request = request_from_openai_chat(
            {
                "messages": [{"role": "user", "content": "hello"}],
                "agent_hub": {"route": "coding", "agent": "claude"},
                "metadata": {"session_id": "s2"},
            }
        )

        self.assertEqual(request.api_shape, "openai-chat")
        self.assertEqual(request.route, "coding")
        self.assertEqual(request.preferred_agent, "claude")
        self.assertEqual(request.session_id, "s2")
        self.assertFalse(request.use_session_history)

    def test_anthropic_system_is_normalized(self) -> None:
        request = request_from_anthropic_messages(
            {
                "system": "Be concise",
                "messages": [{"role": "user", "content": "hello"}],
            }
        )

        self.assertEqual(request.messages[0]["role"], "system")
        self.assertEqual(request.messages[1]["role"], "user")

    def test_response_shapes_hide_routing_details_by_default(self) -> None:
        response = HubResponse(
            request_id="hub-1",
            session_id="s1",
            agent="openai",
            provider="openai",
            model="internal-model",
            public_model="stable-alias",
            text="hello",
            citations=["https://example.com/source"],
            search_results=[{"title": "Source", "url": "https://example.com/source"}],
        )

        openai = openai_chat_response(response)
        anthropic = anthropic_message_response(response)
        native = response.to_native_dict()

        self.assertEqual(openai["choices"][0]["message"]["content"], "hello")
        self.assertEqual(openai["model"], "stable-alias")
        self.assertNotIn("agent_hub", openai)
        self.assertEqual(openai["citations"], ["https://example.com/source"])
        self.assertEqual(anthropic["content"][0]["text"], "hello")
        self.assertEqual(anthropic["model"], "stable-alias")
        self.assertNotIn("agent_hub", anthropic)
        self.assertEqual(native["model"], "stable-alias")
        self.assertNotIn("agent", native)
        self.assertNotIn("failover", native)
        self.assertEqual(native["search_results"][0]["title"], "Source")

    def test_response_shapes_can_include_routing_details_for_debugging(self) -> None:
        response = HubResponse(
            request_id="hub-1",
            session_id="s1",
            agent="openai",
            provider="openai",
            model="internal-model",
            public_model="stable-alias",
            text="hello",
        )

        openai = openai_chat_response(response, include_routing_details=True)
        native = response.to_native_dict(include_routing_details=True)

        self.assertEqual(openai["agent_hub"]["agent"], "openai")
        self.assertEqual(native["agent"]["model"], "internal-model")
        self.assertIn("failover", native)


if __name__ == "__main__":
    unittest.main()
