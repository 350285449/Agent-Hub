from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_hub.cli import main
from agent_hub.models import HubResponse
from agent_hub.observability import record_event


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
            self.assertIn("Readiness:", output)
            self.assertIn("Next step:", output)
            self.assertIn("reliability", output)

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["--config", str(path), "health", "--json"])

            self.assertEqual(code, 0)
            data = json.loads(buffer.getvalue())
            self.assertEqual(data["readiness"]["object"], "agent_hub.readiness")
            self.assertIn("feature_status", data["readiness"])

    def test_production_check_reports_unready_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            _write_minimal_config(path)
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(["--config", str(path), "production-check", "--json"])

            self.assertEqual(code, 1)
            data = json.loads(buffer.getvalue())
            self.assertEqual(data["object"], "agent_hub.production_check")
            self.assertFalse(data["ok"])
            self.assertTrue(any(check["id"] == "route_ready_provider" for check in data["failed"]))

    def test_feature_scorecard_reports_all_local_areas_10(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "state_dir": str(Path(tmp) / "state"),
                        "inbox_dir": str(Path(tmp) / "inbox"),
                        "outbox_dir": str(Path(tmp) / "outbox"),
                        "archive_dir": str(Path(tmp) / "archive"),
                        "auto_detect_local_models": False,
                        "debug_echo_enabled": True,
                        "default_route": ["echo"],
                        "routes": [{"name": "cloud-agent", "agents": ["echo"]}],
                        "agents": [
                            {
                                "name": "echo",
                                "provider": "echo",
                                "provider_type": "echo",
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
                code = main(["--config", str(path), "feature-scorecard", "--json"])

            self.assertEqual(code, 0)
            data = json.loads(buffer.getvalue())
            self.assertEqual(data["object"], "agent_hub.feature_scorecard")
            self.assertEqual(data["rating"], 10.0)
            self.assertTrue(data["all_local_areas_10"], data["blockers"])

    def test_doctor_json_includes_install_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            _write_minimal_config(path)
            buffer = io.StringIO()

            release_check = {
                "id": "release_validation",
                "category": "release",
                "ok": True,
                "detail": "passed",
                "failures": [],
            }
            with (
                patch("agent_hub.cli._backend_reachability") as backend,
                patch("agent_hub.commands_doctor._validate_backend_snapshot", return_value=[]),
                patch("agent_hub.commands_doctor._release_validation_check", return_value=release_check),
                redirect_stdout(buffer),
            ):
                backend.return_value = {"ok": True, "url": "http://127.0.0.1:8787/health", "detail": "HTTP 200"}
                code = main(["--config", str(path), "doctor", "--json"])

            self.assertEqual(code, 0)
            data = json.loads(buffer.getvalue())
            self.assertIn("install_checks", data)
            self.assertTrue(any(row["id"] == "python_version" for row in data["install_checks"]))
            self.assertTrue(any(row["id"] == "runtime_dependency_audit" for row in data["dependency_checks"]))
            self.assertTrue(any(row["id"] == "release_dependency:packaging" for row in data["dependency_checks"]))
            self.assertTrue(any(row["id"] == "provider_config" for row in data["install_checks"]))
            self.assertTrue(any(row["id"] == "server_health" for row in data["install_checks"]))
            self.assertTrue(any(row["id"] == "vscode_extension_prepare_backend" for row in data["install_checks"]))
            self.assertTrue(any(row["id"] == "vscode_backend_gitignored" for row in data["install_checks"]))
            self.assertTrue(data["backend_reachable"]["ok"])
            self.assertIn("runtime_usability", data)
            self.assertIn("local_models", data)
            self.assertTrue(any("Cline:" in fix for fix in data["exact_fixes"]))

    def test_doctor_fix_safe_repairs_route_refs_and_shell_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "state_dir": str(Path(tmp) / "state"),
                        "auto_detect_local_models": False,
                        "allow_shell_tools": True,
                        "default_route": ["ghost", "echo"],
                        "routes": [{"name": "cloud-agent", "agents": ["missing"]}],
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
            release_check = {
                "id": "release_validation",
                "category": "release",
                "ok": True,
                "detail": "passed",
                "failures": [],
            }

            with (
                patch("agent_hub.cli._backend_reachability") as backend,
                patch("agent_hub.commands_doctor._validate_backend_snapshot", return_value=[]),
                patch("agent_hub.commands_doctor._release_validation_check", return_value=release_check),
                redirect_stdout(buffer),
            ):
                backend.return_value = {"ok": True, "url": "http://127.0.0.1:8787/health", "detail": "HTTP 200"}
                code = main(["--config", str(path), "doctor", "--fix-safe", "--json"])

            self.assertEqual(code, 0)
            report = json.loads(buffer.getvalue())
            fixed = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(report["fix_safe"]["changed"])
            self.assertTrue(report["fix_safe"]["backup_path"])
            self.assertTrue(Path(report["fix_safe"]["backup_path"]).exists())
            self.assertEqual(fixed["default_route"], ["echo"])
            self.assertEqual(fixed["routes"][0]["agents"], ["echo"])
            self.assertTrue(fixed["free_only"])
            self.assertEqual(fixed["approval_mode"], "safe")
            self.assertFalse(fixed["allow_shell_tools"])

    def test_checkup_fix_safe_verify_json_reports_runtime_usability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "state_dir": str(Path(tmp) / "state"),
                        "auto_detect_local_models": False,
                        "free_only": False,
                        "approval_mode": "ask",
                        "allow_shell_tools": True,
                        "default_route": ["coder"],
                        "routes": [
                            {"name": "research", "agents": ["local-research"]},
                            {"name": "coding", "agents": ["coder"]},
                            {"name": "cloud-agent", "agents": ["coder"]},
                        ],
                        "agents": [
                            {
                                "name": "coder",
                                "provider": "openai-compatible",
                                "model": "coder-test",
                                "base_url": "http://127.0.0.1:9999/v1",
                                "free": True,
                            },
                            {
                                "name": "local-research",
                                "provider": "local-research",
                                "provider_type": "local-research",
                                "model": "local-research",
                                "free": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            buffer = io.StringIO()
            release_check = {
                "id": "release_validation",
                "category": "release",
                "ok": True,
                "detail": "passed",
                "failures": [],
            }
            local_models = [
                {
                    "name": "coder",
                    "online": True,
                    "configured_model_available": True,
                    "configured_model": "coder-test",
                }
            ]
            smoke = {
                "recorded_at": 1.0,
                "research": {"ok": True, "agent": "local-research"},
                "coding": {"ok": True, "agent": "coder"},
            }

            with (
                patch("agent_hub.cli._backend_reachability") as backend,
                patch("agent_hub.commands_doctor._backend_reachability") as doctor_backend,
                patch("agent_hub.commands_doctor._local_models_report", return_value=local_models),
                patch("agent_hub.commands_doctor._validate_backend_snapshot", return_value=[]),
                patch("agent_hub.commands_doctor._release_validation_check", return_value=release_check),
                patch("agent_hub.commands_doctor._run_checkup_route_smoke", return_value=smoke),
                redirect_stdout(buffer),
            ):
                backend.return_value = {"ok": True, "url": "http://127.0.0.1:8787/health", "detail": "HTTP 200"}
                doctor_backend.return_value = backend.return_value
                code = main(["--config", str(path), "checkup", "--fix-safe", "--verify", "--json"])

            self.assertEqual(code, 0)
            report = json.loads(buffer.getvalue())
            fixed = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["object"], "agent_hub.checkup")
            self.assertTrue(report["fix_safe"]["changed"])
            self.assertTrue(Path(report["fix_safe"]["backup_path"]).exists())
            self.assertTrue(report["verify"])
            self.assertEqual(report["route_smoke"]["coding"]["agent"], "coder")
            self.assertEqual(report["runtime_usability"]["state"], "ready")
            self.assertTrue(report["ok"])
            self.assertTrue(fixed["free_only"])
            self.assertEqual(fixed["approval_mode"], "safe")
            self.assertFalse(fixed["allow_shell_tools"])

    def test_doctor_does_not_warn_for_cline_cloud_auto_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "state_dir": str(Path(tmp) / "state"),
                        "auto_detect_local_models": False,
                        "approval_mode": "auto",
                        "cline_compatibility_mode": True,
                        "free_only": False,
                        "default_route": ["ollama-qwen-cloud"],
                        "routes": [
                            {
                                "name": "cloud-agent",
                                "agents": ["ollama-qwen-cloud"],
                            }
                        ],
                        "agents": [
                            {
                                "name": "ollama-qwen-cloud",
                                "provider": "openai-compatible",
                                "provider_type": "ollama-cloud",
                                "model": "qwen3.5:cloud",
                                "base_url": "http://127.0.0.1:11434",
                                "free": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            buffer = io.StringIO()
            release_check = {
                "id": "release_validation",
                "category": "release",
                "ok": True,
                "detail": "passed",
                "failures": [],
            }

            with (
                patch("agent_hub.cli._backend_reachability") as backend,
                patch("agent_hub.commands_doctor._validate_backend_snapshot", return_value=[]),
                patch("agent_hub.commands_doctor._release_validation_check", return_value=release_check),
                redirect_stdout(buffer),
            ):
                backend.return_value = {"ok": True, "url": "http://127.0.0.1:8787/health", "detail": "HTTP 200"}
                code = main(["--config", str(path), "doctor", "--json"])

            self.assertEqual(code, 0)
            data = json.loads(buffer.getvalue())
            self.assertNotIn("approval_mode_review_recommended", data["likely_problems"])
            self.assertFalse(any("Use approval_mode=ask or safe" in fix for fix in data["exact_fixes"]))

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

    def test_free_models_command_enables_keyed_free_presets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            buffer = io.StringIO()

            with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}, clear=True):
                with redirect_stdout(buffer):
                    code = main(["--config", str(path), "free-models"])

            self.assertEqual(code, 0)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data["free_only"])
            self.assertTrue(data["disable_non_free_models"])
            groq = next(agent for agent in data["agents"] if agent["name"] == "groq-qwen3-32b")
            self.assertTrue(groq["enabled"])
            self.assertTrue(groq["free"])
            self.assertEqual(groq["api_key_env"], "GROQ_API_KEY")
            openrouter = next(
                agent for agent in data["agents"] if agent["name"] == "openrouter-deepseek-free"
            )
            self.assertFalse(openrouter["enabled"])
            cloud_route = next(route for route in data["routes"] if route["name"] == "cloud-agent")
            self.assertIn("groq-qwen3-32b", cloud_route["agents"])

    def test_local_only_routing_preset_keeps_private_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "default_route": ["remote", "local"],
                        "routes": [
                            {"name": "cloud-agent", "agents": ["remote", "local"]},
                            {"name": "local-agent", "agents": ["local"]},
                        ],
                        "agents": [
                            {
                                "name": "remote",
                                "provider": "openai-compatible",
                                "provider_type": "groq",
                                "model": "remote-test",
                                "base_url": "https://api.groq.com/openai/v1",
                                "enabled": True,
                                "free": False,
                            },
                            {
                                "name": "local",
                                "provider": "openai-compatible",
                                "provider_type": "lm-studio",
                                "model": "local-test",
                                "base_url": "http://127.0.0.1:1234",
                                "enabled": True,
                                "free": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                code = main(["--config", str(path), "presets", "apply", "Local Only Mode"])

            self.assertEqual(code, 0)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["default_route"], ["local"])
            self.assertTrue(data["free_only"])
            self.assertFalse(data["auto_enable_available_providers"])

    def test_free_only_routing_preset_disables_codex_cli_and_paid_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "default_route": ["codex-cli", "paid", "free"],
                        "routes": [
                            {"name": "cloud-agent", "agents": ["codex-cli", "paid", "free"]},
                            {"name": "codex-cli", "agents": ["codex-cli", "free"]},
                        ],
                        "agents": [
                            {
                                "name": "codex-cli",
                                "provider": "codex-cli",
                                "provider_type": "codex-cli",
                                "model": "gpt-5.5",
                                "enabled": True,
                                "free": True,
                            },
                            {
                                "name": "paid",
                                "provider": "openai",
                                "model": "gpt-paid",
                                "enabled": True,
                                "free": True,
                            },
                            {
                                "name": "free",
                                "provider": "openai-compatible",
                                "provider_type": "groq",
                                "model": "qwen-free",
                                "base_url": "https://api.groq.com/openai/v1",
                                "enabled": True,
                                "free": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                code = main(["--config", str(path), "presets", "apply", "Free Only Mode"])

            self.assertEqual(code, 0)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data["free_only"])
            self.assertTrue(data["disable_non_free_models"])
            self.assertEqual(data["default_route"], ["free"])
            agents = {agent["name"]: agent for agent in data["agents"]}
            self.assertFalse(agents["codex-cli"]["enabled"])
            self.assertFalse(agents["codex-cli"]["free"])
            self.assertFalse(agents["paid"]["enabled"])
            self.assertFalse(agents["paid"]["free"])
            codex_route = next(route for route in data["routes"] if route["name"] == "codex-cli")
            self.assertEqual(codex_route["agents"], ["free"])

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

    def test_estimate_command_reports_cost_latency_and_explanation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "state_dir": str(Path(tmp) / "state"),
                        "auto_detect_local_models": False,
                        "default_route": ["coder"],
                        "routes": [{"name": "coding", "agents": ["coder"]}],
                        "agents": [
                            {
                                "name": "coder",
                                "provider": "openai-compatible",
                                "model": "coder-test",
                                "base_url": "http://127.0.0.1:9999",
                                "free": True,
                                "cost_per_million_input": 1.0,
                                "cost_per_million_output": 2.0,
                                "supports_tools": True,
                            }
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
                        "estimate",
                        "--route",
                        "coding",
                        "--output-tokens",
                        "1000",
                        "--json",
                        "fix tests",
                    ]
                )

            self.assertEqual(code, 0)
            data = json.loads(buffer.getvalue())
            self.assertEqual(data["object"], "agent_hub.routing_estimate")
            row = data["recommendations"][0]
            self.assertEqual(row["agent"], "coder")
            self.assertIn("estimated_cost_usd", row)
            self.assertIn("routing_explanation", row)

    def test_route_diagnose_reports_selection_skips_latency_and_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "state_dir": str(Path(tmp) / "state"),
                        "auto_detect_local_models": False,
                        "free_only": True,
                        "default_route": ["paid", "free"],
                        "routes": [{"name": "coding", "agents": ["paid", "free"]}],
                        "agents": [
                            {
                                "name": "paid",
                                "provider": "openai-compatible",
                                "model": "paid-test",
                                "base_url": "https://example.invalid/v1",
                                "free": False,
                                "supports_tools": True,
                            },
                            {
                                "name": "free",
                                "provider": "openai-compatible",
                                "model": "free-test",
                                "base_url": "http://127.0.0.1:9999",
                                "free": True,
                                "supports_tools": True,
                                "cost_per_million_input": 1.0,
                                "cost_per_million_output": 2.0,
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
                        "route-diagnose",
                        "--route",
                        "coding",
                        "--needs-tools",
                        "--output-tokens",
                        "1000",
                        "--json",
                        "fix tests",
                    ]
                )

            self.assertEqual(code, 0)
            data = json.loads(buffer.getvalue())
            self.assertEqual(data["object"], "agent_hub.route_diagnosis")
            self.assertEqual(data["selected_provider"], "openai-compatible")
            self.assertEqual(data["selected_model"], "free-test")
            self.assertIn("latency_ms", data)
            self.assertGreater(data["estimated_cost_usd"], 0)
            self.assertEqual(data["fallback_reason"], "skipped by free_only")
            self.assertEqual(data["skipped_providers"][0]["agent"], "paid")
            self.assertEqual(data["skipped_providers"][0]["reason"], "skipped by free_only")

    def test_route_diagnose_does_not_select_failed_local_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "state_dir": str(Path(tmp) / "state"),
                        "auto_enable_available_providers": False,
                        "auto_detect_local_models": True,
                        "local_model_probe_timeout_seconds": 0.05,
                        "free_only": True,
                        "default_route": ["local"],
                        "routes": [{"name": "coding", "agents": ["local"]}],
                        "agents": [
                            {
                                "name": "local",
                                "provider": "openai-compatible",
                                "model": "local-test",
                                "base_url": "http://127.0.0.1:1/v1",
                                "free": True,
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
                        "route-diagnose",
                        "--route",
                        "coding",
                        "--json",
                        "fix tests",
                    ]
                )

            self.assertEqual(code, 0)
            data = json.loads(buffer.getvalue())
            self.assertIsNone(data["selected_provider"])
            self.assertIsNone(data["selected_model"])
            self.assertEqual(data["skipped_providers"][0]["agent"], "local")
            self.assertIn("local endpoint probe failed", data["skipped_providers"][0]["reason"])

    def test_local_models_report_reuses_duplicate_base_url_probe(self) -> None:
        from agent_hub.commands_provider import _local_models_report
        from agent_hub.config import AgentConfig, HubConfig

        config = HubConfig(
            agents={
                "local-a": AgentConfig(
                    name="local-a",
                    provider="openai-compatible",
                    model="model-a",
                    base_url="http://127.0.0.1:9999/v1",
                    free=True,
                ),
                "local-b": AgentConfig(
                    name="local-b",
                    provider="openai-compatible",
                    model="model-b",
                    base_url="http://127.0.0.1:9999/v1",
                    free=True,
                ),
            },
        )
        calls: list[str] = []

        def fake_models(base_url: str, **_kwargs: object) -> list[str]:
            calls.append(base_url)
            return ["model-a", "model-b"]

        with patch("agent_hub.commands_provider.fetch_openai_models", side_effect=fake_models):
            rows = _local_models_report(config)

        self.assertEqual(calls, ["http://127.0.0.1:9999/v1"])
        self.assertEqual([row["configured_model_available"] for row in rows], [True, True])

    def test_benchmark_dataset_export_and_verify_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            _write_minimal_config(path)
            export = Path(tmp) / "results.json"
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(
                    [
                        "--config",
                        str(path),
                        "benchmark",
                        "--dataset",
                        "proof-50",
                        "--export",
                        str(export),
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue(export.exists())
            report = json.loads(export.read_text(encoding="utf-8"))
            self.assertEqual(report["object"], "agent_hub.benchmark_proof")
            self.assertEqual(report["dataset"]["name"], "proof-50")
            self.assertIn("dataset_fingerprint", report)

            verify_buffer = io.StringIO()
            with redirect_stdout(verify_buffer):
                verify_code = main(
                    [
                        "--config",
                        str(path),
                        "benchmark",
                        "verify",
                        str(export),
                        "--dataset",
                        "proof-50",
                        "--json",
                    ]
                )

            self.assertEqual(verify_code, 0)
            verification = json.loads(verify_buffer.getvalue())
            self.assertTrue(verification["ok"])

    def test_benchmark_compare_cli_outputs_verified_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            _write_minimal_config(path)
            export = Path(tmp) / "compare.json"
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(
                    [
                        "--config",
                        str(path),
                        "benchmark",
                        "compare",
                        "--dataset",
                        "proof-50",
                        "--limit",
                        "2",
                        "--export",
                        str(export),
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue(export.exists())
            comparison = json.loads(buffer.getvalue())
            self.assertEqual(comparison["object"], "agent_hub.benchmark_comparison")
            self.assertTrue(comparison["verified"])
            self.assertEqual(comparison["verified_tasks"], 2)
            self.assertIn("quality_pct", comparison["summary"])
            self.assertEqual(json.loads(export.read_text(encoding="utf-8"))["object"], "agent_hub.benchmark_comparison")

            text_buffer = io.StringIO()
            with redirect_stdout(text_buffer):
                text_code = main(
                    [
                        "--config",
                        str(path),
                        "benchmark",
                        "compare",
                        comparison["report_path"],
                        "--dataset",
                        "proof-50",
                    ]
                )

            self.assertEqual(text_code, 0)
            output = text_buffer.getvalue()
            self.assertIn("Agent-Hub vs", output)
            self.assertIn("Verified Tasks: 2", output)
            self.assertIn("Quality:", output)

    def test_generate_and_share_proof_cli_without_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            _write_minimal_config(path)
            config_state = Path(tmp) / "state"
            config_state.mkdir(parents=True, exist_ok=True)
            record_event(
                config_state,
                "routing",
                {"type": "routing_decision", "request_id": "r1", "provider": "echo", "model": "local-echo"},
            )
            report_dir = config_state / "benchmark_reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "benchmark-report.json").write_text(
                json.dumps(
                    {
                        "object": "agent_hub.benchmark_proof",
                        "task_count": 50,
                        "dataset": {"name": "proof-50", "fingerprint": "abc"},
                        "comparison": {
                            "cost_reduction": 34.0,
                            "latency_reduction": 18.0,
                            "success_delta": 2.0,
                        },
                        "results": [],
                    }
                ),
                encoding="utf-8",
            )

            proof_buffer = io.StringIO()
            with redirect_stdout(proof_buffer):
                code = main(["--config", str(path), "generate-proof"])

            self.assertEqual(code, 0)
            proof = json.loads(proof_buffer.getvalue())
            self.assertEqual(proof["routes"], 1)
            self.assertEqual(proof["estimated_savings"], 34.0)
            self.assertEqual(proof["providers_used"], 1)

            share_buffer = io.StringIO()
            with patch("agent_hub.anonymous_proof.webbrowser.open", return_value=True), redirect_stdout(share_buffer):
                share_code = main(["--config", str(path), "share-proof", "--no-open", "--target", "x"])

            self.assertEqual(share_code, 0)
            share_output = share_buffer.getvalue()
            self.assertIn("Agent-Hub Benchmark", share_output)
            self.assertIn("twitter.com/intent/tweet", share_output)

    def test_explain_route_accepts_recorded_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            _write_minimal_config(path)
            state = Path(tmp) / "state"
            state.mkdir(parents=True, exist_ok=True)
            record_event(
                state,
                "routing",
                {
                    "type": "routing_decision",
                    "request_id": "abc123",
                    "agent": "echo",
                    "provider": "echo",
                    "model": "local-echo",
                    "routing_decision": {
                        "selected_agent": "echo",
                        "selected_provider": "echo",
                        "selected_model": "local-echo",
                        "reason": "lowest estimated cost",
                        "candidate_scores": [
                            {
                                "agent": "echo",
                                "provider": "echo",
                                "model": "local-echo",
                                "final_routing_score": 90,
                                "estimated_cost_usd": 0.0,
                            },
                            {
                                "agent": "paid",
                                "provider": "openai",
                                "model": "gpt-test",
                                "final_routing_score": 88,
                                "estimated_cost_usd": 0.01,
                            },
                        ],
                    },
                },
            )
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(["--config", str(path), "explain-route", "abc123"])

            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertIn("Selected:", output)
            self.assertIn("Reasons:", output)
            self.assertIn("Rejected:", output)

    def test_demo_cli_runs_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            _write_minimal_config(path)
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(["--config", str(path), "demo"])

            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertIn("Agent-Hub Demo", output)
            self.assertIn("Savings Report", output)
            self.assertIn("agent-hub benchmark --dataset coding-100 --export results.json", output)

    def test_debug_bundle_exports_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            _write_minimal_config(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["agents"][0]["api_key"] = "sk-test-secret-value-1234567890"
            data["agents"][0]["api_key_env"] = "ECHO_API_KEY"
            path.write_text(json.dumps(data), encoding="utf-8")
            output = Path(tmp) / "debug.zip"
            buffer = io.StringIO()

            doctor_output = {"object": "agent_hub.doctor", "ok": True}
            validation_result = {"object": "agent_hub.release_validation", "ok": True, "failures": []}
            with (
                patch("agent_hub.commands_server._debug_doctor_output", return_value=doctor_output),
                patch("agent_hub.commands_server._debug_validation_result", return_value=validation_result),
                redirect_stdout(buffer),
            ):
                code = main(["--config", str(path), "debug-bundle", "--output", str(output)])

            self.assertEqual(code, 0)
            self.assertTrue(output.exists())
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("version-info.json", names)
                self.assertIn("config.json", names)
                self.assertIn("logs.json", names)
                self.assertIn("doctor.json", names)
                self.assertIn("provider-status.json", names)
                self.assertIn("validation.json", names)
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                self.assertIn("doctor.json", manifest["files"])
                config = json.loads(archive.read("config.json").decode("utf-8"))
                self.assertEqual(config["agents"][0]["api_key"], "[REDACTED]")
                self.assertEqual(config["agents"][0]["api_key_env"], "ECHO_API_KEY")
                validation = json.loads(archive.read("validation.json").decode("utf-8"))
                self.assertEqual(validation["object"], "agent_hub.release_validation")

    def test_chat_runs_one_turn_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-hub.config.json"
            path.write_text(
                json.dumps(
                    {
                        "state_dir": str(Path(tmp) / "state"),
                        "debug_echo_enabled": True,
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

    def test_inspect_request_reports_context_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "request.json"
            path.write_text(
                json.dumps(
                    {
                        "model": "agent-hub-coding",
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "hello"},
                                    {"type": "tool_result", "tool_use_id": "x", "content": "ok"},
                                ],
                                "task_progress": [{"title": "todo"}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            config = Path(tmp) / "agent-hub.config.json"
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = main(
                    [
                        "--config",
                        str(config),
                        "inspect-request",
                        str(path),
                        "--api-shape",
                        "openai-chat",
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            data = json.loads(buffer.getvalue())
            self.assertEqual(data["diagnostics"]["structured_content_messages"], 1)
            self.assertEqual(data["diagnostics"]["preserved_tool_results"], 1)
            self.assertTrue(data["diagnostics"]["cline_compatibility_mode"])

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
