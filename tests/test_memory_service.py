from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.memory import MemoryService
from agent_hub.models import HubRequest, HubResponse


class MemoryServiceTests(unittest.TestCase):
    def test_memory_tiers_persist_and_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = MemoryService(Path(tmp), Path(tmp))
            service.put("request", "current-file", "agent_hub/hub.py")
            service.put("workspace", "routing-plan", "Prefer coding route for repository edits")
            service.put("long_term", "project-style", "Keep public APIs dependency-free")

            again = MemoryService(Path(tmp), Path(tmp))
            matches = again.search("dependency-free")

            self.assertEqual(matches[0].key, "project-style")
            self.assertEqual(again.get("workspace", "routing-plan").value, "Prefer coding route for repository edits")
            explanation = again.explain()
            self.assertEqual(explanation["object"], "agent_hub.memory_tiers")
            self.assertEqual(explanation["counts"]["workspace"], 1)
            self.assertEqual(explanation["counts"]["long_term"], 1)

    def test_record_turn_updates_session_store_and_session_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = MemoryService(Path(tmp))
            request = HubRequest(session_id="s1", messages=[{"role": "user", "content": "hello"}])
            response = HubResponse(
                request_id="r1",
                session_id="s1",
                agent="echo",
                provider="echo",
                model="echo",
                text="world",
            )

            service.record_turn(request, response)

            self.assertEqual(service.get("session", "s1:last_turn").value, "world")
            session = service.session_store.load("s1")
            self.assertEqual(session["messages"][-1]["content"], "world")


if __name__ == "__main__":
    unittest.main()
