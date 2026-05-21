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
            health = router.health_snapshot()
            self.assertEqual(health["claude"]["failure_count"], 1)
            self.assertEqual(health["openai"]["success_count"], 1)

    def test_cooldown_avoids_repeated_failed_provider(self) -> None:
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

            router.route(request)
            router.route(request)

            self.assertEqual(calls, ["claude", "openai", "openai"])

    def test_provider_balancing_respects_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["low", "high"],
                agents={
                    "low": AgentConfig(
                        name="low",
                        provider="openai-compatible",
                        model="low-test",
                        base_url="http://127.0.0.1:9999",
                        priority=1,
                    ),
                    "high": AgentConfig(
                        name="high",
                        provider="openai-compatible",
                        model="high-test",
                        base_url="http://127.0.0.1:9999",
                        priority=10,
                    ),
                },
            )
            router = AgentRouter(
                config,
                provider_factory=lambda agent: _FakeProvider(agent, calls),
            )

            response = router.route(
                HubRequest(
                    session_id="abc",
                    messages=[{"role": "user", "content": "hello"}],
                )
            )

            self.assertEqual(calls, ["high"])
            self.assertEqual(response.agent, "high")

    def test_session_history_is_replayed_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seen: list[list[dict]] = []
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["openai"],
                agents={
                    "openai": AgentConfig(
                        name="openai",
                        provider="openai-compatible",
                        model="openai-test",
                        base_url="http://127.0.0.1:9999",
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

    def test_free_only_skips_paid_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["paid", "local"],
                agents={
                    "paid": AgentConfig(
                        name="paid",
                        provider="openai",
                        model="paid-test",
                    ),
                    "local": AgentConfig(
                        name="local",
                        provider="openai-compatible",
                        model="local-test",
                        base_url="http://127.0.0.1:9999",
                    ),
                },
            )
            router = AgentRouter(
                config,
                provider_factory=lambda agent: _FakeProvider(agent, calls),
            )

            response = router.route(
                HubRequest(
                    session_id="abc",
                    messages=[{"role": "user", "content": "hello"}],
                )
            )

            self.assertEqual(calls, ["local"])
            self.assertEqual(response.agent, "local")
            self.assertEqual(response.failover[0].agent, "paid")
            self.assertIn("free_only", response.failover[0].reason)

    def test_agent_without_enough_context_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["tiny", "large"],
                agents={
                    "tiny": AgentConfig(
                        name="tiny",
                        provider="openai-compatible",
                        model="tiny-test",
                        base_url="http://127.0.0.1:9999",
                        max_tokens=200,
                        context_window=210,
                    ),
                    "large": AgentConfig(
                        name="large",
                        provider="openai-compatible",
                        model="large-test",
                        base_url="http://127.0.0.1:9999",
                        max_tokens=200,
                        context_window=1000,
                    ),
                },
            )
            router = AgentRouter(
                config,
                provider_factory=lambda agent: _FakeProvider(agent, calls),
            )

            response = router.route(
                HubRequest(
                    session_id="abc",
                    messages=[{"role": "user", "content": "x" * 100}],
                )
            )

            self.assertEqual(calls, ["large"])
            self.assertEqual(response.agent, "large")
            self.assertEqual(response.failover[0].agent, "tiny")
            self.assertIn("context window is too small", response.failover[0].reason)

    def test_token_limit_finish_reason_fails_over_to_next_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["small", "large"],
                agents={
                    "small": AgentConfig(
                        name="small",
                        provider="openai-compatible",
                        model="small-test",
                        base_url="http://127.0.0.1:9999",
                    ),
                    "large": AgentConfig(
                        name="large",
                        provider="openai-compatible",
                        model="large-test",
                        base_url="http://127.0.0.1:9999",
                    ),
                },
            )

            class TokenLimitProvider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(self.agent.name)
                    if self.agent.name == "small":
                        return ProviderResult(
                            text="partial",
                            model=self.agent.model,
                            finish_reason="length",
                        )
                    return ProviderResult(
                        text="complete",
                        model=self.agent.model,
                        finish_reason="stop",
                    )

            response = AgentRouter(config, provider_factory=TokenLimitProvider).route(
                HubRequest(
                    session_id="abc",
                    route="local-agent",
                    messages=[{"role": "user", "content": "hello"}],
                )
            )

            self.assertEqual(calls, ["small", "large"])
            self.assertEqual(response.text, "complete")
            self.assertEqual(response.failover[0].agent, "small")
            self.assertIn("token limit", response.failover[0].reason)
            public = response.to_native_dict()
            self.assertEqual(public["model"], "local-agent")
            self.assertNotIn("failover", public)

    def test_route_errors_when_no_agent_has_enough_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["tiny"],
                agents={
                    "tiny": AgentConfig(
                        name="tiny",
                        provider="openai-compatible",
                        model="tiny-test",
                        base_url="http://127.0.0.1:9999",
                        max_tokens=200,
                        context_window=210,
                    )
                },
            )
            router = AgentRouter(config, provider_factory=lambda agent: _FakeProvider(agent, []))

            with self.assertRaises(RouterError) as error:
                router.route(
                    HubRequest(
                        session_id="abc",
                        messages=[{"role": "user", "content": "x" * 100}],
                    )
                )

            self.assertIn("context window is too small", str(error.exception))


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
                provider="openai-compatible",
                model="claude-test",
                base_url="http://127.0.0.1:9999",
            ),
            "openai": AgentConfig(
                name="openai",
                provider="openai-compatible",
                model="openai-test",
                base_url="http://127.0.0.1:9999",
            ),
        },
    )


if __name__ == "__main__":
    unittest.main()
