from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.models import HubRequest
from agent_hub.observability import recent_events
from agent_hub.workflows import WorkflowMemory, WorkflowStageResult
from agent_hub.workflows.events import WorkflowEventRecorder
from agent_hub.workflows.planning import WorkflowPlanner, WorkflowStage


class WorkflowModernizationPhaseSixTests(unittest.TestCase):
    def test_planner_owns_stage_policy_prompts_and_raw_metadata(self) -> None:
        config = HubConfig(
            group_roles={"planner": "plan-agent"},
            agents={"plan-agent": AgentConfig(name="plan-agent", provider="echo", model="echo")},
        )
        planner = WorkflowPlanner(config)
        request = HubRequest(
            session_id="wf",
            messages=[{"role": "user", "content": "edit app.py"}],
            raw={"agent_hub": {"patch_summary": True}},
        )
        memory = WorkflowMemory(workflow_id="wf_1", kind="code", task="edit app.py")

        stages = planner.stages("code")
        prompt = planner.stage_prompt("code", stages[0], request, memory)
        raw = planner.stage_raw(request, "wf_1", "code", stages[0])

        self.assertEqual([stage.name for stage in stages], ["plan", "work", "review"])
        self.assertIn("Plan the code workflow", prompt)
        self.assertEqual(raw["agent_hub"]["workflow_id"], "wf_1")
        self.assertEqual(raw["agent_hub"]["workflow_stage"], "plan")
        self.assertEqual(planner.role_agent("planner"), "plan-agent")
        self.assertTrue(planner.patch_summary_requested(request))

    def test_planner_owns_review_retry_and_files_touched_policy(self) -> None:
        planner = WorkflowPlanner(HubConfig())
        memory = WorkflowMemory(workflow_id="wf_1", kind="code", task="edit app.py")
        memory.add(
            WorkflowStageResult(
                stage="review",
                role="reviewer",
                agent="reviewer",
                provider="echo",
                model="echo",
                text="blocking issue in src/app.py and tests/test_app.py",
                started_at=1.0,
                finished_at=2.0,
            )
        )

        self.assertTrue(planner.review_blocks(memory))
        self.assertEqual(planner.files_touched(memory), ["src/app.py", "tests/test_app.py"])

    def test_workflow_event_recorder_preserves_sink_and_jsonl_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events: list[dict] = []
            recorder = WorkflowEventRecorder(Path(tmp) / "state")

            recorder.emit(events.append, "workflow_started", workflow_id="wf_1")
            recorder.record("workflow_finished", workflow_id="wf_1", final_status="completed")
            stored = recent_events(Path(tmp) / "state", "workflows")

            self.assertEqual(events, [{"type": "workflow_started", "workflow_id": "wf_1"}])
            self.assertEqual(stored[-1]["type"], "workflow_finished")
            self.assertEqual(stored[-1]["final_status"], "completed")


if __name__ == "__main__":
    unittest.main()
