from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from agent_hub.config import HubConfig
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

    def test_semantic_compression_can_store_compacted_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = MemoryService(Path(tmp), Path(tmp))
            text = "\n".join(
                [
                    "# Architecture Notes",
                    "This section explains a normal detail.",
                    "TODO: preserve plugin memory context boundaries.",
                    "Traceback: important failure signal should survive.",
                    "Another ordinary sentence " * 20,
                ]
            )

            result = service.compress(text, max_chars=160)
            record = service.put("workspace", "compressed-plan", text, compress=True, max_chars=160)

        self.assertLessEqual(result.compressed_chars, 160)
        self.assertIn("plugin memory", result.compressed)
        self.assertLess(len(record.value), len(text))
        self.assertEqual(record.metadata["compression"]["object"], "agent_hub.memory_compression")

    def test_trusted_memory_context_plugin_contributes_searchable_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "memory-demo"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "memory.demo",
                        "name": "Memory Demo",
                        "type": "memory_context",
                        "enabled_by_default": True,
                        "metadata": {
                            "contexts": [
                                {
                                    "tier": "workspace",
                                    "key": "plugin-style",
                                    "value": "Prefer dependency-free public API clients.",
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = HubConfig(
                state_dir=root / "state",
                workspace_dir=root,
                plugin_dirs=[root / "plugins"],
                trusted_plugins=["memory.demo"],
            )
            service = MemoryService(config.state_dir, config.workspace_dir, config=config)

            matches = service.search("dependency-free", tiers=["workspace"])
            explanation = service.explain()

        self.assertEqual(matches[0].key, "plugin-style")
        self.assertTrue(matches[0].metadata["plugin_memory_context"])
        self.assertEqual(explanation["plugin_memory_contexts"], 1)


if __name__ == "__main__":
    unittest.main()
