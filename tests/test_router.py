from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.providers import ProviderError
from agent_hub.core.router import AgentRouter, RouterError


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

    def test_quota_failures_mark_agent_temporarily_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = _config(Path(tmp))
            config.quota_cooldown_seconds = 600
            router = AgentRouter(
                config,
                provider_factory=lambda agent: _FakeProvider(agent, calls),
            )

            response = router.route(
                HubRequest(
                    session_id="abc",
                    route="coding",
                    messages=[{"role": "user", "content": "code a parser"}],
                )
            )

            self.assertEqual(response.agent, "openai")
            self.assertEqual(response.failover[0].error_type, "quota_exhausted")
            health = router.health_snapshot()
            self.assertEqual(health["claude"]["last_error_type"], "quota_exhausted")
            self.assertGreater(health["claude"]["unavailable_until"], 0)

    def test_provider_health_persists_across_router_restarts(self) -> None:
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
            restarted = AgentRouter(
                config,
                provider_factory=lambda agent: _FakeProvider(agent, calls),
            )
            restarted.route(request)

            self.assertEqual(calls, ["claude", "openai", "openai"])
            health = restarted.health_snapshot(include_history=True)
            self.assertEqual(health["claude"]["failure_count"], 1)
            self.assertGreater(health["claude"]["cooldown_until"], 0)
            self.assertTrue(health["claude"]["failover_events"])

    def test_success_metadata_can_cool_down_exhausted_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = HubConfig(
                state_dir=Path(tmp),
                enable_load_balancing=False,
                default_route=["primary", "fallback"],
                agents={
                    "primary": AgentConfig(
                        name="primary",
                        provider="openai-compatible",
                        model="primary-test",
                        base_url="http://127.0.0.1:9999",
                        cooldown_seconds=300,
                    ),
                    "fallback": AgentConfig(
                        name="fallback",
                        provider="openai-compatible",
                        model="fallback-test",
                        base_url="http://127.0.0.1:9999",
                    ),
                },
            )

            class MetadataProvider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(self.agent.name)
                    if self.agent.name == "primary":
                        return ProviderResult(
                            text="almost out",
                            model=self.agent.model,
                            raw={
                                "agent_hub_provider": {
                                    "quota": {"requests_remaining": 0}
                                }
                            },
                        )
                    return ProviderResult(text="fallback", model=self.agent.model)

            router = AgentRouter(config, provider_factory=MetadataProvider)
            request = HubRequest(
                session_id="abc",
                messages=[{"role": "user", "content": "hello"}],
            )

            self.assertEqual(router.route(request).agent, "primary")
            self.assertEqual(router.route(request).agent, "fallback")

            self.assertEqual(calls, ["primary", "fallback"])
            health = router.health_snapshot()
            self.assertEqual(health["primary"]["requests_remaining"], 0)
            self.assertFalse(health["primary"]["available"])

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

    def test_tool_requests_prefer_tool_capable_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["plain", "tooly"],
                agents={
                    "plain": AgentConfig(
                        name="plain",
                        provider="openai-compatible",
                        model="plain-test",
                        base_url="http://127.0.0.1:9999",
                        priority=20,
                    ),
                    "tooly": AgentConfig(
                        name="tooly",
                        provider="openai-compatible",
                        model="tooly-test",
                        base_url="http://127.0.0.1:9999",
                        supports_tools=True,
                        supports_function_calling=True,
                        coding_score=0.9,
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
                    messages=[{"role": "user", "content": "edit a file"}],
                    raw={
                        "tools": [
                            {
                                "type": "function",
                                "function": {"name": "read_file", "parameters": {"type": "object"}},
                            }
                        ]
                    },
                )
            )

            self.assertEqual(response.agent, "tooly")
            self.assertEqual(calls, ["tooly"])

    def test_cline_tool_request_does_not_route_to_echo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = HubConfig(
                state_dir=Path(tmp),
                routes=[RouteRule(name="coding", agents=["plain", "echo"])],
                agents={
                    "plain": AgentConfig(
                        name="plain",
                        provider="openai-compatible",
                        model="plain-test",
                        base_url="http://127.0.0.1:9999",
                    ),
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="local-echo",
                    ),
                },
            )
            router = AgentRouter(
                config,
                provider_factory=lambda agent: _FakeProvider(agent, calls),
            )

            with self.assertRaises(RouterError) as error:
                router.route(
                    HubRequest(
                        session_id="cline",
                        api_shape="openai-chat",
                        route="coding",
                        messages=[{"role": "user", "content": "Read README"}],
                        raw={
                            "model": "agent-hub-coding",
                            "tools": [
                                {
                                    "type": "function",
                                    "function": {"name": "read_file", "parameters": {"type": "object"}},
                                }
                            ],
                        },
                    )
                )

            self.assertEqual(calls, [])
            self.assertEqual(error.exception.error_type, "no_tool_capable_model")
            self.assertIn("No tool-capable model", str(error.exception))

    def test_tool_request_with_only_echo_returns_no_tool_capable_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp),
                routes=[RouteRule(name="coding", agents=["echo"])],
                agents={
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="local-echo",
                    )
                },
            )
            router = AgentRouter(config, provider_factory=lambda agent: _FakeProvider(agent, []))

            with self.assertRaises(RouterError) as error:
                router.route(
                    HubRequest(
                        session_id="cline",
                        api_shape="openai-chat",
                        route="coding",
                        messages=[{"role": "user", "content": "Read README"}],
                        raw={
                            "tools": [
                                {
                                    "type": "function",
                                    "function": {"name": "read_file", "parameters": {"type": "object"}},
                                }
                            ],
                        },
                    )
                )

            self.assertEqual(error.exception.error_type, "no_tool_capable_model")
            self.assertIn("Echo is a diagnostic provider", str(error.exception))

    def test_no_tool_capable_model_error_names_missing_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp),
                routes=[RouteRule(name="coding", agents=["codex", "echo"])],
                agents={
                    "codex": AgentConfig(
                        name="codex",
                        provider="openai",
                        model="gpt-test",
                        api_key_env="OPENAI_API_KEY",
                        free=True,
                        supports_tools=True,
                    ),
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="local-echo",
                    ),
                },
            )
            router = AgentRouter(config, provider_factory=lambda agent: _FakeProvider(agent, []))

            with self.assertRaises(RouterError) as error:
                router.route(
                    HubRequest(
                        session_id="cline",
                        api_shape="openai-chat",
                        route="coding",
                        messages=[{"role": "user", "content": "Read README"}],
                        raw={
                            "tools": [
                                {
                                    "type": "function",
                                    "function": {"name": "read_file", "parameters": {"type": "object"}},
                                }
                            ],
                        },
                    )
                )

            self.assertEqual(error.exception.error_type, "no_tool_capable_model")
            self.assertIn("OPENAI_API_KEY", str(error.exception))
            self.assertIn("OPENAI_API_KEY", error.exception.suggested_fix or "")

    def test_debug_echo_non_tool_request_works_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp),
                debug_echo_enabled=True,
                default_route=["echo"],
                agents={
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="local-echo",
                    )
                },
            )
            router = AgentRouter(config, provider_factory=lambda agent: _FakeProvider(agent, []))

            response = router.route(
                HubRequest(
                    session_id="debug",
                    api_shape="openai-chat",
                    messages=[{"role": "user", "content": "hello"}],
                    raw={"model": "agent:echo"},
                )
            )

            self.assertEqual(response.agent, "echo")
            self.assertEqual(response.text, "done")

    def test_preferred_agent_can_fall_back_to_route_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = _config(Path(tmp))
            router = AgentRouter(
                config,
                provider_factory=lambda agent: _FakeProvider(agent, calls),
            )

            response = router.route(
                HubRequest(
                    session_id="abc",
                    preferred_agent="claude",
                    route="coding",
                    messages=[{"role": "user", "content": "code a parser"}],
                )
            )

            self.assertEqual(calls, ["claude", "openai"])
            self.assertEqual(response.agent, "openai")

    def test_recommendation_prefers_coding_model_for_coding_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["general", "coder"],
                agents={
                    "general": AgentConfig(
                        name="general",
                        provider="openai-compatible",
                        model="general-test",
                        base_url="http://127.0.0.1:9999",
                        coding_score=0.2,
                        reasoning_score=0.8,
                        speed_score=0.8,
                    ),
                    "coder": AgentConfig(
                        name="coder",
                        provider="openai-compatible",
                        model="coder-test",
                        base_url="http://127.0.0.1:9999",
                        coding_score=0.95,
                        reasoning_score=0.6,
                        supports_tools=True,
                    ),
                },
            )
            router = AgentRouter(config)

            recommendations = router.recommend(
                HubRequest(
                    session_id="abc",
                    messages=[{"role": "user", "content": "fix the failing tests in this repo"}],
                ),
                needs_tools=True,
            )

            self.assertEqual(recommendations[0]["agent"], "coder")
            self.assertTrue(recommendations[0]["supports_tools"])

    def test_recommendation_hides_echo_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp),
                default_route=["cloud", "echo"],
                agents={
                    "cloud": AgentConfig(
                        name="cloud",
                        provider="openai-compatible",
                        provider_type="ollama-cloud",
                        model="cloud-test",
                        base_url="http://127.0.0.1:11434",
                        free=True,
                        context_window=128000,
                    ),
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="local-echo",
                        free=True,
                        context_window=1000000,
                        speed_score=1,
                    ),
                },
            )

            recommendations = AgentRouter(config).recommend(
                HubRequest(
                    session_id="abc",
                    messages=[{"role": "user", "content": "hello"}],
                )
            )

            self.assertEqual(recommendations[0]["agent"], "cloud")
            self.assertNotIn("echo", {row["agent"] for row in recommendations})

    def test_recommendation_allows_echo_in_debug_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp),
                debug_echo_enabled=True,
                default_route=["echo"],
                agents={
                    "echo": AgentConfig(
                        name="echo",
                        provider="echo",
                        model="local-echo",
                        free=True,
                    )
                },
            )

            recommendations = AgentRouter(config).recommend(
                HubRequest(
                    session_id="abc",
                    messages=[{"role": "user", "content": "hello"}],
                )
            )

            self.assertEqual(recommendations[0]["agent"], "echo")

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
