from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.tools import (
    Tool,
    ToolCall,
    ToolExecutionPipeline,
    ToolLoopRunner,
    ToolRegistry,
    ToolResult,
)


class ToolRuntimePhaseThreeTests(unittest.TestCase):
    def test_tool_loop_runner_executes_call_and_reenters_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(state_dir=root / "state", workspace_dir=root, approval_mode="auto")
            registry = ToolRegistry()
            registry.register(
                Tool(
                    name="inspect_file",
                    description="Inspect a file.",
                    input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
                    executor=_inspect_file,
                    permission="read",
                )
            )
            calls: list[HubRequest] = []
            recorded_results: list[tuple[str, bool]] = []
            events: list[tuple[str, dict]] = []
            agent = AgentConfig(name="tooly", provider="openai-compatible", model="m", free=True)
            request = HubRequest(
                session_id="s",
                messages=[{"role": "user", "content": "inspect README.md"}],
                raw={"agent_hub_tools": [{"name": "inspect_file"}], "agent_hub": {"auto_execute_tools": True}},
            )
            runner = ToolLoopRunner(
                config=config,
                registry=registry,
                pipeline=ToolExecutionPipeline(registry),
                chat_provider=lambda selected, next_request: _final_response(calls, next_request),
                record_tool_result=lambda name, ok: recorded_results.append((name, ok)),
                record_event=lambda event_type, **data: events.append((event_type, data)),
            )

            result = runner.run(
                request_id="req",
                agent=agent,
                request=request,
                initial_result=_tool_call_response("inspect_file", {"path": "README.md"}),
            )

        self.assertEqual(result.result.text, "final after tool")
        self.assertEqual(result.metadata.tool_iteration_count, 1)
        self.assertEqual(result.metadata.tool_calls[0]["name"], "inspect_file")
        self.assertTrue(result.metadata.tool_results[0]["ok"])
        self.assertEqual(recorded_results, [("tooly", True)])
        self.assertEqual(events[0][0], "tool_loop_iteration")
        self.assertEqual(calls[0].messages[-1]["role"], "tool")
        self.assertTrue(calls[0].raw["agent_hub"]["auto_execute_tools"])

    def test_tool_loop_runner_leaves_client_owned_tools_for_client(self) -> None:
        config = HubConfig(approval_mode="auto")
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="inspect_file",
                description="Inspect a file.",
                input_schema={"type": "object"},
                executor=_inspect_file,
                permission="read",
            )
        )
        chat_calls: list[HubRequest] = []
        request = HubRequest(
            session_id="s",
            messages=[{"role": "user", "content": "inspect"}],
            raw={
                "tools": [
                    {
                        "type": "function",
                        "function": {"name": "inspect_file", "parameters": {"type": "object"}},
                    }
                ]
            },
        )
        initial = _tool_call_response("inspect_file", {"path": "README.md"})

        result = ToolLoopRunner(
            config=config,
            registry=registry,
            pipeline=ToolExecutionPipeline(registry),
            chat_provider=lambda selected, next_request: _final_response(chat_calls, next_request),
        ).run(
            request_id="req",
            agent=AgentConfig(name="tooly", provider="openai-compatible", model="m", free=True),
            request=request,
            initial_result=initial,
        )

        self.assertIs(result.result, initial)
        self.assertEqual(chat_calls, [])
        self.assertEqual(result.metadata.tool_iteration_count, 0)


def _inspect_file(call: ToolCall, context: object) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=True,
        content={"path": call.arguments.get("path"), "content": "evidence"},
    )


def _final_response(calls: list[HubRequest], request: HubRequest) -> ProviderResult:
    calls.append(request)
    return ProviderResult(text="final after tool", model="m", raw={}, finish_reason="stop")


def _tool_call_response(name: str, arguments: dict[str, object]) -> ProviderResult:
    import json

    return ProviderResult(
        text="",
        model="m",
        finish_reason="tool_calls",
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
                                    "name": name,
                                    "arguments": json.dumps(arguments),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    )


if __name__ == "__main__":
    unittest.main()
