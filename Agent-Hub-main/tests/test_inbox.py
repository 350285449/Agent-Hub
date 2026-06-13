from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.inbox import InboxProcessor, enqueue_task, inbox_task_preview
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.core.router import AgentRouter


class InboxTests(unittest.TestCase):
    def test_process_once_routes_json_file_to_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                inbox_dir=root / "inbox",
                outbox_dir=root / "outbox",
                archive_dir=root / "archive",
                debug_echo_enabled=True,
                default_route=["echo"],
                agents={
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="echo-test",
                    )
                },
            )
            config.ensure_dirs()

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    return ProviderResult(text="processed", model=self.agent.model)

            router = AgentRouter(config, provider_factory=Provider)
            task_path = config.inbox_dir / "task.json"
            task_path.write_text(
                json.dumps({"session_id": "inbox", "task": "do work"}),
                encoding="utf-8",
            )

            outputs = InboxProcessor(config, router=router).process_once()

            self.assertEqual(len(outputs), 1)
            data = json.loads(outputs[0].read_text(encoding="utf-8"))
            self.assertEqual(data["message"]["content"], "processed")
            self.assertFalse(task_path.exists())
            self.assertEqual(len(list(config.archive_dir.glob("*.json"))), 1)

    def test_enqueue_task_and_preview_validate_pending_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                state_dir=root / "state",
                inbox_dir=root / "inbox",
                outbox_dir=root / "outbox",
                archive_dir=root / "archive",
            )

            path = enqueue_task(
                config,
                {"task_id": "fix/readme", "task": "Update README", "api_shape": "native"},
            )
            preview = inbox_task_preview(path)
            (config.inbox_dir / "broken.json").write_text("{", encoding="utf-8")
            broken = inbox_task_preview(config.inbox_dir / "broken.json")

            self.assertEqual(path.name, "fix-readme.json")
            self.assertTrue(preview["valid"])
            self.assertEqual(preview["api_shape"], "native")
            self.assertIn("Update README", preview["preview"])
            self.assertFalse(broken["valid"])
            self.assertIn("Invalid JSON", broken["error"])

    def test_enqueue_task_rejects_empty_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                inbox_dir=Path(tmp) / "inbox",
                outbox_dir=Path(tmp) / "outbox",
                archive_dir=Path(tmp) / "archive",
            )

            with self.assertRaises(ValueError):
                enqueue_task(config, {"api_shape": "native"})


if __name__ == "__main__":
    unittest.main()
