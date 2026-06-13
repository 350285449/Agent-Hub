from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.core.router import AgentRouter, RouterError
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.observability import recent_events
from agent_hub.permissions import (
    LOCAL,
    TRUSTED_CLOUD,
    UNTRUSTED_EXTERNAL,
    PermissionManager,
    mark_trusted_approval,
    provider_trust_level,
    tool_permission_request,
)


class ProviderCompatibilityTests(unittest.TestCase):
    def test_approval_mode_auto_allows_trusted_cloud_and_audits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = _config(
                Path(tmp),
                approval_mode="auto",
                cline_compatibility_mode=False,
                agent=_trusted_cloud_agent(),
            )

            response = AgentRouter(config, provider_factory=_provider(calls)).route(
                _workspace_request()
            )

            self.assertEqual(response.text, "ok")
            self.assertEqual(calls, ["cloud"])
            audit = recent_events(config.state_dir, "security_audit", limit=10)
            self.assertTrue(audit)
            self.assertEqual(audit[-1]["provider"], "openai")
            self.assertEqual(audit[-1]["trust_level"], TRUSTED_CLOUD)
            self.assertTrue(audit[-1]["allowed"])
            self.assertTrue(audit[-1]["workspace_content_sent"])
            self.assertFalse(audit[-1]["interactive_approval_required"])
            self.assertNotIn("Current file", str(audit[-1]["permission"]))
            self.assertNotIn("preview", str(audit[-1]["permission"]))

    def test_cline_compatibility_mode_does_not_bypass_trusted_cloud_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = _config(
                Path(tmp),
                approval_mode="ask",
                cline_compatibility_mode=True,
                agent=_trusted_cloud_agent(),
            )

            with self.assertRaises(RouterError):
                AgentRouter(config, provider_factory=_provider(calls)).route(
                    _workspace_request(api_shape="openai-chat")
                )

            self.assertEqual(calls, [])

    def test_cline_user_agent_does_not_bypass_trusted_cloud_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = _config(
                Path(tmp),
                approval_mode="ask",
                cline_compatibility_mode=True,
                agent=_trusted_cloud_agent(),
            )

            router = AgentRouter(config, provider_factory=_provider(calls))
            request = _workspace_request(metadata={"user_agent": "Cline/3.0 VSCode"})
            with self.assertRaises(RouterError):
                router.route(request)
            response = router.route(
                mark_trusted_approval(
                    HubRequest(
                        session_id=request.session_id,
                        api_shape=request.api_shape,
                        messages=request.messages,
                        metadata=request.metadata,
                        raw={"agent_hub": {"provider_approval_granted": True}},
                    ),
                    source="test-trusted-session",
                )
            )

            self.assertEqual(response.text, "ok")
            self.assertEqual(calls, ["cloud"])
            audit = recent_events(config.state_dir, "security_audit", limit=10)
            self.assertEqual(audit[-1]["client"]["user_agent"], "Cline/3.0 VSCode")

    def test_unknown_external_provider_is_blocked_even_in_auto_compat_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = _config(
                Path(tmp),
                approval_mode="auto",
                cline_compatibility_mode=True,
                agent=AgentConfig(
                    name="cloud",
                    provider="openai-compatible",
                    provider_type="custom-external",
                    base_url="https://unknown.example.invalid/v1",
                    model="unknown-model",
                    api_key="secret",
                    free=False,
                ),
            )

            with self.assertRaises(RouterError) as error:
                AgentRouter(config, provider_factory=_provider(calls)).route(
                    _workspace_request(api_shape="openai-chat")
                )

            self.assertEqual(calls, [])
            self.assertEqual(error.exception.failover[0].error_type, "permission_required")
            audit = recent_events(config.state_dir, "security_audit", limit=10)
            self.assertFalse(audit[-1]["allowed"])
            self.assertEqual(audit[-1]["trust_level"], UNTRUSTED_EXTERNAL)
            self.assertTrue(audit[-1]["interactive_approval_required"])

    def test_local_provider_is_always_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            local_agent = AgentConfig(
                name="cloud",
                provider="openai-compatible",
                provider_type="openai-compatible",
                base_url="http://127.0.0.1:11434/v1",
                model="local-model",
                free=True,
            )
            config = _config(
                Path(tmp),
                approval_mode="ask",
                cline_compatibility_mode=False,
                agent=local_agent,
            )

            response = AgentRouter(config, provider_factory=_provider(calls)).route(
                _workspace_request()
            )

            self.assertEqual(response.text, "ok")
            self.assertEqual(calls, ["cloud"])
            self.assertEqual(provider_trust_level(local_agent), LOCAL)
            audit = recent_events(config.state_dir, "security_audit", limit=10)
            self.assertEqual(audit[-1]["trust_level"], LOCAL)
            self.assertTrue(audit[-1]["allowed"])

    def test_ollama_cloud_provider_type_is_not_downgraded_by_localhost_url(self) -> None:
        agent = AgentConfig(
            name="ollama-cloud",
            provider="openai-compatible",
            provider_type="ollama-cloud",
            base_url="http://127.0.0.1:11434/v1",
            model="gpt-oss:120b-cloud",
            api_key="secret",
            free=False,
        )

        self.assertEqual(provider_trust_level(agent), TRUSTED_CLOUD)

    def test_ollama_cloud_localhost_proxy_requires_cloud_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            agent = AgentConfig(
                name="ollama-cloud",
                provider="openai-compatible",
                provider_type="ollama-cloud",
                base_url="http://127.0.0.1:11434/v1",
                model="gpt-oss:120b-cloud",
                api_key="secret",
                free=False,
            )
            config = _config(
                Path(tmp),
                approval_mode="ask",
                cline_compatibility_mode=False,
                agent=agent,
            )

            with self.assertRaises(RouterError) as error:
                AgentRouter(config, provider_factory=_provider(calls)).route(
                    _workspace_request(api_shape="openai-chat")
                )

            self.assertEqual(calls, [])
            self.assertEqual(error.exception.failover[0].error_type, "permission_required")
            audit = recent_events(config.state_dir, "security_audit", limit=10)
            self.assertEqual(audit[-1]["trust_level"], TRUSTED_CLOUD)
            self.assertFalse(audit[-1]["allowed"])
            self.assertTrue(audit[-1]["interactive_approval_required"])

    def test_provider_trust_classification_rules(self) -> None:
        self.assertEqual(
            provider_trust_level(
                AgentConfig(
                    name="ollama",
                    provider="ollama",
                    provider_type="ollama",
                    base_url="http://localhost:11434",
                    model="qwen",
                )
            ),
            LOCAL,
        )
        self.assertEqual(
            provider_trust_level(
                AgentConfig(
                    name="openrouter",
                    provider="openai-compatible",
                    provider_type="openrouter",
                    base_url="https://openrouter.ai/api/v1",
                    model="model",
                )
            ),
            TRUSTED_CLOUD,
        )
        self.assertEqual(
            provider_trust_level(
                AgentConfig(
                    name="unknown",
                    provider="openai-compatible",
                    provider_type="custom-external",
                    base_url="https://unknown.example.invalid/v1",
                    model="model",
                )
            ),
            UNTRUSTED_EXTERNAL,
        )

    def test_dangerous_tools_are_still_blocked_in_auto_mode(self) -> None:
        request = tool_permission_request("run_command", {"command": "rm -rf ."})
        decision = PermissionManager("auto", approval_granted=True).check(request)

        self.assertFalse(decision.allowed)
        self.assertTrue(decision.denied)


def _config(
    path: Path,
    *,
    approval_mode: str,
    cline_compatibility_mode: bool,
    agent: AgentConfig,
) -> HubConfig:
    return HubConfig(
        state_dir=path / "state",
        workspace_dir=path,
        approval_mode=approval_mode,
        cline_compatibility_mode=cline_compatibility_mode,
        free_only=False,
        default_route=[agent.name],
        agents={agent.name: agent},
    )


def _trusted_cloud_agent() -> AgentConfig:
    return AgentConfig(
        name="cloud",
        provider="openai",
        provider_type="openai",
        model="trusted-model",
        api_key="secret",
        free=False,
    )


def _workspace_request(
    *,
    api_shape: str = "native",
    metadata: dict | None = None,
) -> HubRequest:
    return HubRequest(
        session_id="compat",
        api_shape=api_shape,
        messages=[{"role": "user", "content": "Current file: app.py\nhello"}],
        metadata=metadata or {},
    )


def _provider(calls: list[str]):
    class Provider:
        def __init__(self, agent: AgentConfig) -> None:
            self.agent = agent

        def complete(self, request: HubRequest) -> ProviderResult:
            calls.append(self.agent.name)
            return ProviderResult(text="ok", model=self.agent.model)

    return Provider


if __name__ == "__main__":
    unittest.main()
