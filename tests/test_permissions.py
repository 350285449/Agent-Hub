from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.agent_tools import AgentToolbox
from agent_hub.config import AgentConfig, HubConfig, config_from_dict, free_local_config
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.permissions import PermissionManager, PermissionRequest, mark_trusted_approval
from agent_hub.core.router import AgentRouter, RouterError


class PermissionManagerTests(unittest.TestCase):
    def test_ask_mode_requires_approval_for_sensitive_action(self) -> None:
        decision = PermissionManager("ask").check(
            PermissionRequest(
                action="run_shell_command",
                category="shell_command",
                description="Run tests",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_approval)

    def test_readonly_denies_file_writes(self) -> None:
        decision = PermissionManager("readonly").check(
            PermissionRequest(
                action="write_file",
                category="file_write",
                description="Write file",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertTrue(decision.denied)

    def test_default_loaded_configs_use_safe_mode(self) -> None:
        self.assertEqual(free_local_config().approval_mode, "safe")
        self.assertEqual(config_from_dict({}).approval_mode, "safe")
        self.assertEqual(config_from_dict({}).shell_command_policy, "deny")

    def test_agent_tools_ask_before_any_shell_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            toolbox = AgentToolbox(
                HubConfig(workspace_dir=Path(tmp), approval_mode="ask"),
                HubRequest(session_id="s", messages=[]),
            )

            result = toolbox.run("run_command", {"command": "python -c \"print('hi')\""})

            self.assertFalse(result["ok"])
            self.assertTrue(result["approval_required"])
            self.assertEqual(result["permission"]["request"]["category"], "shell_command")

    def test_external_provider_requires_provider_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                workspace_dir=Path(tmp),
                approval_mode="ask",
                free_only=False,
                default_route=["cloud"],
                agents={
                    "cloud": AgentConfig(
                        name="cloud",
                        provider="openai",
                        model="paid-model",
                        api_key="secret",
                    )
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    return ProviderResult(text="ok", model=self.agent.model)

            router = AgentRouter(config, provider_factory=Provider)
            request = HubRequest(
                session_id="s",
                messages=[{"role": "user", "content": "Current file: app.py\nhello"}],
            )

            with self.assertRaises(RouterError) as error:
                router.route(request)

            self.assertIn("Provider requires approval", str(error.exception))
            self.assertEqual(error.exception.failover[0].error_type, "permission_required")

            approved = router.route(
                mark_trusted_approval(HubRequest(
                    session_id="s",
                    messages=request.messages,
                    raw={"agent_hub": {"provider_approval_granted": True}},
                ), source="test-trusted-session")
            )
            self.assertEqual(approved.text, "ok")

    def test_enterprise_permissions_are_enforced_only_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                workspace_dir=Path(tmp),
                approval_mode="auto",
                free_only=False,
                default_route=["cloud"],
                agents={
                    "cloud": AgentConfig(
                        name="cloud",
                        provider="openai",
                        model="paid-model",
                        api_key="secret",
                    )
                },
            )

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(self.agent.name)
                    return ProviderResult(text="ok", model=self.agent.model, finish_reason="stop")

            request = HubRequest(
                session_id="s",
                messages=[{"role": "user", "content": "Current file: app.py\nhello"}],
            )
            self.assertEqual(AgentRouter(config, provider_factory=Provider).route(request).text, "ok")

            config.enterprise_mode_enabled = True
            with self.assertRaises(RouterError) as error:
                AgentRouter(config, provider_factory=Provider).route(request)
            self.assertIn("Enterprise mode requires a user_id", str(error.exception))

            config.enterprise_users = [{"id": "alice", "roles": ["developer"]}]
            config.enterprise_roles = [
                {"name": "developer", "permissions": ["workspace_cloud"]}
            ]
            allowed = AgentRouter(config, provider_factory=Provider).route(
                HubRequest(
                    session_id="s",
                    messages=request.messages,
                    raw={"agent_hub": {"user_id": "alice", "workspace_id": "default"}},
                )
            )

            self.assertEqual(allowed.text, "ok")


if __name__ == "__main__":
    unittest.main()
