from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.providers import ProviderError
from agent_hub.router import AgentRouter, RouterError


class _FakeProvider:
    def __init__(self, agent: AgentConfig, calls: list[str]) -> None:
        self.agent = agent
        self.calls = calls

    def complete(self, request: HubRequest) -> ProviderResult:
        self.calls.append(self.agent.name)
        if self.agent.name == "claude":
            raise ProviderError("quota exhausted", status_code=429, retryable=True)
        return ProviderResult(text="done", model=self.agent.model, finish_reason="stop")


class RouterTests(unittest.TestCase):
    def test_failover_preserves_request_and_records_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = _config(Path(tmp))
            router = AgentRouter(
                config,
                provider_factory=lambda agent: _FakeProvider(agent, calls),
            )
            request = HubRequest(
                session_id="abc",
                route="coding",
                messages=[{"role": "user", "content": "code a parser"}],
            )

            response = router.route(request)

            self.assertEqual(calls, ["claude", "openai"])
            self.assertEqual(response.agent, "openai")
            self.assertEqual(response.text, "done")
            self.assertEqual(len(response.failover), 1)
            self.assertEqual(response.failover[0].agent, "claude")
            self.assertIn("quota", response.failover[0].reason)

    def test_session_history_is_replayed_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seen: list[list[dict]] = []
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["openai"],
                agents={
                    "openai": AgentConfig(
                        name="openai",
                        provider="openai",
                        model="openai-test",
                    )
                },
            )

            class CaptureProvider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    seen.append(list(request.messages))
                    return ProviderResult(text=f"reply-{len(seen)}", model=self.agent.model)

            router = AgentRouter(config, provider_factory=CaptureProvider)
            router.route(
                HubRequest(
                    session_id="abc",
                    messages=[{"role": "user", "content": "first"}],
                    use_session_history=True,
                )
            )
            router.route(
                HubRequest(
                    session_id="abc",
                    messages=[{"role": "user", "content": "second"}],
                    use_session_history=True,
                )
            )

            self.assertEqual(
                seen[-1],
                [
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "reply-1"},
                    {"role": "user", "content": "second"},
                ],
            )

    def test_non_retryable_error_stops_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = _config(Path(tmp))

            class BadProvider(_FakeProvider):
                def complete(self, request: HubRequest) -> ProviderResult:
                    self.calls.append(self.agent.name)
                    raise ProviderError("invalid payload", status_code=400, retryable=False)

            router = AgentRouter(
                config,
                provider_factory=lambda agent: BadProvider(agent, calls),
            )

            with self.assertRaises(RouterError):
                router.route(
                    HubRequest(
                        session_id="abc",
                        messages=[{"role": "user", "content": "hello"}],
                    )
                )
            self.assertEqual(calls, ["claude"])

    def test_keyword_route_selects_coding_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = _config(Path(tmp))
            config.default_route = ["general"]
            config.agents["general"] = AgentConfig(
                name="general",
                provider="echo",
                model="general-model",
            )
            router = AgentRouter(
                config,
                provider_factory=lambda agent: _FakeProvider(agent, calls),
            )

            response = router.route(
                HubRequest(
                    session_id="abc",
                    messages=[{"role": "user", "content": "please refactor this code"}],
                )
            )

            self.assertEqual(response.agent, "openai")
            self.assertEqual(calls, ["claude", "openai"])


def _config(path: Path) -> HubConfig:
    return HubConfig(
        state_dir=path,
        default_route=["claude", "openai"],
        routes=[
            RouteRule(
                name="coding",
                keywords=["code", "refactor"],
                agents=["claude", "openai"],
            )
        ],
        agents={
            "claude": AgentConfig(
                name="claude",
                provider="anthropic",
                model="claude-test",
            ),
            "openai": AgentConfig(
                name="openai",
                provider="openai",
                model="openai-test",
            ),
        },
    )


if __name__ == "__main__":
    unittest.main()
