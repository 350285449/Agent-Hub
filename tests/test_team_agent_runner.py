from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.router import AgentRouter
from agent_hub.team_agent_runner import TeamAgentRunner, score_plan, select_best_plan


class TeamAgentRunnerTests(unittest.TestCase):
    def test_group_agent_runs_planner_researcher_coder_reviewer_finalizer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["planner", "researcher", "coder", "reviewer", "finalizer"],
                group_roles={
                    "planner": "planner",
                    "researcher": "researcher",
                    "coder": "coder",
                    "reviewer": "reviewer",
                    "finalizer": "finalizer",
                },
                agents={
                    name: AgentConfig(
                        name=name,
                        provider="openai-compatible",
                        model=f"{name}-test",
                        base_url="http://127.0.0.1:9999",
                        supports_tools=True,
                    )
                    for name in ["planner", "researcher", "coder", "reviewer", "finalizer"]
                },
            )
            calls: list[str] = []
            test_case = self

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(self.agent.name)
                    if self.agent.name == "planner":
                        return ProviderResult(
                            text="Inspect README.md, make a minimal edit, then verify.",
                            model=self.agent.model,
                        )
                    if self.agent.name == "researcher":
                        if any("Tool result for repo_map" in m.get("content", "") for m in request.messages):
                            return ProviderResult(
                                text='{"action":"final","answer":"README.md is a top-level documentation file."}',
                                model=self.agent.model,
                            )
                        return ProviderResult(
                            text='{"action":"tool","tool":"repo_map","args":{"target":"README.md"}}',
                            model=self.agent.model,
                        )
                    if self.agent.name == "coder":
                        state = request.raw["agent_hub_runtime"]["reasoning_state"]
                        test_case.assertGreaterEqual(state["context_score"], 4)
                        test_case.assertTrue(state["repository_inspection_complete"])
                        if any("Tool result for write_file" in m.get("content", "") for m in request.messages):
                            return ProviderResult(
                                text='{"action":"final","answer":"Created TEAM.txt."}',
                                model=self.agent.model,
                            )
                        return ProviderResult(
                            text=(
                                '{"action":"tool","tool":"write_file","args":'
                                '{"path":"TEAM.txt","content":"team edit\\n"}}'
                            ),
                            model=self.agent.model,
                        )
                    if self.agent.name == "reviewer":
                        return ProviderResult(text="No blocking issues.", model=self.agent.model)
                    return ProviderResult(
                        text="Changed TEAM.txt and reviewed the patch.",
                        model=self.agent.model,
                    )

            router = AgentRouter(config, provider_factory=Provider)
            response = TeamAgentRunner(config, router).run(
                HubRequest(
                    session_id="team",
                    messages=[{"role": "user", "content": "Create TEAM.txt"}],
                    raw={"group_agent": {"plan_candidates": 1}},
                )
            )

            self.assertEqual((root / "TEAM.txt").read_text(encoding="utf-8"), "team edit\n")
            self.assertIn("Changed TEAM.txt", response.text)
            self.assertEqual(response.raw["agent_hub"]["mode"], "group-agent")
            self.assertEqual(
                [phase["role"] for phase in response.raw["agent_hub"]["phases"]],
                ["planner", "researcher", "coder", "reviewer"],
            )
            self.assertEqual(
                calls,
                ["planner", "researcher", "researcher", "coder", "coder", "reviewer", "finalizer"],
            )
            state = response.raw["agent_hub"]["reasoning_state"]
            self.assertIn("README.md", state["inspected_files"])
            self.assertGreaterEqual(state["context_score"], 4)
            self.assertTrue(state["repository_inspection_complete"])
            self.assertTrue(
                any("TEAM.txt" in edit.get("files", []) for edit in state["planned_edits"])
            )
            self.assertTrue(response.raw["agent_hub"]["execution_plan"]["nodes"])
            session = router.session_store.load("team")
            self.assertIn("reasoning_state", session)

    def test_plan_voting_prefers_scoped_verified_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agent_hub").mkdir()
            (root / "agent_hub" / "router.py").write_text("", encoding="utf-8")
            request = HubRequest(
                session_id="team",
                messages=[{"role": "user", "content": "Update agent_hub/router.py"}],
            )
            risky = "Rewrite everything in vscode-extension/backend and delete old files."
            scoped = "Inspect agent_hub/router.py, make a minimal change, then run tests."

            self.assertGreater(score_plan(scoped, request, root), score_plan(risky, request, root))
            self.assertEqual(select_best_plan([risky, scoped], request, root), scoped)

    def test_group_agent_runs_optional_validator_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                default_route=["planner", "researcher", "coder", "validator", "reviewer", "finalizer"],
                group_roles={
                    "planner": "planner",
                    "researcher": "researcher",
                    "coder": "coder",
                    "validator": "validator",
                    "reviewer": "reviewer",
                    "finalizer": "finalizer",
                },
                agents={
                    name: AgentConfig(
                        name=name,
                        provider="openai-compatible",
                        model=f"{name}-test",
                        base_url="http://127.0.0.1:9999",
                        supports_tools=True,
                    )
                    for name in ["planner", "researcher", "coder", "validator", "reviewer", "finalizer"]
                },
            )
            calls: list[str] = []

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(self.agent.name)
                    if self.agent.name == "planner":
                        return ProviderResult(text="Inspect, edit, validate.", model=self.agent.model)
                    if self.agent.name == "researcher":
                        return ProviderResult(text='{"action":"final","answer":"Context ready."}', model=self.agent.model)
                    if self.agent.name == "coder":
                        return ProviderResult(text='{"action":"final","answer":"Changed files."}', model=self.agent.model)
                    if self.agent.name == "validator":
                        return ProviderResult(text="Validation passed.", model=self.agent.model)
                    if self.agent.name == "reviewer":
                        return ProviderResult(text="No blocking issues.", model=self.agent.model)
                    return ProviderResult(text="Done.", model=self.agent.model)

            response = TeamAgentRunner(config, AgentRouter(config, provider_factory=Provider)).run(
                HubRequest(
                    session_id="team-validator",
                    messages=[{"role": "user", "content": "Do work"}],
                )
            )

            self.assertEqual(response.text, "Done.")
            self.assertIn("validator", calls)
            self.assertIn("confidence", response.raw["agent_hub"])
            self.assertIn("validator", [phase["role"] for phase in response.raw["agent_hub"]["phases"]])


if __name__ == "__main__":
    unittest.main()
