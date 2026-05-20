from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.agent_runner import AgentRunner
from agent_hub.config import AgentConfig, HubConfig
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.router import AgentRouter


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


if __name__ == "__main__":
    unittest.main()
