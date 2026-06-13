from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.core.router import AgentRouter
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.payloads import (
    anthropic_message_response,
    openai_chat_response,
    openai_response_response,
)
from agent_hub.tool_compatibility import (
    normalize_emulated_tool_result,
    prepare_tool_compatibility_request,
)


class ToolCompatibilityTests(unittest.TestCase):
    def test_text_only_model_can_return_tool_call_to_every_public_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            captured: list[HubRequest] = []
            config = HubConfig(
                state_dir=Path(tmp),
                workspace_dir=Path(tmp),
                free_only=False,
                automatic_escalation_enabled=False,
                default_route=["text-only"],
                agents={
                    "text-only": AgentConfig(
                        name="text-only",
                        provider="openai-compatible",
                        model="text-model",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    captured.append(request)
                    return ProviderResult(
                        text='{"tool_call":{"name":"read_file","arguments":{"path":"README.md"}}}',
                        model=self.agent.model,
                    )

            response = AgentRouter(config, provider_factory=Provider).route(_tool_request())

        self.assertEqual(response.agent, "text-only")
        self.assertEqual(response.finish_reason, "tool_calls")
        self.assertEqual(response.raw["agent_hub_compatibility"]["tool_mode"], "emulated")
        self.assertTrue(captured[0].messages[0]["agent_hub_tool_compatibility"])
        self.assertNotIn("tools", captured[0].raw)
        self.assertEqual(
            openai_chat_response(response)["choices"][0]["message"]["tool_calls"][0]["function"]["name"],
            "read_file",
        )
        self.assertEqual(anthropic_message_response(response)["content"][0]["type"], "tool_use")
        self.assertEqual(openai_response_response(response)["output"][0]["type"], "function_call")

    def test_emulation_rejects_unlisted_tool_name(self) -> None:
        config = HubConfig()
        agent = AgentConfig(name="plain", provider="openai-compatible", model="m")
        prepared = prepare_tool_compatibility_request(config, agent, _tool_request())
        result = normalize_emulated_tool_result(
            prepared,
            ProviderResult(
                text='{"tool_call":{"name":"delete_everything","arguments":{}}}',
                model="m",
            ),
        )

        self.assertEqual(result.finish_reason, None)
        self.assertNotIn("choices", result.raw)

    def test_malformed_raw_and_metadata_are_treated_as_empty(self) -> None:
        config = HubConfig()
        agent = AgentConfig(name="plain", provider="openai-compatible", model="m")
        request = _tool_request()
        request.raw["agent_hub"] = "not-a-dict"
        request.metadata = "not-a-dict"  # type: ignore[assignment]

        prepared = prepare_tool_compatibility_request(config, agent, request)
        result = normalize_emulated_tool_result(
            prepared,
            ProviderResult(
                text='{"tool_call":{"name":"read_file","arguments":{"path":"README.md"}}}',
                model="m",
                raw="not-a-dict",  # type: ignore[arg-type]
            ),
        )

        self.assertEqual(prepared.raw["agent_hub"]["tool_compatibility"]["mode"], "emulated")
        self.assertEqual(prepared.metadata["tool_compatibility"]["mode"], "emulated")
        self.assertEqual(result.finish_reason, "tool_calls")
        self.assertEqual(result.raw["agent_hub_compatibility"]["tool_mode"], "emulated")

    def test_recommendations_include_emulated_tool_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp),
                workspace_dir=Path(tmp),
                free_only=False,
                default_route=["plain"],
                agents={
                    "plain": AgentConfig(
                        name="plain",
                        provider="openai-compatible",
                        model="m",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            rows = AgentRouter(config).recommend(_tool_request(), needs_tools=True)

        self.assertEqual(rows[0]["agent"], "plain")
        self.assertFalse(rows[0]["supports_tools"])
        self.assertTrue(rows[0]["effective_supports_tools"])
        self.assertEqual(rows[0]["tool_compatibility"], "emulated")


def _tool_request() -> HubRequest:
    return HubRequest(
        session_id="s",
        api_shape="openai-chat",
        messages=[{"role": "user", "content": "Read README.md"}],
        raw={
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    },
                }
            ]
        },
    )


if __name__ == "__main__":
    unittest.main()
