from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from agent_hub.cli import main


class CliTests(unittest.TestCase):
    def test_init_writes_friendly_config_with_optional_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(["--config", str(path), "init", "--with-cloud-examples"])

            self.assertEqual(code, 0)
            data = json.loads(path.read_text(encoding="utf-8"))
            names = {agent["name"] for agent in data["agents"]}
            self.assertIn("custom-local", names)
            self.assertIn("chatgpt", names)
            self.assertIn("gemini", names)
            self.assertIn("claude", names)

    def test_agents_command_prints_configured_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            with redirect_stdout(io.StringIO()):
                main(["--config", str(path), "init"])
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(["--config", str(path), "agents"])

            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertIn("custom-local", output)
            self.assertIn("allowed", output)


if __name__ == "__main__":
    unittest.main()
