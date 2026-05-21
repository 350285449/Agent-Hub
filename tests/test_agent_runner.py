from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.agent_tools import AgentToolbox
from agent_hub.agent_runner import AgentRunner
from agent_hub.config import AgentConfig, HubConfig
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.router import AgentRouter
from agent_hub.providers import ProviderError


class AgentRunnerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
