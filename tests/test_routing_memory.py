from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.core.router import AgentRouter
from agent_hub.core.task_classifier import TaskClassifier
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.routing_memory import (
    RoutingMemoryStore,
    outcome_score,
    pattern_from_classification,
    similarity_score,
)
from agent_hub.server import AgentHubHTTPServer


class RoutingMemoryTests(unittest.TestCase):
    def test_classifier_exposes_workspace_aware_fields(self) -> None:
        request = _request(
            "Edit and refactor src/App.tsx and src/state.ts in React."
        )
        classification = TaskClassifier().classify(request)
        data = classification.to_dict()

        self.assertEqual(data["task_category"], "refactor")
        self.assertEqual(data["language"], "typescript")
        self.assertEqual(data["framework"], "react")
        self.assertEqual(data["complexity"], "high")
        self.assertIn("file_write", data["permission_requirements"])
        self.assertIn(data["expected_cost"], {"medium", "high"})

    def test_memory_persistence_similarity_and_no_prompt_storage_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = RoutingMemoryStore(root)
            agent = AgentConfig(name="good", provider="openai-compatible", model="good-test")
            request = _request("Fix src/app.py and update tests/test_app.py")
            classification = TaskClassifier(root).classify(request)

            store.record_outcome(
                request_id="hub-1",
                request=request,
                classification=classification,
                agent=agent,
                model=agent.model,
                success=True,
                latency_seconds=1.0,
                failover_attempts=0,
                input_tokens=200,
                output_tokens=80,
                estimated_cost_usd=0.001,
                final=True,
            )
            recent = RoutingMemoryStore(root).recent(limit=5)
            signal = RoutingMemoryStore(root).routing_signal(agent, classification)

            self.assertEqual(len(recent), 1)
            self.assertNotIn("prompt", recent[0])
            self.assertEqual(recent[0]["task_type"], classification.task_type)
            self.assertGreater(signal["attempts"], 0)
            self.assertGreater(
                similarity_score(
                    pattern_from_classification(classification),
                    recent[0],
                ),
                0,
            )
            self.assertGreater(
                outcome_score(
                    success=True,
                    latency_seconds=1,
                    fallback_count=0,
                    timeout=False,
                    tool_failure=False,
                    reviewer_pass=True,
                    user_cancellation=False,
                ),
                0.8,
            )

    def test_router_boosts_and_penalizes_models_from_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _router_config(root)
            good = config.agents["good"]
            bad = config.agents["bad"]
            store = RoutingMemoryStore.from_config(config)
            request = _request("Fix src/app.py and update tests/test_app.py")
            classification = TaskClassifier(root).classify(request)
            for index in range(3):
                store.record_outcome(
                    request_id=f"good-{index}",
                    request=request,
                    classification=classification,
                    agent=good,
                    model=good.model,
                    success=True,
                    latency_seconds=1,
                    failover_attempts=0,
                    input_tokens=100,
                    output_tokens=50,
                    estimated_cost_usd=None,
                    final=True,
                )
                store.record_outcome(
                    request_id=f"bad-{index}",
                    request=request,
                    classification=classification,
                    agent=bad,
                    model=bad.model,
                    success=False,
                    latency_seconds=20,
                    failover_attempts=1,
                    input_tokens=100,
                    output_tokens=0,
                    estimated_cost_usd=None,
                    error_type="timeout",
                    final=False,
                )
            calls: list[str] = []
            config.expose_routing_details = True

            response = AgentRouter(
                config,
                provider_factory=lambda agent: _Provider(agent, calls),
            ).route(request)
            decision = response.raw["agent_hub"]["routing_decision"]

            self.assertEqual(response.agent, "good")
            self.assertEqual(calls, ["good"])
            self.assertTrue(decision["memory_adjustments"])
            self.assertGreater(decision["candidate_scores"][0]["memory_adjustment"], 0)
            self.assertIn("fallback_rejections", decision)

    def test_memory_marks_model_teachable_after_deep_workspace_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = RoutingMemoryStore(root)
            agent = AgentConfig(name="good", provider="openai-compatible", model="good-test")
            request = _request("Refactor src/app.py and update the pytest coverage")
            classification = _classification(
                task_type="code_edit",
                language="python",
                framework="pytest",
                repository_profile_id="repo-1",
                repository_project="agent-hub",
            )

            for index in range(12):
                store.record_outcome(
                    request_id=f"workspace-{index}",
                    request=request,
                    classification=classification,
                    agent=agent,
                    model=agent.model,
                    success=True,
                    latency_seconds=1,
                    failover_attempts=0,
                    input_tokens=120,
                    output_tokens=60,
                    estimated_cost_usd=None,
                    final=True,
                )

            rows = store._read_recent(limit=20)
            first = dict(rows[0])
            first["time"] = first["time"] - (5 * 60 * 60)
            _write_jsonl(store.path, [first, *rows[1:]])

            signal = RoutingMemoryStore(root).routing_signal(agent, classification)

            self.assertTrue(signal["teach_ready"]["active"])
            self.assertEqual(signal["teach_ready"]["basis"], "workspace_history")
            self.assertGreater(signal["teach_ready"]["workspace_samples"], 0)
            self.assertGreater(signal["adjustment"], signal["raw_adjustment"])

    def test_memory_marks_model_teachable_after_many_similar_assessments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = RoutingMemoryStore(root)
            agent = AgentConfig(name="good", provider="openai-compatible", model="good-test")
            request = _request("Fix React state handling in src/App.tsx")
            classification = _classification(
                task_type="code_edit",
                language="typescript",
                framework="react",
                repository_profile_id="repo-current",
                repository_project="current",
            )

            for index in range(16):
                store.record_outcome(
                    request_id=f"similar-{index}",
                    request=request,
                    classification=_classification(
                        task_type="code_edit",
                        language="typescript",
                        framework="react",
                        repository_profile_id=f"repo-{index}",
                        repository_project=f"project-{index}",
                    ),
                    agent=agent,
                    model=agent.model,
                    success=True,
                    latency_seconds=1,
                    failover_attempts=0,
                    input_tokens=100,
                    output_tokens=50,
                    estimated_cost_usd=None,
                    final=True,
                )

            signal = RoutingMemoryStore(root).routing_signal(agent, classification)

            self.assertTrue(signal["teach_ready"]["active"])
            self.assertEqual(signal["teach_ready"]["basis"], "similar_assessments")
            self.assertGreaterEqual(signal["teach_ready"]["similar_samples"], 16)
            self.assertIn("teachable", signal["summary"].lower())

    def test_memory_blocks_teaching_from_bad_training_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = RoutingMemoryStore(root)
            agent = AgentConfig(name="bad", provider="openai-compatible", model="bad-test")
            request = _request("Fix React state handling in src/App.tsx")
            classification = _classification(
                task_type="code_edit",
                language="typescript",
                framework="react",
            )

            for index in range(8):
                store.record_outcome(
                    request_id=f"bad-data-{index}",
                    request=request,
                    classification=classification,
                    agent=agent,
                    model=agent.model,
                    success=False,
                    latency_seconds=20,
                    failover_attempts=1,
                    input_tokens=100,
                    output_tokens=0,
                    estimated_cost_usd=None,
                    error_type="timeout",
                    final=True,
                )

            signal = RoutingMemoryStore(root).routing_signal(agent, classification)

            self.assertFalse(signal["teach_ready"]["active"])
            self.assertEqual(signal["teach_ready"]["basis"], "similar_assessments")
            self.assertGreater(signal["teach_ready"]["bad_rate"], 0.25)
            self.assertLess(signal["teach_adjustment"], 0)
            self.assertIn("blocked by bad", signal["teach_ready"]["summary"])

    def test_memory_uses_backup_model_history_when_primary_profiles_are_sparse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = RoutingMemoryStore(root)
            agent = AgentConfig(name="steady", provider="openai-compatible", model="steady-test")
            backup_request = _request("Summarize markdown documentation")
            backup_classification = _classification(
                task_type="documentation",
                task_category="documentation",
                language="markdown",
                framework="none",
                complexity="low",
                risk_level="low",
                repo_size_bucket="small",
                context_size_bucket="small",
                file_types=[".md"],
            )

            for index in range(24):
                store.record_outcome(
                    request_id=f"backup-{index}",
                    request=backup_request,
                    classification=backup_classification,
                    agent=agent,
                    model=agent.model,
                    success=True,
                    latency_seconds=1,
                    failover_attempts=0,
                    input_tokens=80,
                    output_tokens=40,
                    estimated_cost_usd=None,
                    final=True,
                )

            current = _classification(
                task_type="security_sensitive_change",
                task_category="security_sensitive_change",
                language="rust",
                framework="axum",
                complexity="high",
                risk_level="high",
                repo_size_bucket="xlarge",
                context_size_bucket="xlarge",
                file_types=[".rs"],
            )
            signal = RoutingMemoryStore(root).routing_signal(agent, current)

            self.assertTrue(signal["teach_ready"]["active"])
            self.assertEqual(signal["teach_ready"]["basis"], "backup_model_history")
            self.assertTrue(signal["teach_ready"]["backup"]["active"])
            self.assertEqual(signal["attempts"], 0)
            self.assertGreater(signal["adjustment"], 0)

    def test_router_ignores_memory_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _router_config(root)
            config.routing_memory_enabled = False
            store = RoutingMemoryStore(config.state_dir)
            request = _request("Fix src/app.py")
            classification = TaskClassifier(root).classify(request)
            for index in range(3):
                store.record_outcome(
                    request_id=f"good-{index}",
                    request=request,
                    classification=classification,
                    agent=config.agents["good"],
                    model="good-test",
                    success=True,
                    latency_seconds=1,
                    failover_attempts=0,
                    input_tokens=1,
                    output_tokens=1,
                    estimated_cost_usd=None,
                    final=True,
                )

            response = AgentRouter(config, provider_factory=lambda agent: _Provider(agent, [])).route(request)

            self.assertEqual(response.agent, "bad")

    def test_memory_api_stats_recent_decision_and_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _router_config(Path(tmp))
            config.expose_routing_details = True
            server = AgentHubHTTPServer(("127.0.0.1", 0), config)
            server.router.provider_factory = lambda agent: _Provider(agent, [])
            thread = _start(server)
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                response = _post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "messages": [{"role": "user", "content": "Fix src/app.py"}],
                    },
                )
                stats = _get_json(f"{base}/v1/routing-memory/stats")
                recent = _get_json(f"{base}/v1/routing-memory/recent")
                decision = _get_json(f"{base}/v1/routing-decision/{response['id']}")
                reset = _delete_json(f"{base}/v1/routing-memory")
                after = _get_json(f"{base}/v1/routing-memory/stats")
            finally:
                _stop(server, thread)

            self.assertEqual(stats["object"], "agent_hub.routing_memory.stats")
            self.assertGreaterEqual(stats["total_records"], 1)
            self.assertEqual(stats["summary"]["data_state"], "measured_ready")
            self.assertIn("feedback", stats["summary"]["signals_tracked"])
            self.assertIn("self_adjusting", stats)
            self.assertGreaterEqual(stats["self_adjusting"]["profile_count"], 1)
            self.assertEqual(recent["object"], "agent_hub.routing_memory.recent")
            self.assertTrue(decision["found"])
            self.assertEqual(reset["object"], "agent_hub.routing_memory.reset")
            self.assertEqual(after["total_records"], 0)
            self.assertEqual(after["summary"]["data_state"], "baseline_ready")
            self.assertIsNotNone(after["empty_state"])
            self.assertIn("privacy", after["baseline_policy"])


class _Provider:
    def __init__(self, agent: AgentConfig, calls: list[str]) -> None:
        self.agent = agent
        self.calls = calls

    def complete(self, request: HubRequest) -> ProviderResult:
        self.calls.append(self.agent.name)
        return ProviderResult(
            text="ok",
            model=self.agent.model,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            finish_reason="stop",
        )


def _request(text: str) -> HubRequest:
    return HubRequest(session_id="s", messages=[{"role": "user", "content": text}], raw={})


def _classification(**overrides: str) -> dict[str, object]:
    data: dict[str, object] = {
        "task_type": "code_edit",
        "task_category": "code_edit",
        "language": "python",
        "framework": "pytest",
        "complexity": "medium",
        "risk_level": "low",
        "repo_size_bucket": "medium",
        "repository_profile_id": "",
        "repository_project": "",
        "repository_architecture": "",
        "context_size_bucket": "small",
        "file_types": [".py"],
    }
    data.update(overrides)
    return data


def _router_config(root: Path) -> HubConfig:
    return HubConfig(
        state_dir=root / "state",
        workspace_dir=root,
        free_only=False,
        dev_unauthenticated_mode=True,
        local_auth_required=False,
        adaptive_learning_enabled=False,
        automatic_escalation_enabled=False,
        repo_context_enabled=False,
        default_route=["bad", "good"],
        agents={
            "bad": AgentConfig(
                name="bad",
                provider="openai-compatible",
                model="bad-test",
                base_url="http://127.0.0.1:9999",
                coding_score=0.1,
                free=True,
            ),
            "good": AgentConfig(
                name="good",
                provider="openai-compatible",
                model="good-test",
                base_url="http://127.0.0.1:9999",
                coding_score=0.1,
                free=True,
            ),
        },
    )


def _start(server: AgentHubHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _stop(server: AgentHubHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _delete_json(url: str) -> dict:
    request = Request(url, method="DELETE")
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
