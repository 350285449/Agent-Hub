from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.core.health import ProviderHealth, calculate_provider_score
from agent_hub.core.router import AgentRouter, RouterError
from agent_hub.events import (
    CONTEXT_TRUNCATED,
    PROVIDER_FAILED,
    PROVIDER_SELECTED,
    ROUTER_FALLBACK,
    STREAM_FAILED,
    STREAM_STARTED,
    TOOL_EXECUTED,
)
from agent_hub.models import ErrorCategory, HubRequest, ProviderResult, StructuredError
from agent_hub.observability import recent_events
from agent_hub.providers import ProviderError
from agent_hub.providers.base import StreamChunk
from agent_hub.tools.registry import ToolRegistry
from agent_hub.tools.runtime import ToolExecutionContext, ToolExecutionPipeline
from agent_hub.tools.types import ToolCall
from agent_hub.workflows import (
    ConsensusStrategy,
    MergeStrategy,
    ProviderCallPlan,
    RoleStrategy,
    WorkflowExtensionPoints,
)


class FoundationPhaseTests(unittest.TestCase):
    def test_structured_errors_for_provider_and_router(self) -> None:
        provider_error = ProviderError(
            "quota exceeded",
            status_code=429,
            retryable=True,
            metadata={"requests_remaining": 0},
        ).to_structured_error()

        self.assertEqual(provider_error.category, ErrorCategory.QUOTA)
        self.assertTrue(provider_error.retryable)
        self.assertEqual(provider_error.to_dict()["status_code"], 429)

        router_error = RouterError(
            "No usable model",
            error_type="configuration_error",
            suggested_fix="Configure a provider.",
            status_code=400,
        ).to_structured_error()

        self.assertEqual(router_error.category, ErrorCategory.CONFIGURATION)
        self.assertIn("Configure a provider", router_error.user_message)

        manual = StructuredError(
            category=ErrorCategory.TOOL,
            code="tool_failed",
            message="Tool failed",
            retryable=False,
        )
        self.assertEqual(manual.to_dict()["user_message"], "Tool failed")

    def test_router_records_provider_fallback_selection_and_context_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            config = _routing_config(Path(tmp), ["bad", "good"])
            config.max_context_tokens = 500
            for agent in config.agents.values():
                agent.context_window = 2000
                agent.max_tokens = 100

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    calls.append(self.agent.name)
                    if self.agent.name == "bad":
                        return ProviderResult(text="", model=self.agent.model, raw={})
                    return ProviderResult(
                        text="ok",
                        model=self.agent.model,
                        finish_reason="stop",
                        usage={"prompt_tokens": 50, "completion_tokens": 5},
                    )

            messages = [
                {"role": "user", "content": f"message {index} " + ("x" * 700)}
                for index in range(10)
            ]
            response = AgentRouter(config, provider_factory=Provider).route(
                HubRequest(session_id="s", route="coding", messages=messages)
            )

            self.assertEqual(response.text, "ok")
            self.assertEqual(calls, ["bad", "bad", "good"])
            names = [event.get("name") for event in recent_events(config.state_dir, "events", limit=50)]
            self.assertIn(PROVIDER_FAILED, names)
            self.assertIn(ROUTER_FALLBACK, names)
            self.assertIn(PROVIDER_SELECTED, names)
            self.assertIn(CONTEXT_TRUNCATED, names)

    def test_tool_execution_error_records_internal_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(state_dir=Path(tmp) / "state", workspace_dir=Path(tmp))
            request = HubRequest(
                session_id="s",
                route="coding",
                messages=[{"role": "user", "content": "run missing tool"}],
            )
            result = ToolExecutionPipeline(ToolRegistry()).execute(
                ToolCall(name="missing_tool"),
                ToolExecutionContext(config=config, request=request),
            )

            self.assertFalse(result.ok)
            events = recent_events(config.state_dir, "events", limit=10)
            self.assertEqual(events[-1]["name"], TOOL_EXECUTED)
            self.assertEqual(events[-1]["tool"], "missing_tool")
            self.assertFalse(events[-1]["ok"])

    def test_native_stream_interruption_records_started_and_failed_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _routing_config(Path(tmp), ["native"])
            config.agents["native"].supports_streaming = True

            class Provider:
                def __init__(self, agent: AgentConfig) -> None:
                    self.agent = agent

                def complete(self, request: HubRequest) -> ProviderResult:
                    return ProviderResult(text="unused", model=self.agent.model)

                def supports_streaming(self) -> bool:
                    return True

                def stream(self, request: HubRequest):
                    yield StreamChunk(
                        text="part",
                        delta={"content": "part"},
                        model=self.agent.model,
                    )
                    raise ProviderError("stream timed out", retryable=True, error_type="timeout")

            router = AgentRouter(config, provider_factory=Provider)
            stream = router.native_stream(
                HubRequest(
                    session_id="s",
                    route="coding",
                    stream=True,
                    messages=[{"role": "user", "content": "hello"}],
                )
            )

            self.assertIsNotNone(stream)
            iterator = iter(stream.chunks)
            self.assertEqual(next(iterator).text, "part")
            with self.assertRaises(ProviderError):
                next(iterator)

            names = [event.get("name") for event in recent_events(config.state_dir, "events", limit=20)]
            self.assertIn(STREAM_STARTED, names)
            self.assertIn(STREAM_FAILED, names)
            self.assertIn(PROVIDER_FAILED, names)

    def test_provider_score_exposes_token_efficiency_component(self) -> None:
        agent = AgentConfig(
            name="agent",
            provider="openai-compatible",
            model="model",
            base_url="http://127.0.0.1:9999",
        )
        health = ProviderHealth(success_count=2, tokens_in=100, tokens_out=50)
        score = calculate_provider_score(agent, health)

        self.assertGreater(score.token_efficiency, 0)
        self.assertIn("token_efficiency", score.to_dict())

    def test_workflow_extension_points_are_passive_and_serializable(self) -> None:
        extensions = WorkflowExtensionPoints(
            provider_calls=[
                ProviderCallPlan(agent_names=["planner", "reviewer"], role="reviewer", parallel=True)
            ],
            roles=RoleStrategy(assignments={"planner": "planner"}),
            consensus=ConsensusStrategy(name="majority", min_votes=2),
            merge=MergeStrategy(name="ranked"),
        )

        self.assertEqual(extensions.roles.agent_for("planner", ["planner"]), "planner")
        self.assertEqual(extensions.roles.agent_for("reviewer", ["worker"]), "worker")
        data = extensions.to_dict()
        self.assertTrue(data["provider_calls"][0]["parallel"])
        self.assertEqual(data["consensus"]["min_votes"], 2)
        self.assertEqual(data["merge"]["name"], "ranked")


def _routing_config(path: Path, agents: list[str]) -> HubConfig:
    return HubConfig(
        state_dir=path / "state",
        workspace_dir=path,
        approval_mode="auto",
        free_only=False,
        default_route=agents,
        routes=[RouteRule(name="coding", agents=agents)],
        agents={
            name: AgentConfig(
                name=name,
                provider="openai-compatible",
                provider_type="openai-compatible",
                base_url="http://127.0.0.1:9999",
                model=f"{name}-model",
                free=True,
            )
            for name in agents
        },
    )


if __name__ == "__main__":
    unittest.main()
