from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

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
            self.assertIn("local-research", names)
            self.assertIn("codex", names)
            self.assertIn("chatgpt", names)
            self.assertIn("gemini", names)
            self.assertIn("claude", names)
            self.assertFalse(data["cloud_control_selection"]["api_key_models_enabled"])
            research = next(route for route in data["routes"] if route["name"] == "research")
            self.assertEqual(research["agents"][0], "local-research")

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

    def test_agent_command_reports_route_errors_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "default_route": [],
                        "routes": [{"name": "local-agent", "agents": ["missing"]}],
                        "agents": [],
                    }
                ),
                encoding="utf-8",
            )
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(["--config", str(path), "agent", "do work"])

            self.assertEqual(code, 1)
            self.assertIn("Agent-Hub route failed", buffer.getvalue())

    def test_enable_provider_opts_in_to_cloud_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(
                    [
                        "--config",
                        str(path),
                        "enable-provider",
                        "openai",
                        "--model",
                        "gpt-test",
                    ]
                )

            self.assertEqual(code, 0)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data["free_only"])
            self.assertTrue(data["cloud_control_selection"]["api_key_models_enabled"])
            codex = next(agent for agent in data["agents"] if agent["name"] == "codex")
            self.assertTrue(codex["enabled"])
            self.assertTrue(codex["free"])
            self.assertEqual(codex["model"], "gpt-test")
            self.assertEqual(data["cloud_control_selection"]["route_mode"], "api-key")
            cloud_route = next(route for route in data["routes"] if route["name"] == "cloud-agent")
            self.assertEqual(cloud_route["agents"][0], "codex")
            self.assertIn("ollama-kimi-cloud", cloud_route["agents"])
            self.assertNotIn("ollama-qwen-coder", cloud_route["agents"])

    def test_add_provider_supports_openai_compatible_provider_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(
                    [
                        "--config",
                        str(path),
                        "add-provider",
                        "groq",
                        "--model",
                        "llama-3.3-70b-versatile",
                        "--enabled",
                    ]
                )

            self.assertEqual(code, 0)
            data = json.loads(path.read_text(encoding="utf-8"))
            agent = next(agent for agent in data["agents"] if agent["provider_type"] == "groq")
            self.assertEqual(agent["provider"], "openai-compatible")
            self.assertEqual(agent["api_key_env"], "GROQ_API_KEY")
            self.assertEqual(agent["base_url"], "https://api.groq.com/openai/v1")
            cloud_route = next(route for route in data["routes"] if route["name"] == "cloud-agent")
            self.assertEqual(cloud_route["agents"][0], agent["name"])

    def test_add_free_presets_merges_editable_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(["--config", str(path), "add-free-presets"])

            self.assertEqual(code, 0)
            data = json.loads(path.read_text(encoding="utf-8"))
            names = {agent["name"] for agent in data["agents"]}
            self.assertIn("groq-qwen3-32b", names)
            self.assertIn("openrouter-deepseek-free", names)

    def test_chat_runs_one_turn_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "state_dir": str(Path(tmp) / "state"),
                        "default_route": ["echo"],
                        "routes": [{"name": "local-agent", "agents": ["echo"]}],
                        "agents": [
                            {
                                "name": "echo",
                                "provider": "echo",
                                "model": "local-echo",
                                "free": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            buffer = io.StringIO()

            with patch("builtins.input", side_effect=["hello", "/exit"]), redirect_stdout(buffer):
                code = main(["--config", str(path), "chat"])

            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertIn("Agent-Hub Codex Chat", output)
            self.assertIn("codex>", output)


if __name__ == "__main__":
    unittest.main()
