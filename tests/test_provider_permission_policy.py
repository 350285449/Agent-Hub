from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.core.router import AgentRouter
from agent_hub.models import HubRequest
from agent_hub.permissions import mark_trusted_approval
from agent_hub.observability import recent_events
from agent_hub.security.provider_permissions import ProviderPermissionPolicy


class ProviderPermissionPolicyTests(unittest.TestCase):
    def test_trusted_cloud_auto_records_permission_and_audit_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                approval_mode="auto",
                free_only=False,
            )
            agent = AgentConfig(
                name="cloud",
                provider="openai",
                model="gpt-test",
                api_key="secret",
            )
            request = HubRequest(
                session_id="s",
                messages=[{"role": "user", "content": "Current file: app.py\nhello"}],
            )

            decision = ProviderPermissionPolicy(config).check(agent, request)
            permission_events = recent_events(config.state_dir, "permissions")
            audit_events = recent_events(config.state_dir, "security_audit")

            self.assertIsNotNone(decision)
            self.assertTrue(decision.allowed)
            self.assertEqual(permission_events[-1]["type"], "provider_permission")
            self.assertTrue(permission_events[-1]["compatibility_bypass"])
            self.assertEqual(audit_events[-1]["type"], "provider_routing_audit")
            self.assertTrue(audit_events[-1]["allowed"])

    def test_untrusted_external_requires_explicit_provider_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                approval_mode="auto",
                free_only=False,
            )
            agent = AgentConfig(
                name="external",
                provider="custom-cloud",
                model="remote-model",
                api_key="secret",
            )
            request = HubRequest(
                session_id="s",
                messages=[{"role": "user", "content": "hello"}],
            )
            policy = ProviderPermissionPolicy(config)

            blocked = policy.check(agent, request)
            approved = policy.check(
                agent,
                mark_trusted_approval(HubRequest(
                    session_id="s",
                    messages=request.messages,
                    raw={"agent_hub": {"provider_approval_granted": True}},
                ), source="test-trusted-session"),
            )

            self.assertFalse(blocked.allowed)
            self.assertTrue(blocked.requires_approval)
            self.assertTrue(approved.allowed)

    def test_enterprise_policy_is_checked_before_trusted_auto_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                approval_mode="auto",
                free_only=False,
                enterprise_mode_enabled=True,
            )
            agent = AgentConfig(
                name="cloud",
                provider="openai",
                model="gpt-test",
                api_key="secret",
            )
            request = HubRequest(
                session_id="s",
                messages=[{"role": "user", "content": "Current file: app.py\nhello"}],
            )

            decision = ProviderPermissionPolicy(config).check(agent, request)

            self.assertFalse(decision.allowed)
            self.assertTrue(decision.denied)
            self.assertIn("Enterprise mode requires a user_id", decision.reason)

    def test_router_keeps_provider_permission_compatibility_delegate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp) / "state",
                approval_mode="auto",
                free_only=False,
            )
            agent = AgentConfig(
                name="cloud",
                provider="openai",
                model="gpt-test",
                api_key="secret",
            )
            router = AgentRouter(config)

            decision = router._provider_permission_decision(
                agent,
                HubRequest(session_id="s", messages=[{"role": "user", "content": "hello"}]),
            )

            self.assertIsInstance(router.provider_permission_policy, ProviderPermissionPolicy)
            self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main()
