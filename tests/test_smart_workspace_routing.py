from __future__ import annotations

import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.core.context_preparation import ContextPreparationService
from agent_hub.core.router import AgentRouter
from agent_hub.core.task_classifier import TaskClassifier
from agent_hub.evaluation import BenchmarkResult, ProviderScoreStore
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.payloads import openai_chat_response, openai_response_response
from agent_hub.tools import create_builtin_registry
from agent_hub.workflows import (
    SafeWorkspaceService,
    WorkflowCancelledError,
    WorkflowEngine,
    WorkflowTimeoutError,
)


class SmartWorkspaceRoutingTests(unittest.TestCase):
    def test_task_classifier_drives_different_routing_modes(self) -> None:
        classifier = TaskClassifier()

        simple = classifier.classify(_request("Explain what a context window is."))
        refactor = classifier.classify(_request("Refactor the whole codebase across app.py and tests/test_app.py."))
        risky = classifier.classify(_request("Edit agent-hub.config.json and run npm install left-pad."))

        self.assertEqual(simple.task_type, "simple_explanation")
        self.assertEqual(simple.routing_mode, "cheapest")
        self.assertEqual(refactor.routing_mode, "long_context")
        self.assertTrue(refactor.repository_context_needed)
        self.assertEqual(risky.task_type, "security_sensitive_change")
        self.assertIn(risky.risk_level, {"high", "critical"})
        self.assertEqual(risky.workflow_hint, "reviewer_permission_gate")

    def test_router_decision_explains_smart_workspace_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _smart_config(Path(tmp))
            router = AgentRouter(config, provider_factory=_OkProvider)

            simple = router.decide(_request("Explain the release process briefly."))
            coding = router.decide(_request("Fix the bug in src/app.py and update tests/test_app.py."))
            large = router.decide(_request("Large repo task: refactor architecture across many modules."))

        self.assertEqual(simple.routing_mode, "cheapest")
        self.assertEqual(simple.selected_agent, "cheap")
        self.assertEqual(coding.routing_mode, "coding")
        self.assertEqual(coding.selected_agent, "coder")
        self.assertEqual(large.routing_mode, "long_context")
        self.assertEqual(large.selected_agent, "long")
        self.assertIn("task_classification", large.to_dict())
        self.assertIn("reason", large.to_dict())

    def test_token_save_routing_hint_offloads_simple_wrapped_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                workspace_dir=root,
                state_dir=root / ".agent-hub" / "state",
                free_only=False,
                enable_load_balancing=True,
                default_route=["free-cloud", "codex-fallback"],
                routes=[RouteRule(name="cloud-agent", agents=["free-cloud", "codex-fallback"])],
                agents={
                    "free-cloud": AgentConfig(
                        name="free-cloud",
                        provider="openai-compatible",
                        provider_type="groq",
                        model="free-qwen",
                        base_url="https://example.invalid/v1",
                        free=True,
                        speed_score=1.0,
                        coding_score=0.2,
                        context_window=128_000,
                    ),
                    "codex-fallback": AgentConfig(
                        name="codex-fallback",
                        provider="openai",
                        provider_type="openai",
                        model="codex-like",
                        free=False,
                        coding_score=1.0,
                        reasoning_score=1.0,
                        supports_tools=True,
                        context_window=128_000,
                    ),
                },
            )
            router = AgentRouter(config, provider_factory=_OkProvider)
            wrapped_task = "\n".join(
                [
                    "Use workspace tools when inspection or edits are useful.",
                    "Use the current file path from context.",
                    "Explain this selected code clearly.",
                ]
            )

            simple = router.decide(
                HubRequest(
                    session_id="s",
                    route="cloud-agent",
                    task=wrapped_task,
                    context="File: app.py\n" + ("def run(): pass\n" * 1000),
                    messages=[{"role": "user", "content": wrapped_task}],
                    raw={"agent_hub": {"classification_text": "Explain this selected code clearly."}},
                )
            )
            coding = router.decide(
                HubRequest(
                    session_id="s",
                    route="cloud-agent",
                    task=wrapped_task,
                    context="File: app.py\n",
                    messages=[{"role": "user", "content": wrapped_task}],
                    raw={"agent_hub": {"classification_text": "Fix the bug in app.py and update tests."}},
                )
            )

        self.assertEqual(simple.routing_mode, "cheapest")
        self.assertEqual(simple.selected_agent, "free-cloud")
        self.assertEqual(coding.routing_mode, "coding")
        self.assertEqual(coding.selected_agent, "codex-fallback")

    def test_cloud_exploration_uses_codex_when_cloud_score_is_not_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _cloud_exploration_config(root)
            store = ProviderScoreStore(config.state_dir)
            store.save_results(
                [
                    BenchmarkResult("free-cloud", "openai-compatible", "free-qwen", "simple_explanation", 0.40, 10, True),
                    BenchmarkResult("free-cloud", "openai-compatible", "free-qwen", "simple_explanation", 0.44, 10, True),
                    BenchmarkResult("free-cloud", "openai-compatible", "free-qwen", "simple_explanation", 0.46, 10, True),
                    BenchmarkResult("codex-fallback", "openai", "codex-like", "simple_explanation", 0.92, 15, True),
                    BenchmarkResult("codex-fallback", "openai", "codex-like", "simple_explanation", 0.94, 15, True),
                    BenchmarkResult("codex-fallback", "openai", "codex-like", "simple_explanation", 0.93, 15, True),
                ]
            )

            decision = AgentRouter(config, provider_factory=_OkProvider).decide(
                HubRequest(
                    session_id="s",
                    route="cloud-agent",
                    messages=[{"role": "user", "content": "Explain this selected code clearly."}],
                    raw={
                        "agent_hub": {
                            "classification_text": "Explain this selected code clearly.",
                            "allow_cloud_exploration": True,
                        }
                    },
                )
            )

        self.assertEqual(decision.routing_mode, "cheapest")
        self.assertEqual(decision.selected_agent, "codex-fallback")

    def test_live_routed_outcomes_update_provider_score_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                workspace_dir=root,
                state_dir=root / ".agent-hub" / "state",
                approval_mode="auto",
                repo_context_enabled=False,
                default_route=["agent"],
                routes=[RouteRule(name="cloud-agent", agents=["agent"])],
                agents={
                    "agent": AgentConfig(
                        name="agent",
                        provider="openai-compatible",
                        model="free-qwen",
                        base_url="https://example.invalid/v1",
                        free=True,
                    )
                },
            )

            AgentRouter(config, provider_factory=_OkProvider).route(
                HubRequest(
                    session_id="s",
                    route="cloud-agent",
                    messages=[{"role": "user", "content": "Explain what a context window is."}],
                    raw={"provider_approval_granted": True},
                )
            )
            scores = ProviderScoreStore(config.state_dir).load()

        self.assertIn("agent", scores)
        self.assertIn("simple_explanation", scores["agent"]["task_scores"])
        self.assertGreater(scores["agent"]["sample_count"], 0)

    def test_router_decide_does_not_prepare_context_or_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
            config = _smart_config(root)
            router = AgentRouter(config, provider_factory=_OkProvider)
            request = _request("Read app.py and explain the bug.")

            router.decide(request)

            self.assertNotIn("agent_hub_tools", request.raw)
            self.assertFalse(any(message.get("agent_hub_repo_context") for message in request.messages))

    def test_context_preparation_boundary_adds_tools_outside_router_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _smart_config(Path(tmp))
            registry = create_builtin_registry(config)
            service = ContextPreparationService(
                config,
                tool_registry=registry,
                has_tool_capable_candidate=lambda request: True,
            )
            prepared = service.prepare(_request("Read app.py and run tests."))

        self.assertIn("agent_hub_tools", prepared.raw)
        self.assertTrue(prepared.raw["agent_hub"]["auto_execute_tools"])

    def test_api_compatibility_does_not_leak_internal_metadata_by_default(self) -> None:
        response = _hub_response_with_internal_metadata()

        chat = openai_chat_response(response)
        responses = openai_response_response(response)

        self.assertNotIn("agent_hub", chat)
        self.assertNotIn("workflow", str(chat))
        self.assertNotIn("citations", chat)
        self.assertNotIn("agent_hub", responses)
        self.assertNotIn("workflow", str(responses))

    def test_workspace_service_dry_run_file_action_does_not_touch_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            config = HubConfig(workspace_dir=root, state_dir=root / "state", approval_mode="auto")
            service = SafeWorkspaceService(config)

            result = service.apply_file_action(
                HubRequest(session_id="wf", messages=[]),
                "replace_in_file",
                {"path": "app.py", "old": "VALUE = 1", "new": "VALUE = 2", "dry_run": True},
                dry_run=True,
            )

            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 1\n")
            self.assertIn("VALUE = 2", result.result["patch_preview"])

    def test_workflow_stage_timeout_and_cancellation_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _workflow_config(Path(tmp))
            engine = WorkflowEngine(config)
            engine.router.provider_factory = _SlowProvider

            with self.assertRaises(WorkflowTimeoutError):
                engine.execute(
                    "code",
                    _request("edit app.py"),
                    stage_timeout_seconds=0.01,
                )

            with self.assertRaises(WorkflowCancelledError):
                engine.execute(
                    "code",
                    HubRequest(
                        session_id="wf",
                        messages=[{"role": "user", "content": "edit app.py"}],
                        raw={"agent_hub": {"workflow_cancelled": True}},
                    ),
                )

    def test_concurrent_router_requests_update_health_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _workflow_config(Path(tmp))
            router = AgentRouter(config, provider_factory=_OkProvider)
            requests = [_request(f"hello {index}") for index in range(12)]

            with ThreadPoolExecutor(max_workers=6) as executor:
                responses = list(executor.map(router.route, requests))

            self.assertEqual(len(responses), 12)
            health = router.health_snapshot()["agent"]
            self.assertEqual(health["success_count"], 12)


class _OkProvider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        return ProviderResult(
            text="ok",
            model=self.agent.model,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            finish_reason="stop",
        )


class _SlowProvider(_OkProvider):
    def complete(self, request: HubRequest) -> ProviderResult:
        time.sleep(0.05)
        return super().complete(request)


def _request(text: str) -> HubRequest:
    return HubRequest(session_id="s", messages=[{"role": "user", "content": text}], raw={})


def _smart_config(root: Path) -> HubConfig:
    return HubConfig(
        workspace_dir=root,
        state_dir=root / ".agent-hub" / "state",
        free_only=False,
        repo_context_enabled=False,
        default_route=["cheap", "coder", "long"],
        routes=[RouteRule(name="coding", agents=["cheap", "coder", "long"])],
        agents={
            "cheap": AgentConfig(
                name="cheap",
                provider="openai-compatible",
                model="cheap-fast",
                base_url="http://127.0.0.1:9999",
                free=True,
                speed_score=1.0,
                context_window=8_000,
            ),
            "coder": AgentConfig(
                name="coder",
                provider="openai-compatible",
                model="coder",
                base_url="http://127.0.0.1:9999",
                free=False,
                coding_score=1.0,
                supports_tools=True,
                supports_function_calling=True,
                context_window=32_000,
            ),
            "long": AgentConfig(
                name="long",
                provider="openai-compatible",
                model="long-context",
                base_url="http://127.0.0.1:9999",
                free=False,
                coding_score=0.5,
                context_window=256_000,
            ),
        },
    )


def _cloud_exploration_config(root: Path) -> HubConfig:
    return HubConfig(
        workspace_dir=root,
        state_dir=root / ".agent-hub" / "state",
        free_only=False,
        enable_load_balancing=True,
        repo_context_enabled=False,
        routing={
            "simple_cloud_exploration_enabled": True,
            "simple_cloud_exploration_rate": 1.0,
            "simple_cloud_min_relative_score": 0.82,
            "simple_cloud_min_samples": 3,
        },
        default_route=["free-cloud", "codex-fallback"],
        routes=[RouteRule(name="cloud-agent", agents=["free-cloud", "codex-fallback"])],
        agents={
            "free-cloud": AgentConfig(
                name="free-cloud",
                provider="openai-compatible",
                provider_type="groq",
                model="free-qwen",
                base_url="https://example.invalid/v1",
                free=True,
                speed_score=1.0,
                coding_score=0.2,
                context_window=128_000,
            ),
            "codex-fallback": AgentConfig(
                name="codex-fallback",
                provider="openai",
                provider_type="openai",
                model="codex-like",
                free=False,
                coding_score=1.0,
                reasoning_score=1.0,
                supports_tools=True,
                context_window=128_000,
            ),
        },
    )


def _workflow_config(root: Path) -> HubConfig:
    return HubConfig(
        workspace_dir=root,
        state_dir=root / "state",
        free_only=False,
        repo_context_enabled=False,
        approval_mode="auto",
        default_route=["agent"],
        routes=[RouteRule(name="coding", agents=["agent"])],
        agents={
            "agent": AgentConfig(
                name="agent",
                provider="openai-compatible",
                model="workflow-model",
                base_url="http://127.0.0.1:9999",
                free=True,
            )
        },
    )


def _hub_response_with_internal_metadata():
    from agent_hub.models import HubResponse

    return HubResponse(
        request_id="hub-1",
        session_id="s",
        agent="agent",
        provider="openai-compatible",
        model="model",
        text="hello",
        raw={
            "agent_hub": {
                "workflow": {"secret": "internal"},
                "workflow_stages": [{"stage": "plan"}],
                "routing_decision": {"reason": "selected"},
            }
        },
        citations=["internal-citation"],
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    )


if __name__ == "__main__":
    unittest.main()
