from __future__ import annotations

import unittest

from agent_hub.models import HubResponse
from agent_hub.payloads import (
    anthropic_message_response,
    anthropic_stream_events,
    openai_chat_response,
    openai_stream_events,
    openai_response_response,
    openai_response_stream_events,
    request_from_anthropic_messages,
    request_from_native,
    request_from_openai_chat,
    request_from_openai_responses,
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

    def test_openai_model_alias_selects_route(self) -> None:
        request = request_from_openai_chat(
            {
                "model": "agent-hub-coding",
                "messages": [{"role": "user", "content": "fix tests"}],
            }
        )

        self.assertEqual(request.route, "coding")
        self.assertIsNone(request.preferred_agent)

    def test_openai_model_agent_prefix_selects_preferred_agent(self) -> None:
        request = request_from_openai_chat(
            {
                "model": "agent:groq-qwen3-32b",
                "messages": [{"role": "user", "content": "hello"}],
            }
        )

        self.assertEqual(request.preferred_agent, "groq-qwen3-32b")

    def test_anthropic_system_is_normalized(self) -> None:
        request = request_from_anthropic_messages(
            {
                "model": "agent-hub-coding",
                "system": "Be concise",
                "messages": [{"role": "user", "content": "hello"}],
            }
        )

        self.assertEqual(request.messages[0]["role"], "system")
        self.assertEqual(request.messages[1]["role"], "user")
        self.assertEqual(request.route, "coding")

    def test_openai_responses_payload_and_response_shape(self) -> None:
        request = request_from_openai_responses(
            {
                "instructions": "Be concise",
                "input": "hello",
                "agent_hub": {"route": "cloud-agent"},
                "max_output_tokens": 123,
            }
        )

        self.assertEqual(request.api_shape, "openai-responses")
        self.assertEqual(request.messages[0]["role"], "system")
        self.assertEqual(request.messages[1]["content"], "hello")
        self.assertEqual(request.max_tokens, 123)
        self.assertEqual(request.route, "cloud-agent")

        response = HubResponse(
            request_id="hub-1",
            session_id="s1",
            agent="openai",
            provider="openai",
            model="internal-model",
            public_model="stable-alias",
            text="done",
        )
        shaped = openai_response_response(response)
        events = openai_response_stream_events(response)

        self.assertEqual(shaped["object"], "response")
        self.assertEqual(shaped["output_text"], "done")
        self.assertEqual(shaped["output"][0]["content"][0]["type"], "output_text")
        self.assertEqual(events[-1], "[DONE]")

    def test_openai_responses_tool_history_becomes_provider_neutral_messages(self) -> None:
        request = request_from_openai_responses(
            {
                "input": [
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "read_file",
                        "arguments": '{"path":"README.md"}',
                    },
                    {
                        "type": "function_call_output",
                        "call_id": "call_1",
                        "output": "file text",
                    },
                ]
            }
        )

        self.assertEqual(request.messages[0]["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(
            request.messages[0]["tool_calls"][0]["function"]["arguments"],
            '{"path":"README.md"}',
        )
        self.assertEqual(request.messages[1]["role"], "tool")
        self.assertEqual(request.messages[1]["tool_call_id"], "call_1")
        self.assertEqual(request.messages[1]["name"], "read_file")
        self.assertEqual(request.messages[1]["content"], "file text")

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
        self.assertNotIn("citations", openai)
        self.assertEqual(anthropic["content"][0]["text"], "hello")
        self.assertEqual(anthropic["model"], "stable-alias")
        self.assertNotIn("agent_hub", anthropic)
        self.assertNotIn("citations", anthropic)
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

    def test_openai_chat_response_preserves_tool_calls(self) -> None:
        response = HubResponse(
            request_id="hub-1",
            session_id="s1",
            agent="groq",
            provider="openai-compatible",
            model="internal-model",
            public_model="agent-hub",
            text="",
            raw={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": "{\"path\":\"README.md\"}",
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            finish_reason="tool_calls",
        )

        shaped = openai_chat_response(response)
        events = openai_stream_events(response)
        responses = openai_response_response(response)

        message = shaped["choices"][0]["message"]
        self.assertIsNone(message["content"])
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(events[0]["choices"][0]["delta"]["tool_calls"][0]["id"], "call_1")
        self.assertEqual(responses["output"][0]["type"], "function_call")
        self.assertEqual(responses["output"][0]["name"], "read_file")

    def test_anthropic_response_preserves_tool_use_from_openai_raw(self) -> None:
        response = HubResponse(
            request_id="hub-1",
            session_id="s1",
            agent="groq",
            provider="openai-compatible",
            model="internal-model",
            public_model="agent-hub-coding",
            text="",
            raw={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": "{\"path\":\"README.md\"}",
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            finish_reason="tool_calls",
        )

        shaped = anthropic_message_response(response)
        events = anthropic_stream_events(response)

        self.assertEqual(shaped["content"][0]["type"], "tool_use")
        self.assertEqual(shaped["content"][0]["name"], "read_file")
        self.assertEqual(shaped["content"][0]["input"]["path"], "README.md")
        self.assertEqual(shaped["stop_reason"], "tool_use")
        self.assertTrue(
            any(
                event[1].get("delta", {}).get("type") == "input_json_delta"
                for event in events
            )
        )


if __name__ == "__main__":
    unittest.main()
