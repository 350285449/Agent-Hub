from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_hub.cli import main
from agent_hub.models import HubResponse


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

    def test_health_command_prints_provider_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "state_dir": str(Path(tmp) / "state"),
                        "auto_detect_local_models": False,
                        "default_route": ["echo"],
                        "routes": [{"name": "cloud-agent", "agents": ["echo"]}],
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

            with redirect_stdout(buffer):
                code = main(["--config", str(path), "health"])

            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertIn("Agent-Hub health", output)
            self.assertIn("reliability", output)

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

    def test_recommend_command_prints_model_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "state_dir": str(Path(tmp) / "state"),
                        "auto_detect_local_models": False,
                        "default_route": ["general", "coder"],
                        "routes": [{"name": "coding", "agents": ["general", "coder"]}],
                        "agents": [
                            {
                                "name": "general",
                                "provider": "openai-compatible",
                                "model": "general-test",
                                "base_url": "http://127.0.0.1:9999",
                                "coding_score": 0.2,
                                "reasoning_score": 0.7,
                            },
                            {
                                "name": "coder",
                                "provider": "openai-compatible",
                                "model": "coder-test",
                                "base_url": "http://127.0.0.1:9999",
                                "coding_score": 0.95,
                                "supports_tools": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(
                    [
                        "--config",
                        str(path),
                        "recommend",
                        "--route",
                        "coding",
                        "--needs-tools",
                        "fix tests",
                    ]
                )

            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertIn("coder", output)
            self.assertIn("score", output)

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

    def test_agent_runtime_flags_populate_agent_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            _write_minimal_config(path)
            captured: list[dict] = []

            def fake_run(self, request, event_sink=None, shell_permission_callback=None):
                captured.append(request.raw)
                return HubResponse(
                    request_id="test",
                    session_id=request.session_id,
                    agent="local",
                    provider="echo",
                    model="echo",
                    text="ok",
                )

            with patch("agent_hub.cli.AgentRunner.run", fake_run), redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--config",
                        str(path),
                        "agent",
                        "--prefer-multi-file-patches",
                        "--context-change-bar",
                        "strict",
                        "--context-change-threshold",
                        "6",
                        "update",
                        "tests",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue(captured[0]["prefer_multi_file_patches"])
            self.assertTrue(captured[0]["context_change_bar_enabled"])
            self.assertEqual(captured[0]["context_change_bar_mode"], "strict")
            self.assertEqual(captured[0]["context_change_bar_threshold"], 6)

    def test_agent_runtime_flags_populate_group_agent_and_chat_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            _write_minimal_config(path)
            group_payloads: list[dict] = []
            chat_payloads: list[dict] = []

            def fake_group_run(self, request, event_sink=None, shell_permission_callback=None):
                group_payloads.append(request.raw)
                return HubResponse(
                    request_id="group",
                    session_id=request.session_id,
                    agent="local",
                    provider="echo",
                    model="echo",
                    text="group ok",
                )

            def fake_agent_run(self, request, event_sink=None, shell_permission_callback=None):
                chat_payloads.append(request.raw)
                return HubResponse(
                    request_id="chat",
                    session_id=request.session_id,
                    agent="local",
                    provider="echo",
                    model="echo",
                    text="chat ok",
                )

            with patch("agent_hub.cli.TeamAgentRunner.run", fake_group_run), redirect_stdout(io.StringIO()):
                group_code = main(
                    [
                        "--config",
                        str(path),
                        "group-agent",
                        "--no-prefer-multi-file-patches",
                        "--context-change-bar",
                        "off",
                        "--context-change-threshold",
                        "2",
                        "update",
                    ]
                )

            with (
                patch("builtins.input", side_effect=["hello", "/exit"]),
                patch("agent_hub.cli.AgentRunner.run", fake_agent_run),
                redirect_stdout(io.StringIO()),
            ):
                chat_code = main(
                    [
                        "--config",
                        str(path),
                        "chat",
                        "--prefer-multi-file-patches",
                        "--context-change-bar",
                        "light",
                        "--context-change-threshold",
                        "4",
                    ]
                )

            self.assertEqual(group_code, 0)
            self.assertFalse(group_payloads[0]["prefer_multi_file_patches"])
            self.assertFalse(group_payloads[0]["context_change_bar_enabled"])
            self.assertEqual(group_payloads[0]["context_change_bar_mode"], "off")
            self.assertEqual(group_payloads[0]["context_change_bar_threshold"], 2)
            self.assertEqual(chat_code, 0)
            self.assertTrue(chat_payloads[0]["prefer_multi_file_patches"])
            self.assertTrue(chat_payloads[0]["context_change_bar_enabled"])
            self.assertEqual(chat_payloads[0]["context_change_bar_mode"], "light")
            self.assertEqual(chat_payloads[0]["context_change_bar_threshold"], 4)


def _write_minimal_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "state_dir": str(path.parent / "state"),
                "auto_detect_local_models": False,
                "default_route": ["echo"],
                "routes": [{"name": "cloud-agent", "agents": ["echo"]}],
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


if __name__ == "__main__":
    unittest.main()
