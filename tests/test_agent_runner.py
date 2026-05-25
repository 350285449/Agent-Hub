from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_hub.agent_tools import AgentToolbox, create_workspace_checkpoint, restore_workspace_checkpoint
from agent_hub.agent_runner import AgentRunner, _is_repository_file_path
from agent_hub.config import AgentConfig, HubConfig
from agent_hub.models import HubRequest, HubResponse, ProviderResult
from agent_hub.router import AgentRouter, estimate_input_tokens
from agent_hub.providers import ProviderError


class AgentRunnerTests(unittest.TestCase):
    def test_repository_file_path_rejects_symbol_like_graph_nodes(self) -> None:
        self.assertFalse(_is_repository_file_path("VALUE", known_files=set()))
        self.assertFalse(_is_repository_file_path("Class.method", known_files=set()))
        self.assertFalse(_is_repository_file_path("package/module", known_files=set()))
        self.assertFalse(_is_repository_file_path("state/provider_health.json", known_files=set()))
        self.assertTrue(_is_repository_file_path("app.py", known_files=set()))
        self.assertTrue(_is_repository_file_path("agent_hub/app.py", known_files=set()))
        self.assertTrue(_is_repository_file_path("README", known_files=set()))
        self.assertTrue(_is_repository_file_path("LICENSE", known_files=set()))
        self.assertTrue(_is_repository_file_path("Dockerfile", known_files=set()))
        self.assertFalse(_is_repository_file_path("docs/README", known_files=set()))
        self.assertTrue(_is_repository_file_path("docs/README", known_files={"docs/README"}))
        self.assertTrue(_is_repository_file_path("tools/BUILD", known_files={"tools/BUILD"}))

    def test_agent_loop_executes_tool_and_returns_final_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("hello from a local file", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            test_case = self

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    if any("Tool result for read_file" in message.get("content", "") for message in request.messages):
                        test_case.assertIn("reasoning_state", request.raw["agent_hub_runtime"])
                        return ProviderResult(
                            text='{"action":"final","answer":"I read note.txt."}',
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"tool","tool":"read_file","args":{"path":"note.txt"}}',
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Read note.txt"}],
                    use_session_history=True,
                )
            )

            self.assertEqual(response.text, "I read note.txt.")
            steps = response.raw["agent_hub"]["steps"]
            self.assertEqual(steps[0]["tool"], "read_file")
            self.assertIn("hello from a local file", steps[0]["result"]["result"]["content"])
            self.assertNotIn("agent_hub", response.to_native_dict())
            self.assertIn("agent_hub", response.to_native_dict(include_routing_details=True))
            state = response.raw["agent_hub"]["reasoning_state"]
            self.assertIn("note.txt", state["inspected_files"])
            plan = response.raw["agent_hub"]["execution_plan"]
            self.assertTrue(any(node.endswith("-inspect") for node in plan["completed_nodes"]))
            self.assertTrue(plan["active_node"].endswith("-edit"))
            session = router.session_store.load("agent")
            self.assertIn("reasoning_state", session)
            self.assertIn("note.txt", session["reasoning_state"]["inspected_files"])
            self.assertIn("execution_plan", session["reasoning_state"])

    def test_agent_loop_emits_progress_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("hello from a local file", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    if any("Tool result for read_file" in message.get("content", "") for message in request.messages):
                        return ProviderResult(
                            text='{"action":"final","answer":"I read note.txt."}',
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"tool","tool":"read_file","args":{"path":"note.txt"}}',
                        model=self.agent.model,
                    )

            events: list[dict] = []
            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Read note.txt"}],
                ),
                event_sink=events.append,
            )

            self.assertEqual(response.text, "I read note.txt.")
            event_types = [event["type"] for event in events]
            self.assertIn("agent_started", event_types)
            self.assertIn("model_request", event_types)
            self.assertIn("model_response", event_types)
            self.assertIn("tool_started", event_types)
            self.assertIn("tool_finished", event_types)
            self.assertIn("agent_final", event_types)
            tool_started = next(event for event in events if event["type"] == "tool_started")
            self.assertEqual(tool_started["tool"], "read_file")
            self.assertIn("note.txt", tool_started["message"])
            tool_finished = next(event for event in events if event["type"] == "tool_finished")
            self.assertTrue(tool_finished["ok"])
            self.assertEqual(tool_finished["result"]["path"], "note.txt")

    def test_agent_loop_sends_native_workspace_tool_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seen_tools: list[list[dict]] = []
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                allow_shell_tools=True,
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    seen_tools.append(list(request.raw.get("agent_hub_tools", [])))
                    return ProviderResult(
                        text='{"action":"final","answer":"Tool schemas are present."}',
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Edit files"}],
                )
            )

            self.assertEqual(response.text, "Tool schemas are present.")
            tool_names = {tool["name"] for tool in seen_tools[0]}
            self.assertIn("write_file", tool_names)
            self.assertIn("replace_in_file", tool_names)
            self.assertIn("run_command", tool_names)

    def test_agent_loop_accepts_tool_name_as_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n\nNeeds comments.\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    if any("Tool result for read_file" in message.get("content", "") for message in request.messages):
                        return ProviderResult(
                            text='{"action":"final","answer":"I inspected README.md."}',
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text=(
                            '{"action":"read_file","args":'
                            '{"path":"README.md","start_line":1,"line_count":200}}'
                        ),
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "add comments where necessary"}],
                )
            )

            self.assertEqual(response.text, "I inspected README.md.")
            steps = response.raw["agent_hub"]["steps"]
            self.assertEqual(steps[0]["tool"], "read_file")
            self.assertIn("# Demo", steps[0]["result"]["result"]["content"])

    def test_agent_loop_fast_finalizes_after_successful_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    return ProviderResult(
                        text=(
                            '{"action":"tool","tool":"write_file","args":'
                            '{"path":"created.txt","content":"hello\\n"}}'
                        ),
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            events: list[dict] = []
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Create created.txt"}],
                    raw={"fast_write_finalize": True},
                ),
                event_sink=events.append,
            )

            self.assertEqual(calls, 1)
            self.assertEqual((root / "created.txt").read_text(encoding="utf-8"), "hello\n")
            self.assertIn("Wrote created.txt", response.text)
            self.assertEqual(response.raw["agent_hub"]["steps"][0]["tool"], "write_file")
            self.assertIn("Agent completed after the local file edit.", [event.get("message") for event in events])
            edit_event = next(event for event in events if event["type"] == "workspace_edit")
            self.assertEqual(edit_event["path"], "created.txt")
            self.assertEqual(edit_event["action"], "wrote")

    def test_agent_loop_accepts_gemini_function_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["gemini"],
                agents={
                    "gemini": AgentConfig(
                        name="gemini",
                        provider="gemini",
                        model="gemini-test",
                        api_key="key",
                        free=True,
                    )
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    return ProviderResult(
                        text="",
                        model=self.agent.model,
                        raw={
                            "candidates": [
                                {
                                    "content": {
                                        "parts": [
                                            {
                                                "functionCall": {
                                                    "name": "write_file",
                                                    "args": {
                                                        "path": "gemini.txt",
                                                        "content": "hello from gemini\n",
                                                    },
                                                }
                                            }
                                        ]
                                    }
                                }
                            ]
                        },
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Create gemini.txt"}],
                    raw={"fast_write_finalize": True},
                )
            )

            self.assertEqual((root / "gemini.txt").read_text(encoding="utf-8"), "hello from gemini\n")
            self.assertIn("Wrote gemini.txt", response.text)

    def test_agent_loop_can_disable_fast_write_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"write_file","args":'
                                '{"path":"created.txt","content":"hello\\n"}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Model saw the write result."}',
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Create created.txt"}],
                    raw={"fast_write_finalize": False},
                )
            )

            self.assertEqual(calls, 2)
            self.assertEqual(response.text, "Model saw the write result.")

    def test_agent_loop_does_not_fast_finalize_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"write_file","args":'
                                '{"path":"one.txt","content":"one\\n"}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text=(
                            '{"action":"tool","tool":"write_file","args":'
                            '{"path":"two.txt","content":"two\\n"}}'
                        )
                        if calls == 2
                        else '{"action":"final","answer":"Both files are done."}',
                        model=self.agent.model,
                    )

            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Create one.txt and two.txt"}],
                )
            )

            self.assertEqual(calls, 3)
            self.assertEqual(response.text, "Both files are done.")
            self.assertEqual((root / "one.txt").read_text(encoding="utf-8"), "one\n")
            self.assertEqual((root / "two.txt").read_text(encoding="utf-8"), "two\n")

    def test_agent_loop_validates_after_edit_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                validation_mode="basic",
                auto_validate_after_edits=True,
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"write_file","args":'
                                '{"path":"app.py","content":"VALUE = 1\\n"}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Validated."}',
                        model=self.agent.model,
                    )

            events: list[dict] = []
            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Create app.py"}],
                ),
                event_sink=events.append,
            )

            self.assertEqual(response.text, "Validated.")
            first_step = response.raw["agent_hub"]["steps"][0]
            self.assertTrue(first_step["result"]["validation"]["ok"])
            self.assertIn("validation_started", [event["type"] for event in events])
            self.assertIn("validation_finished", [event["type"] for event in events])

    def test_agent_loop_reports_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                validation_mode="basic",
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"write_file","args":'
                                '{"path":"bad.py","content":"def broken(:\\n"}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Validation failure was reported."}',
                        model=self.agent.model,
                    )

            events: list[dict] = []
            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Create bad.py"}],
                ),
                event_sink=events.append,
            )

            validation = response.raw["agent_hub"]["steps"][0]["result"]["validation"]
            self.assertFalse(validation["ok"])
            self.assertEqual(response.text, "Validation failure was reported.")
            self.assertIn("validation_failed", [event["type"] for event in events])

    def test_agent_loop_recovers_malformed_tool_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n\nNeeds comments.\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    if any("Tool result for read_file" in message.get("content", "") for message in request.messages):
                        return ProviderResult(
                            text='{"action":"final","answer":"I recovered the tool call."}',
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text=(
                            "```json\n"
                            "{\n"
                            '  "action": "tool",\n'
                            '  "tool": "read_file",\n'
                            '  "args": {\n'
                            '    "path": README.md\n'
                            "  }\n"
                            "}\n"
                            "```"
                        ),
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "create comments where necessary"}],
                )
            )

            self.assertEqual(response.text, "I recovered the tool call.")
            steps = response.raw["agent_hub"]["steps"]
            self.assertEqual(steps[0]["tool"], "read_file")
            self.assertIn("# Demo", steps[0]["result"]["result"]["content"])

    def test_agent_loop_reprompts_unknown_json_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            seen_messages: list[list[dict]] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    seen_messages.append(request.messages)
                    if len(seen_messages) == 1:
                        return ProviderResult(
                            text='{"action":"initial_greeting"}',
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Recovered after correction."}',
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "add comments where necessary"}],
                )
            )

            self.assertEqual(response.text, "Recovered after correction.")
            self.assertEqual(len(seen_messages), 2)
            self.assertIn("Invalid Agent Hub JSON response", seen_messages[1][-1]["content"])
            self.assertIn("unknown action 'initial_greeting'", seen_messages[1][-1]["content"])

    def test_agent_loop_reprompts_plain_text_model_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            seen_messages: list[list[dict]] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    seen_messages.append(request.messages)
                    if len(seen_messages) == 1:
                        return ProviderResult(
                            text="I'm ready to help.",
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Recovered from plain text."}',
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "add comments where needed"}],
                )
            )

            self.assertEqual(response.text, "Recovered from plain text.")
            self.assertEqual(len(seen_messages), 2)
            self.assertIn("response was not a JSON object", seen_messages[1][-1]["content"])

    def test_agent_loop_fails_over_after_invalid_response_when_possible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["bad", "good"],
                agents={
                    "bad": AgentConfig(
                        name="bad",
                        provider="openai-compatible",
                        model="bad-test",
                        base_url="http://127.0.0.1:9999",
                    ),
                    "good": AgentConfig(
                        name="good",
                        provider="openai-compatible",
                        model="good-test",
                        base_url="http://127.0.0.1:9998",
                    ),
                },
            )
            calls: list[str] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(self.agent.name)
                    if self.agent.name == "bad":
                        return ProviderResult(text="I can help with that.", model=self.agent.model)
                    return ProviderResult(
                        text='{"action":"final","answer":"Recovered with the next agent."}',
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            events: list[dict] = []
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "remove comments"}],
                ),
                event_sink=events.append,
            )

            self.assertEqual(response.text, "Recovered with the next agent.")
            self.assertEqual(calls, ["bad", "good"])
            self.assertTrue(any(event["type"] == "invalid_response" for event in events))
            self.assertTrue(
                any("Invalid agent message" in event.reason for event in response.failover)
            )

    def test_agent_loop_stops_after_repeated_invalid_responses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["bad"],
                agents={
                    "bad": AgentConfig(
                        name="bad",
                        provider="openai-compatible",
                        model="bad-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    return ProviderResult(text="Still not JSON.", model=self.agent.model)

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "remove comments"}],
                )
            )

            self.assertEqual(calls, 2)
            self.assertTrue(response.raw["agent_hub"]["stopped"])
            self.assertIn("repeated model responses", response.text)

    def test_agent_loop_reprompts_missing_required_tool_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            seen_messages: list[list[dict]] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    seen_messages.append(request.messages)
                    if len(seen_messages) == 1:
                        return ProviderResult(
                            text='{"action":"tool","tool":"read_file","args":{}}',
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Recovered from missing args."}',
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "read README.md"}],
                )
            )

            self.assertEqual(response.text, "Recovered from missing args.")
            self.assertEqual(response.raw["agent_hub"]["steps"], [])
            self.assertIn("read_file requires args.path", seen_messages[1][-1]["content"])

    def test_agent_loop_stops_when_echo_fallback_is_reached_after_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("hello", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                debug_echo_enabled=True,
                default_route=["local", "echo"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    ),
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="local-echo",
                    ),
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    if self.agent.name == "echo":
                        return ProviderResult(
                            text="[echo] Tool result for read_file: {}",
                            model=self.agent.model,
                        )
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text='{"action":"tool","tool":"read_file","args":{"path":"note.txt"}}',
                            model=self.agent.model,
                        )
                    raise ProviderError("local model stopped", retryable=True)

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "read note.txt"}],
                )
            )

            self.assertIn("echo fallback", response.text)
            self.assertTrue(response.raw["agent_hub"]["stopped"])
            self.assertEqual(response.raw["agent_hub"]["steps"][0]["tool"], "read_file")

    def test_file_tools_reject_paths_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / f"{root.name}-outside.txt"
            outside.write_text("secret", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    if any("Tool result for read_file" in message.get("content", "") for message in request.messages):
                        return ProviderResult(
                            text='{"action":"final","answer":"Path was blocked."}',
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text=f'{{"action":"tool","tool":"read_file","args":{{"path":"../{outside.name}"}}}}',
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Read outside.txt"}],
                )
            )

            self.assertEqual(response.text, "Path was blocked.")
            result = response.raw["agent_hub"]["steps"][0]["result"]
            self.assertFalse(result["ok"])
            self.assertIn("escapes workspace", result["error"])

    def test_replace_in_file_requires_exact_replacement_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.py"
            target.write_text("print('old')\n", encoding="utf-8")
            config = HubConfig(workspace_dir=root)
            toolbox = AgentToolbox(
                config,
                HubRequest(session_id="agent", messages=[]),
            )

            result = toolbox.run(
                "replace_in_file",
                {
                    "path": "app.py",
                    "old": "print('old')",
                    "new": "print('new')",
                    "expected_replacements": 1,
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(target.read_text(encoding="utf-8"), "print('new')\n")

            failed = toolbox.run(
                "replace_in_file",
                {
                    "path": "app.py",
                    "old": "missing",
                    "new": "x",
                    "expected_replacements": 1,
                },
            )

            self.assertFalse(failed["ok"])
            self.assertIn("Expected 1 replacement", failed["error"])

    def test_apply_patch_can_edit_multiple_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "README.md").write_text("# Old\n", encoding="utf-8")
            toolbox = AgentToolbox(
                HubConfig(workspace_dir=root),
                HubRequest(session_id="agent", messages=[]),
            )

            result = toolbox.run(
                "apply_patch",
                {
                    "summary": "Update app and docs",
                    "changes": [
                        {
                            "path": "app.py",
                            "old": "VALUE = 1",
                            "new": "VALUE = 2",
                            "expected_replacements": 1,
                        },
                        {"path": "README.md", "content": "# New\n"},
                    ],
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 2\n")
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "# New\n")
            self.assertEqual(result["result"]["paths"], ["app.py", "README.md"])

    def test_apply_patch_accepts_unified_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            toolbox = AgentToolbox(
                HubConfig(workspace_dir=root),
                HubRequest(session_id="agent", messages=[]),
            )

            result = toolbox.run(
                "apply_patch",
                {
                    "patch": (
                        "--- a/app.py\n"
                        "+++ b/app.py\n"
                        "@@ -1 +1 @@\n"
                        "-VALUE = 1\n"
                        "+VALUE = 2\n"
                    )
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 2\n")

    def test_apply_patch_validates_paths_before_applying(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / f"{root.name}-outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            target = root / "app.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            toolbox = AgentToolbox(
                HubConfig(workspace_dir=root),
                HubRequest(session_id="agent", messages=[]),
            )

            result = toolbox.run(
                "apply_patch",
                {
                    "changes": [
                        {"path": "app.py", "content": "VALUE = 2\n"},
                        {"path": f"../{outside.name}", "content": "bad\n"},
                    ]
                },
            )

            self.assertFalse(result["ok"])
            self.assertIn("escapes workspace", result["error"])
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 1\n")
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")

    def test_failed_apply_patch_applies_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            toolbox = AgentToolbox(
                HubConfig(workspace_dir=root),
                HubRequest(session_id="agent", messages=[]),
            )

            result = toolbox.run(
                "apply_patch",
                {
                    "changes": [
                        {"path": "app.py", "content": "VALUE = 2\n"},
                        {
                            "path": "missing.py",
                            "old": "x",
                            "new": "y",
                            "expected_replacements": 1,
                        },
                    ]
                },
            )

            self.assertFalse(result["ok"])
            self.assertIn("missing file", result["error"])
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 1\n")

    def test_apply_patch_approval_request_includes_all_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("A = 1\n", encoding="utf-8")
            (root / "b.py").write_text("B = 1\n", encoding="utf-8")
            toolbox = AgentToolbox(
                HubConfig(workspace_dir=root, approval_mode="ask"),
                HubRequest(session_id="agent", messages=[]),
            )

            result = toolbox.run(
                "apply_patch",
                {
                    "summary": "Update two files",
                    "changes": [
                        {"path": "a.py", "old": "A = 1", "new": "A = 2"},
                        {"path": "b.py", "old": "B = 1", "new": "B = 2"},
                    ],
                    "commands": ["python -m unittest discover -v"],
                    "validation_plan": "Run syntax and unit tests.",
                },
            )

            self.assertFalse(result["ok"])
            self.assertTrue(result["approval_required"])
            self.assertEqual(result["affected_files"], ["a.py", "b.py"])
            self.assertIn("Update two files", result["summary"])
            self.assertIn("--- a/a.py", result["patch_preview"])
            self.assertIn("python -m unittest", result["commands"][0])
            self.assertEqual(result["risk_level"], "medium")
            self.assertIn("2 file(s)", result["impact"])
            self.assertEqual(result["estimated_impact"]["files"], 2)
            groups = {group["group"] for group in result["file_groups"]}
            self.assertIn("implementation", groups)
            self.assertEqual((root / "a.py").read_text(encoding="utf-8"), "A = 1\n")

    def test_apply_patch_approval_granted_applies_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "a.py"
            target.write_text("A = 1\n", encoding="utf-8")
            toolbox = AgentToolbox(
                HubConfig(workspace_dir=root, approval_mode="ask"),
                HubRequest(
                    session_id="agent",
                    messages=[],
                    raw={"agent_hub": {"approval_granted": True}},
                ),
            )

            result = toolbox.run(
                "apply_patch",
                {"changes": [{"path": "a.py", "old": "A = 1", "new": "A = 2"}]},
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["approval_granted"])
            self.assertEqual(target.read_text(encoding="utf-8"), "A = 2\n")

    def test_agent_loop_emits_patch_approval_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("A = 1\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                approval_mode="ask",
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    return ProviderResult(
                        text=(
                            '{"action":"tool","tool":"apply_patch","args":'
                            '{"summary":"Update a.py","changes":['
                            '{"path":"a.py","old":"A = 1","new":"A = 2"}],'
                            '"validation_plan":"py_compile"}}'
                        ),
                        model=self.agent.model,
                    )

            events: list[dict] = []
            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Update a.py"}]),
                event_sink=events.append,
            )

            event_types = [event["type"] for event in events]
            self.assertIn("patch_preview", event_types)
            self.assertIn("approval_required", event_types)
            approval = next(event for event in events if event["type"] == "approval_required")
            self.assertEqual(approval["affected_files"], ["a.py"])
            self.assertIn("--- a/a.py", approval["patch_preview"])
            self.assertIn("Approval required", response.text)
            self.assertEqual((root / "a.py").read_text(encoding="utf-8"), "A = 1\n")

    def test_approval_pause_resume_preserves_reasoning_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("A = 1\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                approval_mode="ask",
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0
            test_case = self

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        state = request.raw["agent_hub_runtime"]["reasoning_state"]
                        test_case.assertTrue(state["approval_history"])
                        test_case.assertEqual(state["approval_history"][-1]["affected_files"], ["a.py"])
                    if calls in {1, 2}:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch","args":'
                                '{"summary":"Update a.py","changes":['
                                '{"path":"a.py","old":"A = 1","new":"A = 2"}]}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Applied after approval."}',
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            events: list[dict] = []
            first = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent-approval",
                    messages=[{"role": "user", "content": "Update a.py"}],
                    use_session_history=True,
                ),
                event_sink=events.append,
            )

            self.assertIn("Approval required", first.text)
            approval_event = next(event for event in events if event["type"] == "approval_required")
            self.assertEqual(approval_event["affected_execution_nodes"], [approval_event["execution_node"]])
            self.assertIn("repository_impact", approval_event)
            self.assertEqual(approval_event["rollback_safety"], "pre_edit_checkpoint_required")
            session = router.session_store.load("agent-approval")
            self.assertTrue(session["reasoning_state"]["approval_history"])
            self.assertTrue(session["reasoning_state"]["execution_plan"]["blocked_nodes"])

            second = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent-approval",
                    messages=[{"role": "user", "content": "Approved."}],
                    use_session_history=True,
                    raw={"agent_hub": {"approval_granted": True}},
                )
            )

            self.assertEqual(second.text, "Applied after approval.")
            self.assertEqual((root / "a.py").read_text(encoding="utf-8"), "A = 2\n")

    def test_file_tools_resolve_unique_bare_filename_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "agent_hub"
            package.mkdir()
            target = package / "config.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(workspace_dir=root)
            toolbox = AgentToolbox(
                config,
                HubRequest(session_id="agent", messages=[]),
            )

            result = toolbox.run("read_file", {"path": "config.py"})

            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["path"], "agent_hub/config.py")
            self.assertIn("VALUE = 1", result["result"]["content"])

            replaced = toolbox.run(
                "replace_in_file",
                {
                    "path": "config.py",
                    "old": "VALUE = 1",
                    "new": "VALUE = 2",
                    "expected_replacements": 1,
                },
            )

            self.assertTrue(replaced["ok"])
            self.assertEqual(replaced["result"]["path"], "agent_hub/config.py")
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 2\n")

    def test_file_tools_prefer_current_file_context_for_bare_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agent_hub").mkdir()
            (root / "vscode-extension" / "backend" / "agent_hub").mkdir(parents=True)
            direct_target = root / "config.py"
            root_target = root / "agent_hub" / "config.py"
            context_target = root / "vscode-extension" / "backend" / "agent_hub" / "config.py"
            direct_target.write_text("VALUE = 100\n", encoding="utf-8")
            root_target.write_text("VALUE = 1\n", encoding="utf-8")
            context_target.write_text("VALUE = 10\n", encoding="utf-8")
            config = HubConfig(workspace_dir=root)
            toolbox = AgentToolbox(
                config,
                HubRequest(
                    session_id="agent",
                    messages=[],
                    context=(
                        "Current file: vscode-extension/backend/agent_hub/config.py\n"
                        "Language: python"
                    ),
                ),
            )

            result = toolbox.run("read_file", {"path": "config.py"})

            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["path"], "vscode-extension/backend/agent_hub/config.py")
            self.assertIn("VALUE = 10", result["result"]["content"])

            replaced = toolbox.run(
                "replace_in_file",
                {
                    "path": "config.py",
                    "old": "VALUE = 10",
                    "new": "VALUE = 11",
                    "expected_replacements": 1,
                },
            )

            self.assertTrue(replaced["ok"])
            self.assertEqual(replaced["result"]["path"], "vscode-extension/backend/agent_hub/config.py")
            self.assertEqual(context_target.read_text(encoding="utf-8"), "VALUE = 11\n")
            self.assertEqual(direct_target.read_text(encoding="utf-8"), "VALUE = 100\n")
            self.assertEqual(root_target.read_text(encoding="utf-8"), "VALUE = 1\n")

    def test_file_tools_prefer_current_folder_context_for_bare_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "config.py").write_text("A = 1\n", encoding="utf-8")
            target = root / "b" / "config.py"
            target.write_text("B = 1\n", encoding="utf-8")
            config = HubConfig(workspace_dir=root)
            toolbox = AgentToolbox(
                config,
                HubRequest(
                    session_id="agent",
                    messages=[],
                    context="Current folder: b\nLanguage: python",
                ),
            )

            result = toolbox.run("read_file", {"path": "config.py"})

            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["path"], "b/config.py")
            self.assertIn("B = 1", result["result"]["content"])

    def test_run_command_defaults_to_current_folder_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "tools"
            folder.mkdir()
            config = HubConfig(workspace_dir=root)
            toolbox = AgentToolbox(
                config,
                HubRequest(
                    session_id="agent",
                    messages=[],
                    context="Current folder: tools",
                ),
            )

            result = toolbox.run(
                "run_command",
                {"command": "python -c \"import pathlib; print(pathlib.Path.cwd().name)\""},
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["cwd"], "tools")
            self.assertIn("tools", result["result"]["stdout"])

    def test_run_command_can_ask_for_permission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(workspace_dir=root, shell_command_policy="ask")
            prompts: list[dict] = []
            toolbox = AgentToolbox(
                config,
                HubRequest(session_id="agent", messages=[]),
                shell_permission_callback=lambda details: prompts.append(details) or True,
            )

            result = toolbox.run(
                "run_command",
                {"command": "python -c \"print('approved')\""},
            )

            self.assertTrue(result["ok"])
            self.assertEqual(prompts[0]["cwd"], ".")
            self.assertIn("approved", result["result"]["stdout"])

    def test_run_command_denies_when_permission_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(workspace_dir=root, shell_command_policy="ask")
            toolbox = AgentToolbox(
                config,
                HubRequest(session_id="agent", messages=[]),
                shell_permission_callback=lambda details: False,
            )

            result = toolbox.run(
                "run_command",
                {"command": "python -c \"print('nope')\""},
            )

            self.assertFalse(result["ok"])
            self.assertIn("denied", result["error"])

    def test_file_tools_report_ambiguous_bare_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "config.py").write_text("A = 1\n", encoding="utf-8")
            (root / "b" / "config.py").write_text("B = 1\n", encoding="utf-8")
            config = HubConfig(workspace_dir=root)
            toolbox = AgentToolbox(
                config,
                HubRequest(session_id="agent", messages=[]),
            )

            result = toolbox.run("read_file", {"path": "config.py"})

            self.assertFalse(result["ok"])
            self.assertIn("Ambiguous path 'config.py'", result["error"])
            self.assertIn("a/config.py", result["error"])
            self.assertIn("b/config.py", result["error"])

    def test_file_tools_block_unrequested_duplicate_backend_copy_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "vscode-extension" / "backend" / "agent_hub" / "config.py"
            target.parent.mkdir(parents=True)
            target.write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(workspace_dir=root)
            toolbox = AgentToolbox(
                config,
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Update config.py in the main backend."}],
                ),
            )

            result = toolbox.run(
                "replace_in_file",
                {
                    "path": "vscode-extension/backend/agent_hub/config.py",
                    "old": "VALUE = 1",
                    "new": "VALUE = 2",
                    "expected_replacements": 1,
                },
            )

            self.assertFalse(result["ok"])
            self.assertIn("duplicate workspace copy", result["error"])
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 1\n")

    def test_file_tools_allow_active_duplicate_backend_copy_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "vscode-extension" / "backend" / "agent_hub" / "config.py"
            target.parent.mkdir(parents=True)
            target.write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(workspace_dir=root)
            toolbox = AgentToolbox(
                config,
                HubRequest(
                    session_id="agent",
                    messages=[],
                    context="Current file: vscode-extension/backend/agent_hub/config.py",
                ),
            )

            result = toolbox.run(
                "replace_in_file",
                {
                    "path": "vscode-extension/backend/agent_hub/config.py",
                    "old": "VALUE = 1",
                    "new": "VALUE = 2",
                    "expected_replacements": 1,
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 2\n")

    def test_multi_file_patch_with_validation_passing(self) -> None:
        """Test that apply_patch with validation passes through and doesn't fast-finalize."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "helper.py").write_text("OTHER = 1\n", encoding="utf-8")

            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                validation_mode="basic",
                auto_validate_after_edits=True,
                validation_commands=["python -m py_compile {files}"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )

            call_count = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal call_count
                    call_count += 1
                    # First call: apply patch
                    if call_count == 1:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch",'
                                '"args":{"summary":"Update VALUE","changes":['
                                '{"path":"app.py","old":"VALUE = 1","new":"VALUE = 2"},'
                                '{"path":"helper.py","old":"OTHER = 1","new":"OTHER = 2"}'
                                ']}}'
                            ),
                            model=self.agent.model,
                        )
                    # Second call: final answer (validation passed, not fast-finalized)
                    return ProviderResult(
                        text='{"action":"final","answer":"Updated both files."}',
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Update VALUE to 2"}],
                )
            )

            self.assertEqual(response.text, "Updated both files.")
            # Should have taken 2 calls (apply_patch + final), not 1 (not fast-finalized)
            self.assertEqual(call_count, 2)
            # Both files should be updated
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 2\n")
            self.assertEqual((root / "helper.py").read_text(encoding="utf-8"), "OTHER = 2\n")

    def test_context_change_bar_blocks_edit_before_inspection_in_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                context_change_bar_mode="strict",
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0
            seen_messages: list[list[dict]] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    seen_messages.append(list(request.messages))
                    if calls == 1:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch","args":'
                                '{"summary":"Update app","changes":['
                                '{"path":"app.py","old":"VALUE = 1","new":"VALUE = 2"}]}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Stopped before editing."}',
                        model=self.agent.model,
                    )

            events: list[dict] = []
            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Update app.py"}]),
                event_sink=events.append,
            )

            self.assertEqual(response.text, "Stopped before editing.")
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 1\n")
            first = response.raw["agent_hub"]["steps"][0]["result"]
            self.assertTrue(first["context_change_bar_feedback"])
            self.assertEqual(first["recommended_tool"], "repo_map")
            self.assertIn("repo_map", first["error"])
            self.assertIn("search_files", first["policy"]["instructions"][1])
            self.assertIn("read_file", first["policy"]["instructions"][1])
            self.assertIn("Context change bar blocked", seen_messages[1][-1]["content"])
            event_types = [event["type"] for event in events]
            self.assertIn("context_score_updated", event_types)
            self.assertIn("context_bar_blocked", event_types)
            self.assertIn("repository_inspection_required", event_types)

    def test_strict_mode_allows_edit_after_repository_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="strict",
                auto_validate_after_edits=False,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text='{"action":"tool","tool":"repo_map","args":{"target":"app.py"}}',
                            model=self.agent.model,
                        )
                    if calls == 2:
                        return ProviderResult(
                            text='{"action":"tool","tool":"search_files","args":{"query":"VALUE","path":"."}}',
                            model=self.agent.model,
                        )
                    if calls == 3:
                        return ProviderResult(
                            text='{"action":"tool","tool":"read_file","args":{"path":"app.py"}}',
                            model=self.agent.model,
                        )
                    if calls == 4:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch","args":'
                                '{"summary":"Update app","changes":['
                                '{"path":"app.py","old":"VALUE = 1","new":"VALUE = 2"}]}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Updated after inspection."}',
                        model=self.agent.model,
                    )

            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Update app.py"}])
            )

            self.assertEqual(response.text, "Updated after inspection.")
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 2\n")
            state = response.raw["agent_hub"]["reasoning_state"]
            self.assertGreaterEqual(state["context_score"], 6)
            self.assertEqual(response.raw["agent_hub"]["steps"][3]["tool"], "apply_patch")

    def test_reviewer_rejects_unread_file_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="strict",
                auto_validate_after_edits=False,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text='{"action":"tool","tool":"repo_map","args":{"target":"app.py"}}',
                            model=self.agent.model,
                        )
                    if calls == 2:
                        return ProviderResult(
                            text='{"action":"tool","tool":"search_files","args":{"query":"VALUE","path":"."}}',
                            model=self.agent.model,
                        )
                    if calls == 3:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch","args":'
                                '{"summary":"Review edit","changes":['
                                '{"path":"app.py","old":"VALUE = 1","new":"VALUE = 2"}]}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Reviewer stopped unread edit."}',
                        model=self.agent.model,
                    )

            events: list[dict] = []
            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Review and update app.py"}],
                    raw={"team_agent_role": "reviewer"},
                ),
                event_sink=events.append,
            )

            self.assertEqual(response.text, "Reviewer stopped unread edit.")
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 1\n")
            feedback = response.raw["agent_hub"]["steps"][2]["result"]
            self.assertTrue(feedback["reviewer_rejected_unread_edit"])
            self.assertIn("Reviewer rejected edits against unread file", feedback["error"])
            self.assertIn("reviewer_rejected_unread_edit", [event["type"] for event in events])

    def test_reasoning_state_persists_context_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text='{"action":"tool","tool":"repo_map","args":{"target":"app.py"}}',
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Inspected."}',
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Inspect app.py"}])
            )

            state = response.raw["agent_hub"]["reasoning_state"]
            self.assertGreaterEqual(state["context_score"], 4)
            self.assertTrue(state["repository_inspection_complete"])
            session = router.session_store.load("agent")
            self.assertEqual(session["reasoning_state"]["context_score"], state["context_score"])

    def test_multi_file_task_prefers_apply_patch_after_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                auto_validate_after_edits=False,
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text='{"action":"tool","tool":"repo_map","args":{"target":"app.py"}}',
                            model=self.agent.model,
                        )
                    if calls == 2:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"write_file","args":'
                                '{"path":"app.py","content":"VALUE = 2\\n"}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Policy requested a patch."}',
                        model=self.agent.model,
                    )

            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Update implementation and tests for app.py"}],
                )
            )

            self.assertEqual(response.text, "Policy requested a patch.")
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 1\n")
            feedback = response.raw["agent_hub"]["steps"][1]["result"]
            self.assertTrue(feedback["edit_policy_feedback"])
            self.assertEqual(feedback["recommended_tool"], "apply_patch")
            self.assertIn("multi-file work", feedback["error"])

    def test_grouped_patch_updates_implementation_and_tests_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "agent_hub"
            tests = root / "tests"
            package.mkdir()
            tests.mkdir()
            (package / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
            (tests / "test_app.py").write_text(
                "from agent_hub.app import value\n\n"
                "def test_value():\n"
                "    assert value() == 1\n",
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                auto_validate_after_edits=False,
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text='{"action":"tool","tool":"repo_map","args":{"target":"agent_hub/app.py"}}',
                            model=self.agent.model,
                        )
                    if calls == 2:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch","args":'
                                '{"summary":"Update implementation and tests","changes":['
                                '{"path":"agent_hub/app.py","old":"return 1","new":"return 2"},'
                                '{"path":"tests/test_app.py","old":"assert value() == 1","new":"assert value() == 2"}'
                                ']}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Updated implementation and tests."}',
                        model=self.agent.model,
                    )

            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Update implementation and tests together"}],
                )
            )

            self.assertEqual(response.text, "Updated implementation and tests.")
            self.assertIn("return 2", (package / "app.py").read_text(encoding="utf-8"))
            self.assertIn("== 2", (tests / "test_app.py").read_text(encoding="utf-8"))
            patch_step = response.raw["agent_hub"]["steps"][1]
            self.assertEqual(patch_step["tool"], "apply_patch")
            self.assertEqual(
                patch_step["result"]["result"]["paths"],
                ["agent_hub/app.py", "tests/test_app.py"],
            )

    def test_validation_failure_feedback_loop_for_apply_patch(self) -> None:
        """Test that validation failures feed back to the agent for repair attempts."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                validation_mode="basic",
                auto_validate_after_edits=True,
                validation_repair_attempts=2,
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )

            call_count = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal call_count
                    call_count += 1

                    # Check if we've seen validation failure feedback
                    has_validation_feedback = any(
                        "Validation failed" in msg.get("content", "")
                        for msg in request.messages
                    )

                    if call_count == 1:
                        # First: apply a bad patch
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch",'
                                '"args":{"summary":"Bad patch","changes":['
                                '{"path":"app.py","old":"VALUE = 1","new":"INVALID PYTHON"}'
                                ']}}'
                            ),
                            model=self.agent.model,
                        )
                    elif call_count == 2 and has_validation_feedback:
                        # Second: receive validation feedback and apply fix
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch",'
                                '"args":{"summary":"Fix syntax error","changes":['
                                '{"path":"app.py","old":"VALUE = 1","new":"VALUE = 2"}'
                                ']}}'
                            ),
                            model=self.agent.model,
                        )
                    else:
                        # Third: finalize
                        return ProviderResult(
                            text='{"action":"final","answer":"Fixed the issue."}',
                            model=self.agent.model,
                        )

            events: list[dict] = []
            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Update VALUE"}],
                ),
                event_sink=events.append,
            )

            # Should have 3 calls: first apply_patch (fails validation), repair apply_patch, then final
            self.assertGreaterEqual(call_count, 2)
            # Final file should have the fixed value
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 2\n")
            # Should have emitted validation_repair_loop event
            event_types = [e["type"] for e in events]
            self.assertIn("validation_repair_loop", event_types)
            self.assertIn("workspace_restored", event_types)
            repairs = response.raw["agent_hub"]["repair_history"]
            self.assertEqual(repairs[0]["attempt"], 1)

    def test_agent_instructions_mention_apply_patch(self) -> None:
        """Test that agent instructions strongly bias toward apply_patch."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            config = HubConfig(workspace_dir=root)
            toolbox = AgentToolbox(
                config,
                HubRequest(session_id="agent", messages=[]),
            )
            instructions = toolbox.instructions()

            # Should mention multi-file editing workflow
            self.assertIn("MULTI-FILE EDITING WORKFLOW", instructions)
            self.assertIn("apply_patch", instructions)
            # Should warn against using single-file tools for repairs
            self.assertIn("AVOID: Stop using single-file edits after validation failures", instructions)
            # Should mention validation and testing
            self.assertIn("validation", instructions.lower())
            self.assertIn("REPOSITORY-AWARE PLANNING", instructions)
            self.assertIn("CONTEXT CHANGE BAR", instructions)
            self.assertIn("repo_map", instructions)
            self.assertIn("pyproject.toml", instructions)

    def test_repo_map_discovers_related_tests_configs_and_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "agent_hub"
            tests = root / "tests"
            package.mkdir()
            tests.mkdir()
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (package / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
            (package / "app.py").write_text(
                "from agent_hub.utils import helper\n\n"
                "class App:\n    pass\n\n"
                "def run():\n    return helper()\n",
                encoding="utf-8",
            )
            (tests / "test_app.py").write_text("from agent_hub.app import run\n", encoding="utf-8")
            toolbox = AgentToolbox(
                HubConfig(workspace_dir=root),
                HubRequest(session_id="agent", messages=[]),
            )

            result = toolbox.run("repo_map", {"target": "app.py"})

            self.assertTrue(result["ok"])
            repo_map = result["result"]
            self.assertIn("agent_hub/app.py", repo_map["related_files"])
            self.assertIn("tests/test_app.py", repo_map["test_files"])
            self.assertIn("pyproject.toml", repo_map["key_files"])
            self.assertIn("App", repo_map["symbols"]["agent_hub/app.py"])
            self.assertIn("agent_hub/utils.py", repo_map["dependency_files"])
            self.assertIn("agent_hub/utils.py", repo_map["dependency_map"]["agent_hub/app.py"])
            self.assertIn("tests/test_app.py", repo_map["reverse_dependency_map"]["agent_hub/app.py"])
            self.assertIn("run", repo_map["symbol_index"]["agent_hub/app.py"])
            self.assertIn("tests/test_app.py", repo_map["validation_targets"])

    def test_apply_patch_does_not_fast_finalize(self) -> None:
        """Test that apply_patch never fast-finalizes even when fast_write_finalize is enabled."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file1.py").write_text("a = 1\n", encoding="utf-8")
            (root / "file2.py").write_text("b = 1\n", encoding="utf-8")

            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                fast_write_finalize=True,  # Enabled, but should not apply to apply_patch
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )

            call_count = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch",'
                                '"args":{"summary":"Update both","changes":['
                                '{"path":"file1.py","old":"a = 1","new":"a = 2"},'
                                '{"path":"file2.py","old":"b = 1","new":"b = 2"}'
                                ']}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Done"}',
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Update files"}],
                )
            )

            # Should require 2 calls despite fast_write_finalize=True
            # (first for apply_patch, second for final answer)
            self.assertGreaterEqual(call_count, 2)

    def test_agent_loop_bounces_existing_file_write_to_apply_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0
            seen_messages: list[list[dict]] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    seen_messages.append(list(request.messages))
                    if calls == 1:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"write_file","args":'
                                '{"path":"app.py","content":"VALUE = 2\\n"}}'
                            ),
                            model=self.agent.model,
                        )
                    if calls == 2:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch","args":'
                                '{"summary":"Update app value","changes":['
                                '{"path":"app.py","old":"VALUE = 1","new":"VALUE = 2"}]}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Updated with patch."}',
                        model=self.agent.model,
                    )

            events: list[dict] = []
            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Update app.py"}]),
                event_sink=events.append,
            )

            self.assertEqual(response.text, "Updated with patch.")
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 2\n")
            self.assertIn("Edit policy requested apply_patch", seen_messages[1][-1]["content"])
            self.assertIn("edit_policy_feedback", [event["type"] for event in events])
            steps = response.raw["agent_hub"]["steps"]
            self.assertTrue(steps[0]["result"]["edit_policy_feedback"])
            self.assertEqual(steps[1]["tool"], "apply_patch")

    def test_agent_loop_bounces_large_replace_to_apply_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"replace_in_file","args":'
                                '{"path":"app.py","old":"VALUE = 1","new":"'
                                + ("X" * 450)
                                + '","expected_replacements":1}}'
                            ),
                            model=self.agent.model,
                        )
                    if calls == 2:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch","args":'
                                '{"summary":"Update app value","changes":['
                                '{"path":"app.py","old":"VALUE = 1","new":"VALUE = 2"}]}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Updated with patch."}',
                        model=self.agent.model,
                    )

            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Update app.py"}])
            )

            self.assertEqual(response.text, "Updated with patch.")
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 2\n")
            self.assertTrue(response.raw["agent_hub"]["steps"][0]["result"]["edit_policy_feedback"])

    def test_agent_loop_rejects_risky_apply_patch_full_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.py"
            target.write_text("VALUE = 1\n" + ("# keep\n" * 120), encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text=json.dumps(
                                {
                                    "action": "tool",
                                    "tool": "apply_patch",
                                    "args": {
                                        "summary": "Rewrite app",
                                        "changes": [
                                            {
                                                "path": "app.py",
                                                "content": "VALUE = 2\n" + ("# rewritten\n" * 120),
                                            }
                                        ],
                                    },
                                }
                            ),
                            model=self.agent.model,
                        )
                    if calls == 2:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch","args":'
                                '{"summary":"Update value surgically","changes":['
                                '{"path":"app.py","old":"VALUE = 1","new":"VALUE = 2"}]}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Updated surgically."}',
                        model=self.agent.model,
                    )

            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Update app.py"}])
            )

            self.assertEqual(response.text, "Updated surgically.")
            self.assertTrue(response.raw["agent_hub"]["steps"][0]["result"]["edit_policy_feedback"])
            self.assertIn("VALUE = 2", target.read_text(encoding="utf-8"))
            self.assertIn("# keep", target.read_text(encoding="utf-8"))

    def test_changed_files_tracked_in_trace(self) -> None:
        """Test that changed files are properly tracked in the response trace."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file1.py").write_text("a = 1\n", encoding="utf-8")
            (root / "file2.py").write_text("b = 1\n", encoding="utf-8")

            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    if any("Tool result for apply_patch" in msg.get("content", "") for msg in request.messages):
                        return ProviderResult(
                            text='{"action":"final","answer":"Updated files."}',
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text=(
                            '{"action":"tool","tool":"apply_patch",'
                            '"args":{"summary":"Update both","changes":['
                            '{"path":"file1.py","old":"a = 1","new":"a = 2"},'
                            '{"path":"file2.py","old":"b = 1","new":"b = 2"}'
                            ']}}'
                        ),
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Update files"}],
                )
            )

            # Check trace for apply_patch step
            steps = response.raw["agent_hub"]["steps"]
            apply_patch_step = next((s for s in steps if s["tool"] == "apply_patch"), None)
            self.assertIsNotNone(apply_patch_step)
            # Should have affected_files in the result
            result = apply_patch_step["result"]
            self.assertIn("result", result)
            patch_result = result["result"]
            self.assertIn("paths", patch_result)
            self.assertEqual(len(patch_result["paths"]), 2)
            self.assertIn("file1.py", patch_result["paths"])
            self.assertIn("file2.py", patch_result["paths"])

    def test_validation_failure_rolls_back_and_repairs_write_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                validation_mode="basic",
                validation_repair_attempts=2,
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0
            seen_messages: list[list[dict]] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    seen_messages.append(list(request.messages))
                    if calls == 1:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"write_file","args":'
                                '{"path":"bad.py","content":"def broken(:\\n"}}'
                            ),
                            model=self.agent.model,
                        )
                    if calls == 2:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"apply_patch","args":'
                                '{"changes":[{"path":"bad.py","content":"VALUE = 2\\n"}]}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Repaired."}',
                        model=self.agent.model,
                    )

            events: list[dict] = []
            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Create bad.py"}]),
                event_sink=events.append,
            )

            self.assertEqual(response.text, "Repaired.")
            self.assertEqual((root / "bad.py").read_text(encoding="utf-8"), "VALUE = 2\n")
            self.assertIn("restored_to_pre_edit_checkpoint", seen_messages[1][-1]["content"])
            repair_prompt = "\n".join(str(message.get("content", "")) for message in seen_messages[1])
            self.assertIn('"failure_type": "validation_failure"', repair_prompt)
            self.assertIn('"failed_categories"', repair_prompt)
            self.assertIn("SyntaxError", repair_prompt)
            event_types = [event["type"] for event in events]
            self.assertIn("workspace_restored", event_types)
            self.assertIn("validation_repair_loop", event_types)
            plan = response.raw["agent_hub"]["execution_plan"]
            self.assertTrue(any("-repair" in node["id"] for node in plan["nodes"]))

    def test_failover_preserves_validation_repair_context_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["primary", "backup"],
                validation_mode="basic",
                validation_repair_attempts=2,
                agents={
                    "primary": AgentConfig(
                        name="primary",
                        provider="openai-compatible",
                        model="primary-test",
                        base_url="http://127.0.0.1:9999",
                    ),
                    "backup": AgentConfig(
                        name="backup",
                        provider="openai-compatible",
                        model="backup-test",
                        base_url="http://127.0.0.1:9998",
                    ),
                },
            )
            primary_calls = 0
            backup_calls = 0
            backup_messages: list[list[dict]] = []
            test_case = self

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal primary_calls, backup_calls
                    if self.agent.name == "primary":
                        primary_calls += 1
                        if primary_calls == 1:
                            return ProviderResult(
                                text=(
                                    '{"action":"tool","tool":"apply_patch",'
                                    '"args":{"summary":"Introduce bad syntax","changes":['
                                    '{"path":"app.py","old":"VALUE = 1","new":"def broken(:"}'
                                    ']}}'
                                ),
                                model=self.agent.model,
                            )
                        raise ProviderError(
                            "quota exhausted",
                            status_code=429,
                            retryable=True,
                            error_type="quota_exhausted",
                        )
                    backup_calls += 1
                    backup_messages.append(list(request.messages))
                    if backup_calls > 1 and any("Tool result for apply_patch" in msg.get("content", "") for msg in request.messages):
                        return ProviderResult(
                            text='{"action":"final","answer":"Backup completed repair."}',
                            model=self.agent.model,
                        )
                    test_case.assertTrue(
                        any("Automatic repair is required" in msg.get("content", "") for msg in request.messages)
                    )
                    test_case.assertEqual(request.raw["agent_hub_runtime"]["repair_attempts_current"], 1)
                    test_case.assertIsNotNone(request.raw["agent_hub_runtime"]["pending_validation"])
                    state = request.raw["agent_hub_runtime"]["reasoning_state"]
                    test_case.assertTrue(state["validation_history"])
                    test_case.assertTrue(state["repair_history"])
                    test_case.assertIn("syntax", state["validation_history"][-1]["failed_categories"])
                    test_case.assertIn("execution_plan", request.raw["agent_hub_runtime"])
                    test_case.assertTrue(request.raw["agent_hub_runtime"]["execution_plan"]["failed_nodes"])
                    return ProviderResult(
                        text=(
                            '{"action":"tool","tool":"apply_patch",'
                            '"args":{"summary":"Repair syntax","changes":['
                            '{"path":"app.py","old":"VALUE = 1","new":"VALUE = 2"}'
                            ']}}'
                        ),
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = AgentRunner(config, router).run(
                HubRequest(
                    session_id="agent-failover",
                    messages=[{"role": "user", "content": "Update app.py"}],
                    use_session_history=True,
                )
            )

            self.assertEqual(response.text, "Backup completed repair.")
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 2\n")
            self.assertTrue(response.failover)
            self.assertIn("quota", response.failover[0].reason)
            self.assertTrue(backup_messages)
            session = router.session_store.load("agent-failover")
            self.assertEqual(session["messages"][-1]["content"], "Backup completed repair.")
            self.assertTrue(session["events"][-1]["failover"])
            state = response.raw["agent_hub"]["reasoning_state"]
            self.assertTrue(state["validation_history"])
            self.assertTrue(state["repair_history"])
            self.assertTrue(response.raw["agent_hub"]["execution_plan"]["nodes"])
            self.assertIn("reasoning_state", session)

    def test_replace_in_file_failure_gets_bounded_repair_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                default_route=["local"],
                validation_repair_attempts=1,
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0
            seen_messages: list[list[dict]] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    seen_messages.append(list(request.messages))
                    if calls == 1:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"replace_in_file","args":'
                                '{"path":"app.py","old":"MISSING","new":"VALUE = 2","expected_replacements":1}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text='{"action":"final","answer":"Saw repair feedback."}',
                        model=self.agent.model,
                    )

            events: list[dict] = []
            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Update app.py"}]),
                event_sink=events.append,
            )

            self.assertEqual(response.text, "Saw repair feedback.")
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 1\n")
            self.assertIn('"failure_type": "tool_failure"', seen_messages[1][-1]["content"])
            self.assertIn("edit_repair_loop", [event["type"] for event in events])

    def test_repeated_read_file_uses_cached_compact_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "big.txt").write_text("".join(f"line-{index:04d}\n" for index in range(2000)), encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                agent_max_steps=5,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0
            read_calls = 0
            token_counts: list[int] = []
            message_counts: list[int] = []
            original_read_file = AgentToolbox._read_file

            def counting_read_file(toolbox: AgentToolbox, args: dict) -> dict:
                nonlocal read_calls
                read_calls += 1
                return original_read_file(toolbox, args)

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    token_counts.append(estimate_input_tokens(request))
                    message_counts.append(len(request.messages))
                    if calls <= 4:
                        return ProviderResult(
                            text='{"action":"tool","tool":"read_file","args":{"path":"big.txt"}}',
                            model=self.agent.model,
                        )
                    return ProviderResult(text='{"action":"final","answer":"Done."}', model=self.agent.model)

            AgentToolbox._read_file = counting_read_file
            try:
                response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                    HubRequest(session_id="agent", messages=[{"role": "user", "content": "Read big.txt"}])
                )
            finally:
                AgentToolbox._read_file = original_read_file

            self.assertEqual(response.text, "Done.")
            self.assertEqual(read_calls, 1)
            self.assertLess(token_counts[-1] - token_counts[1], 5000)
            self.assertLessEqual(max(message_counts), message_counts[1] + 2)
            duplicates = [
                step for step in response.raw["agent_hub"]["steps"]
                if step["result"].get("duplicate_context_result")
            ]
            self.assertEqual(len(duplicates), 3)

    def test_repeated_repo_map_uses_compact_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("from helper import value\nprint(value)\n", encoding="utf-8")
            (root / "helper.py").write_text("value = 1\n", encoding="utf-8")
            (root / "test_app.py").write_text("from app import value\n", encoding="utf-8")
            for index in range(30):
                (root / f"module_{index}.py").write_text(f"VALUE_{index} = {index}\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                agent_max_steps=5,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0
            repo_map_calls = 0
            token_counts: list[int] = []
            seen_messages: list[list[dict]] = []
            original_repo_map = AgentToolbox._repo_map

            def counting_repo_map(toolbox: AgentToolbox, args: dict) -> dict:
                nonlocal repo_map_calls
                repo_map_calls += 1
                return original_repo_map(toolbox, args)

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    token_counts.append(estimate_input_tokens(request))
                    seen_messages.append(list(request.messages))
                    if calls <= 4:
                        return ProviderResult(
                            text='{"action":"tool","tool":"repo_map","args":{"target":"app.py"}}',
                            model=self.agent.model,
                        )
                    return ProviderResult(text='{"action":"final","answer":"Done."}', model=self.agent.model)

            AgentToolbox._repo_map = counting_repo_map
            try:
                response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                    HubRequest(session_id="agent", messages=[{"role": "user", "content": "Map app.py repeatedly"}])
                )
            finally:
                AgentToolbox._repo_map = original_repo_map

            self.assertEqual(response.text, "Done.")
            self.assertEqual(repo_map_calls, 1)
            self.assertLess(token_counts[-1] - token_counts[1], 3000)
            final_prompt = "\n".join(str(message.get("content", "")) for message in seen_messages[-1])
            self.assertIn("repo_map app.py", final_prompt)
            self.assertIn("duplicate_context_result", final_prompt)

    def test_repeated_policy_failures_do_not_duplicate_identical_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                agent_max_steps=4,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0
            seen_messages: list[list[dict]] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    seen_messages.append(list(request.messages))
                    if calls <= 3:
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"write_file","args":'
                                '{"path":"app.py","content":"VALUE = 2\\n"}}'
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(text='{"action":"final","answer":"Done."}', model=self.agent.model)

            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Update app.py"}])
            )

            self.assertEqual(response.text, "Done.")
            last_prompt = "\n".join(str(message.get("content", "")) for message in seen_messages[-1])
            self.assertLessEqual(last_prompt.count("write_file is reserved for new generated files"), 2)
            self.assertIn("duplicate_policy_feedback", last_prompt)

    def test_old_tool_results_compact_and_recent_results_remain_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(4):
                (root / f"file{index}.txt").write_text(f"unique-content-{index}\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                agent_max_steps=6,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0
            seen_messages: list[list[dict]] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    seen_messages.append(list(request.messages))
                    if calls <= 4:
                        return ProviderResult(
                            text=json.dumps(
                                {
                                    "action": "tool",
                                    "tool": "read_file",
                                    "args": {"path": f"file{calls - 1}.txt"},
                                }
                            ),
                            model=self.agent.model,
                        )
                    return ProviderResult(text='{"action":"final","answer":"Done."}', model=self.agent.model)

            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Read files"}])
            )

            self.assertEqual(response.text, "Done.")
            final_prompt = "\n".join(str(message.get("content", "")) for message in seen_messages[-1])
            self.assertIn("content_omitted", final_prompt)
            self.assertIn("content_hash", final_prompt)
            self.assertNotIn("unique-content-0", final_prompt)
            self.assertNotIn("unique-content-1", final_prompt)
            self.assertIn("unique-content-2", final_prompt)
            self.assertIn("unique-content-3", final_prompt)

    def test_context_usage_updated_event_is_emitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("hello\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ProviderResult(
                            text='{"action":"tool","tool":"read_file","args":{"path":"note.txt"}}',
                            model=self.agent.model,
                        )
                    return ProviderResult(text='{"action":"final","answer":"Done."}', model=self.agent.model)

            events: list[dict] = []
            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Read note"}]),
                event_sink=events.append,
            )

            self.assertEqual(response.text, "Done.")
            usage_events = [event for event in events if event["type"] == "context_usage_updated"]
            self.assertGreaterEqual(len(usage_events), 2)
            expected_fields = {
                "input_tokens",
                "budget_tokens",
                "percent_used",
                "tokens_added_since_last_step",
                "compaction_triggered",
                "compaction_level",
                "compacted_messages_count",
                "compacted_tool_results_count",
                "estimated_tokens_saved",
                "largest_context_sources",
                "warning_level",
            }
            self.assertTrue(expected_fields.issubset(usage_events[0]))
            self.assertIn("tokens_added_since_last_step", usage_events[1])

    def test_context_compaction_triggers_when_budget_is_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "big.txt").write_text("x" * 20_000, encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                        context_window=10_000,
                        max_tokens=1000,
                    )
                },
            )
            calls = 0
            seen_messages: list[list[dict]] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    seen_messages.append(list(request.messages))
                    if calls == 1:
                        return ProviderResult(
                            text='{"action":"tool","tool":"read_file","args":{"path":"big.txt"}}',
                            model=self.agent.model,
                        )
                    return ProviderResult(text='{"action":"final","answer":"Done."}', model=self.agent.model)

            events: list[dict] = []
            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Read big"}],
                    raw={"agent_context_budget_tokens": 1200},
                ),
                event_sink=events.append,
            )

            self.assertEqual(response.text, "Done.")
            usage_events = [event for event in events if event["type"] == "context_usage_updated"]
            self.assertTrue(any(event["compaction_triggered"] for event in usage_events))
            self.assertTrue(any(event["compacted_messages_count"] > 0 for event in usage_events))
            final_prompt = "\n".join(str(message.get("content", "")) for message in seen_messages[-1])
            self.assertIn("content_omitted", final_prompt)

    def test_session_history_does_not_inject_old_tool_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            router = AgentRouter(config)
            huge_tool_output = "Tool result for read_file:\n" + ("old file contents\n" * 2000)
            router.session_store.record_turn(
                HubRequest(
                    session_id="agent",
                    messages=[
                        {"role": "user", "content": "Old request"},
                        {"role": "user", "content": huge_tool_output},
                    ],
                ),
                HubResponse(
                    request_id="test",
                    session_id="agent",
                    agent="local",
                    provider="test",
                    model="test",
                    text="Old answer",
                ),
            )
            seen_messages: list[list[dict]] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    seen_messages.append(list(request.messages))
                    return ProviderResult(text='{"action":"final","answer":"Done."}', model=self.agent.model)

            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider, session_store=router.session_store)).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "New request"}],
                    use_session_history=True,
                )
            )

            self.assertEqual(response.text, "Done.")
            prompt = "\n".join(str(message.get("content", "")) for message in seen_messages[0])
            self.assertIn("Prior session", prompt)
            self.assertIn("Old answer", prompt)
            self.assertNotIn("Tool result for read_file", prompt)
            self.assertNotIn("old file contents", prompt)

    def test_provider_is_not_called_when_prompt_exceeds_hard_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    )
                },
            )
            calls = 0

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    return ProviderResult(text='{"action":"final","answer":"Should not run."}', model=self.agent.model)

            events: list[dict] = []
            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Do work"}],
                    raw={"agent_context_budget_tokens": 50},
                ),
                event_sink=events.append,
            )

            self.assertEqual(calls, 0)
            self.assertIn("exceeded the configured context budget", response.text)
            usage_events = [event for event in events if event["type"] == "context_usage_updated"]
            self.assertTrue(usage_events)
            self.assertTrue(usage_events[0]["hard_budget_exceeded"])
            self.assertEqual(usage_events[0]["compaction_level"], "hard_stop")

    def test_repair_loop_context_stays_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("VALUE = 1\n" + ("# context\n" * 7000), encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                context_change_bar_mode="off",
                agent_max_steps=6,
                validation_repair_attempts=3,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                        context_window=12_000,
                        max_tokens=1000,
                    )
                },
            )
            calls = 0
            token_counts: list[int] = []
            seen_messages: list[list[dict]] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    token_counts.append(estimate_input_tokens(request))
                    seen_messages.append(list(request.messages))
                    if calls == 1:
                        return ProviderResult(
                            text='{"action":"tool","tool":"read_file","args":{"path":"app.py"}}',
                            model=self.agent.model,
                        )
                    return ProviderResult(
                        text=(
                            '{"action":"tool","tool":"apply_patch","args":'
                            '{"summary":"Bad repair","changes":['
                            '{"path":"app.py","old":"MISSING","new":"VALUE = 2"}]}}'
                        ),
                        model=self.agent.model,
                    )

            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(
                    session_id="agent",
                    messages=[{"role": "user", "content": "Repair app.py"}],
                    raw={"agent_context_budget_tokens": 9000},
                )
            )

            self.assertIn("repair attempt", response.text)
            self.assertLessEqual(max(token_counts), 9000)
            last_prompt = "\n".join(str(message.get("content", "")) for message in seen_messages[-1])
            self.assertIn("content_omitted", last_prompt)

    def test_long_agent_runs_remain_under_configured_context_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "big.txt").write_text("".join(f"payload-{index:04d}\n" for index in range(7000)), encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                agent_max_steps=12,
                default_route=["local"],
                agents={
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                        context_window=12_000,
                        max_tokens=1000,
                    )
                },
            )
            calls = 0
            token_counts: list[int] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    nonlocal calls
                    calls += 1
                    token_counts.append(estimate_input_tokens(request))
                    if calls <= 10:
                        return ProviderResult(
                            text='{"action":"tool","tool":"read_file","args":{"path":"big.txt"}}',
                            model=self.agent.model,
                        )
                    return ProviderResult(text='{"action":"final","answer":"Done."}', model=self.agent.model)

            response = AgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(session_id="agent", messages=[{"role": "user", "content": "Read repeatedly"}])
            )

            self.assertEqual(response.text, "Done.")
            self.assertTrue(token_counts)
            self.assertLessEqual(max(token_counts) + 1000, 12_000)

    def test_workspace_checkpoint_restore_restores_and_removes_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "app.py"
            existing.write_text("VALUE = 1\n", encoding="utf-8")
            checkpoint = create_workspace_checkpoint(
                root,
                ["app.py", "new.py"],
                state_dir=root / "state",
                reason="test",
            )
            existing.write_text("VALUE = 2\n", encoding="utf-8")
            (root / "new.py").write_text("created\n", encoding="utf-8")

            restored = restore_workspace_checkpoint(checkpoint, root=root)

            self.assertTrue(restored["ok"])
            self.assertEqual(existing.read_text(encoding="utf-8"), "VALUE = 1\n")
            self.assertFalse((root / "new.py").exists())

    def test_search_files_skips_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "secret.txt").write_text("needle\n", encoding="utf-8")
            try:
                os.symlink(outside / "secret.txt", root / "link.txt")
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this platform")
            toolbox = AgentToolbox(
                HubConfig(workspace_dir=root),
                HubRequest(session_id="agent", messages=[]),
            )

            result = toolbox.run("search_files", {"query": "needle", "path": ".", "pattern": "*.txt"})

            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["matches"], [])


if __name__ == "__main__":
    unittest.main()
