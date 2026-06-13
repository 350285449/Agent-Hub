from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.boost import build_boost_plan, boost_policy, normalize_boost_mode
from agent_hub.config import AgentConfig, HubConfig, config_from_dict, config_to_dict
from agent_hub.core.router import AgentRouter
from agent_hub.core.task_classifier import TaskClassifier
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.optimizer import (
    ContextLevel,
    ContextPlanner,
    apply_retry_to_plan,
    optimization_plan_from_dict,
    trace_from_plan,
)
from agent_hub.output_validator import validate_output
from agent_hub.payloads import request_from_openai_chat
from agent_hub.repository import RepositoryIndexer, RepoContextSelector
from agent_hub.token_optimizer import ContextCache, TokenOptimizer


class BoostOptimizerTests(unittest.TestCase):
    def test_boost_mode_round_trips_config_and_aliases(self) -> None:
        config = config_from_dict({"boost_mode": "Save Tokens", "agents": []})

        self.assertEqual(config.boost_mode, "save_tokens")
        self.assertEqual(config_to_dict(config)["boost_mode"], "save_tokens")
        self.assertEqual(normalize_boost_mode("Big Refactor"), "big_refactor")
        self.assertEqual(normalize_boost_mode("another level"), "turbo_boost")
        self.assertEqual(normalize_boost_mode("Boost + Save Tokens"), "save_tokens")
        self.assertEqual(normalize_boost_mode("Turbo Boost!"), "turbo_boost")
        self.assertEqual(boost_policy("local first").routing_mode, "local_private")

    def test_boost_mode_runtime_selector_options(self) -> None:
        config = HubConfig()

        self.assertEqual(config.boost_mode_label, "Balanced")
        self.assertIn("Best Code", [option["label"] for option in config.boost_mode_options])
        self.assertEqual(config.set_boost_mode("Save Tokens"), "save_tokens")
        self.assertEqual(config.boost_mode_label, "Save Tokens")
        self.assertEqual(config.context_mode, "minimal")
        self.assertEqual(config.set_boost_mode("Best Code"), "best_code")
        self.assertEqual(config.context_mode, "deep")
        self.assertEqual(config.set_boost_mode("Boost"), "turbo_boost")
        self.assertEqual(config.boost_mode_label, "Turbo Boost")

    def test_turbo_boost_expands_complex_feature_context_and_retry_policy(self) -> None:
        plan = build_boost_plan(
            task_type="coding",
            task_category="feature",
            text=(
                "Build a multi-file integration feature with backwards compatible API behavior, "
                "UI updates, and related tests."
            ),
            boost_mode="Boost",
            estimated_input_tokens=15_000,
            repo_size_bucket="large",
            file_count=5,
        )

        self.assertEqual(plan.boost_mode, "turbo_boost")
        self.assertEqual(plan.model_policy, "adaptive_quality_speed")
        self.assertGreaterEqual(plan.repo_max_files, 12)
        self.assertGreater(plan.quality_weight, plan.cost_weight)
        self.assertGreaterEqual(plan.retry_policy.max_retries, 3)
        self.assertEqual(plan.retry_policy.strategy_for("missing context"), "expand_context")
        self.assertIn("adaptive_evidence_ladder", plan.algorithms)
        self.assertIn("complexity_aware_context_expansion", plan.algorithms)
        self.assertIn("coding", plan.preferred_models)

    def test_boost_profile_recognizes_migration_and_build_fix_tasks(self) -> None:
        migration = build_boost_plan(
            task_type="coding",
            task_category="maintenance",
            text="Migrate the auth package after a breaking change and update all call sites.",
            boost_mode="balanced",
            file_count=6,
        )
        build_fix = build_boost_plan(
            task_type="debug",
            task_category="ci",
            text="Build failed with a TypeScript error in the route config.",
            boost_mode="fast_fix",
            file_count=1,
        )

        self.assertEqual(migration.task_type, "migration")
        self.assertIn("migration_impact_graph", migration.algorithms)
        self.assertGreater(migration.risk_weight, 1.0)
        self.assertEqual(build_fix.task_type, "build_fix")
        self.assertIn("build_log_anchor", build_fix.algorithms)
        self.assertGreater(build_fix.speed_weight, 1.2)

    def test_adaptive_boost_plan_tightens_context_under_token_pressure(self) -> None:
        plan = build_boost_plan(
            task_type="documentation",
            task_category="documentation",
            text="Update docs and explain the API briefly.",
            boost_mode="save_tokens",
            estimated_input_tokens=22_000,
            repo_size_bucket="large",
        )
        risky = build_boost_plan(
            task_type="security_sensitive_change",
            task_category="security_sensitive_operation",
            text="Fix auth token validation in middleware.",
            boost_mode="best_code",
            risk_level="high",
            file_count=2,
        )

        self.assertLess(plan.repo_max_chars, boost_policy("save_tokens").repo_max_chars)
        self.assertLessEqual(plan.repo_max_files, 6)
        self.assertLess(plan.target_context_ratio, 0.4)
        self.assertGreater(plan.cost_weight, plan.quality_weight)
        self.assertIn("token_pressure_scaling", plan.algorithms)
        self.assertGreater(risky.quality_weight, risky.cost_weight)
        self.assertIn("risk_guarded_escalation", risky.algorithms)

    def test_boost_plan_exposes_optimizer_contract(self) -> None:
        plan = build_boost_plan(
            task_type="debug",
            task_category="debugging",
            text="Fix src/app.py failing test",
            boost_mode="fast_fix",
            file_count=1,
        )
        payload = plan.to_dict()

        self.assertEqual(payload["object"], "agent_hub.optimization_plan")
        self.assertEqual(payload["boost_mode"], "fast_fix")
        self.assertIn("token_budget", payload)
        self.assertIn("retry_policy", payload)
        self.assertIn("validation_gates", payload)
        self.assertIn("free", payload["preferred_models"])

    def test_retry_policy_modifies_existing_plan(self) -> None:
        plan = build_boost_plan(
            task_type="debug",
            task_category="debugging",
            text="Fix src/app.py with missing context",
            boost_mode="save_tokens",
        )

        retry = apply_retry_to_plan(
            plan,
            reason="missing context for referenced helper",
            attempt=1,
        )

        self.assertGreater(retry.repo_max_files, plan.repo_max_files)
        self.assertGreater(retry.target_context_ratio, plan.target_context_ratio)
        self.assertIn("plan_based_retry", retry.algorithms)
        self.assertEqual(retry.context_policy, "expanded_context")

    def test_boost_plan_normalizes_token_targets_and_serialized_limits(self) -> None:
        tiny = build_boost_plan(
            task_type="documentation",
            task_category="documentation",
            text="Explain the setup briefly.",
            boost_mode="save_tokens",
        )
        self.assertLessEqual(tiny.token_budget.target_context_tokens, tiny.token_budget.max_context_tokens)

        payload = tiny.to_dict()
        payload.update(
            {
                "repo_max_files": -4,
                "repo_max_chars": 100,
                "full_files": 99,
                "compressed_files": 99,
                "map_files": 99,
                "target_context_ratio": 2.5,
                "compression_aggression": 3.0,
                "quality_weight": 9.0,
                "retry_budget": -2,
            }
        )
        payload["token_budget"] = {
            **payload["token_budget"],
            "max_context_tokens": 120,
            "target_context_tokens": 10_000,
        }

        restored = optimization_plan_from_dict(payload)

        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertGreaterEqual(restored.repo_max_files, 1)
        self.assertGreaterEqual(restored.repo_max_chars, 1_000)
        self.assertLessEqual(restored.full_files + restored.compressed_files + restored.map_files, restored.repo_max_files)
        self.assertLessEqual(restored.token_budget.target_context_tokens, restored.token_budget.max_context_tokens)
        self.assertLessEqual(restored.compression_aggression, 0.92)
        self.assertLessEqual(restored.quality_weight, 1.7)
        self.assertEqual(restored.retry_budget, 0)

    def test_retry_policy_keeps_context_bucket_invariants(self) -> None:
        plan = build_boost_plan(
            task_type="debug",
            task_category="debugging",
            text="Fix src/app.py",
            boost_mode="save_tokens",
            file_count=1,
        )

        retry = apply_retry_to_plan(plan, reason="low confidence", strategy="add_full_files")

        self.assertLessEqual(retry.full_files + retry.compressed_files + retry.map_files, retry.repo_max_files)
        self.assertGreaterEqual(retry.repo_max_files, 1)

    def test_task_classifier_exposes_optimizer_policy_without_breaking_route_type(self) -> None:
        classification = TaskClassifier().classify(
            HubRequest(
                session_id="s",
                messages=[{"role": "user", "content": "Fix the failing parser test in src/router.py."}],
            )
        )
        data = classification.to_dict()

        self.assertEqual(classification.task_type, "debug")
        self.assertEqual(data["optimization_policy"]["task_type"], "bug_fix")
        self.assertEqual(data["context_policy"], "focused_files")
        self.assertEqual(data["model_policy"], "cheap_first")
        self.assertEqual(data["validation_policy"], "run_tests")

    def test_token_optimizer_deduplicates_and_extractively_compacts_messages(self) -> None:
        repeated = "same diagnostic line\n" * 120
        noisy = "\n".join(["INFO repeated repeated repeated"] * 180 + ["ERROR auth token failed"])
        messages = [
            {"role": "user", "content": repeated},
            {"role": "assistant", "content": noisy},
            {"role": "user", "content": repeated},
            {"role": "user", "content": "Fix the auth token failure."},
        ]

        result = TokenOptimizer().optimize(messages, max_context_tokens=1_000)
        warning_text = " ".join(result.warnings)

        self.assertLess(result.final_tokens, result.original_tokens)
        self.assertIn("deduplicated_messages", warning_text)
        self.assertIn("extractive_message_compaction", warning_text)
        self.assertIn("ERROR auth token failed", "\n".join(str(message.get("content")) for message in result.messages))

    def test_token_optimizer_targets_semantic_duplicates_before_hard_limit(self) -> None:
        base_log = "\n".join(
            f"WARNING: src/auth.py:{line}: token cache lookup repeated stale result"
            for line in range(180)
        )
        messages = [
            {"role": "assistant", "content": f"Tool result run {run}\n{base_log}\nINFO run={run}"}
            for run in range(6)
        ]
        messages.append({"role": "user", "content": "Fix src/auth.py and preserve ERROR auth token failed."})

        result = TokenOptimizer().optimize(
            messages,
            max_context_tokens=20_000,
            target_context_tokens=1_600,
        )
        warning_text = " ".join(result.warnings)

        self.assertTrue(result.target_reached)
        self.assertLessEqual(result.final_tokens, 1_600)
        self.assertLess(result.final_tokens, result.original_tokens * 0.35)
        self.assertIn("semantic_delta_compaction", warning_text)
        self.assertIn("extractive_message_compaction", warning_text)
        self.assertIn("ERROR auth token failed", "\n".join(str(message.get("content")) for message in result.messages))

    def test_token_optimizer_reuses_cached_compacted_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = ContextCache(Path(tmp) / "context-cache.json", enabled=True, max_entries=4)
            repeated = "\n".join(
                f"WARNING: src/cache.py:{line}: repeated token budget warning"
                for line in range(220)
            )
            messages = [
                {"role": "assistant", "content": f"Tool result run {run}\n{repeated}\nINFO run={run}"}
                for run in range(5)
            ]
            messages.append({"role": "user", "content": "Fix src/cache.py token budget warnings."})
            optimizer = TokenOptimizer(cache=cache)

            first = optimizer.optimize(messages, max_context_tokens=20_000, target_context_tokens=1_200)
            second = optimizer.optimize(messages, max_context_tokens=20_000, target_context_tokens=1_200)

        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(second.final_tokens, first.final_tokens)
        self.assertEqual(second.messages, first.messages)
        self.assertIn("context_cache_reused", second.warnings)

    def test_token_optimizer_mmr_budget_preserves_query_evidence(self) -> None:
        unrelated_template = "\n".join(
            f"analytics ledger shard row {row} metric={row * 17} unrelated payment status ok"
            for row in range(180)
        )
        relevant = "\n".join(
            [
                "src/auth.py validate_token tenant scoped feature flags",
                "token cache lookup returns stale tenant result",
                "assert tenant_flags.token_cache_enabled is True",
            ]
            * 70
        )
        messages = [
            {"role": "assistant", "content": unrelated_template.replace("ledger", f"ledger_{run}")}
            for run in range(8)
        ]
        messages.insert(2, {"role": "assistant", "content": relevant})
        messages.extend(
            [
                {"role": "assistant", "content": "Latest state: auth tests are the active validation target."},
                {"role": "assistant", "content": "Next action should stay scoped to token cache handling."},
                {
                    "role": "user",
                    "content": (
                        "Fix src/auth.py token cache stale tenant scoped feature flags. "
                        "Preserve the validation assertion."
                    ),
                },
            ]
        )

        result = TokenOptimizer().optimize(
            messages,
            max_context_tokens=24_000,
            target_context_tokens=900,
        )
        text = "\n".join(str(message.get("content")) for message in result.messages)
        warning_text = " ".join(result.warnings)

        self.assertTrue(result.target_reached)
        self.assertLessEqual(result.final_tokens, 900)
        self.assertGreaterEqual(result.saved_percent, 85.0)
        self.assertIn("budgeted_relevance_mmr", warning_text)
        self.assertIn("src/auth.py", text)
        self.assertIn("tenant scoped feature flags", text)
        self.assertNotIn("ledger_7", text)

    def test_repository_context_ranks_files_and_assigns_context_levels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "router.py").write_text(
                "\n".join(
                    [
                        "import json",
                        "class Router:",
                        "    def route(self, value):",
                        "        return json.loads(value)",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "tests" / "test_router.py").write_text(
                "from src.router import Router\n\ndef test_route():\n    assert Router().route('{}') == {}\n",
                encoding="utf-8",
            )
            (root / "docs.md").write_text("old docs\n", encoding="utf-8")
            index = RepositoryIndexer(root).index()

            selection = RepoContextSelector(index).select(
                'Traceback\n  File "src/router.py", line 3\nFix Router.route and tests/test_router.py',
                max_files=3,
                max_chars=4_000,
                full_files=1,
                compressed_files=1,
                map_files=1,
            )
            payload = selection.to_dict()

        self.assertEqual(payload["selected_files"][0], "src/router.py")
        self.assertIn("tests/test_router.py", payload["selected_files"])
        self.assertEqual(payload["context_levels"]["src/router.py"], "Full")
        self.assertGreaterEqual(payload["tokens_saved"], 0)
        self.assertIn("Matched", payload["reason"])
        self.assertIn("context_files", payload)
        self.assertIn("FULL", payload["context_level_counts"])

    def test_context_planner_creates_first_class_context_files_and_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "app.py").write_text("def fix_me():\n    return 1\n", encoding="utf-8")
            (root / "tests" / "test_app.py").write_text(
                "from src.app import fix_me\n\ndef test_fix_me():\n    assert fix_me() == 2\n",
                encoding="utf-8",
            )
            (root / "README.md").write_text("project docs\n", encoding="utf-8")
            index = RepositoryIndexer(root).index()

            context_plan = ContextPlanner(index).plan(
                "Fix src/app.py and related tests",
                max_files=2,
                full_files=1,
                compressed_files=0,
                map_files=1,
            )
            plan = build_boost_plan(
                task_type="debug",
                task_category="debugging",
                text="Fix src/app.py and related tests",
                boost_mode="balanced",
            ).with_context_plan(context_plan)
            trace = trace_from_plan(plan)

        levels = {item.path: item.level for item in context_plan.context_files}
        self.assertEqual(levels["src/app.py"], ContextLevel.FULL)
        self.assertIn("tests/test_app.py", context_plan.selected_files)
        self.assertIn("OMITTED", context_plan.level_counts())
        self.assertIn("src/app.py", plan.selected_files)
        self.assertEqual(trace.selected_files, len(plan.selected_files))

    def test_trace_distinguishes_estimated_and_actual_token_savings(self) -> None:
        plan = build_boost_plan(
            task_type="debug",
            task_category="debugging",
            text="Fix src/app.py",
            boost_mode="balanced",
        )
        trace = trace_from_plan(
            plan,
            context_usage={
                "original_input_tokens": 10_000,
                "optimized_context_tokens": 4_000,
            },
            actual_usage={"prompt_tokens": 4_500, "completion_tokens": 100},
            estimated_cost_saved_usd=0.0123,
            actual_cost_saved_usd=0.011,
            plan_diff={"summary": "Attempt 1 -> Attempt 2"},
        )
        payload = trace.to_dict()

        self.assertEqual(payload["estimated_tokens_saved"], 6_000)
        self.assertEqual(payload["actual_provider_input_tokens"], 4_500)
        self.assertEqual(payload["actual_input_tokens_saved"], 5_500)
        self.assertEqual(payload["token_accounting_source"], "actual_provider_usage")
        self.assertEqual(payload["actual_cost_saved_usd"], 0.011)
        self.assertEqual(payload["plan_diff"]["summary"], "Attempt 1 -> Attempt 2")

    def test_repository_context_diversifies_and_focuses_compressed_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "auth.py").write_text(
                "\n".join(
                    [
                        "class AuthService:",
                        "    def login(self, token):",
                        "        # login failure happens when token cache expires",
                        "        return token == 'ok'",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "src" / "auth_cache.py").write_text(
                "class AuthCache:\n    def get(self):\n        return None\n",
                encoding="utf-8",
            )
            (root / "tests" / "test_auth.py").write_text(
                "from src.auth import AuthService\n\ndef test_login_failure():\n    assert AuthService().login('bad') is False\n",
                encoding="utf-8",
            )
            index = RepositoryIndexer(root).index()

            selection = RepoContextSelector(index).select(
                "Fix login failure in src/auth.py and preserve auth tests.",
                max_files=3,
                max_chars=1_800,
                full_files=0,
                compressed_files=3,
                map_files=0,
                compression_aggression=0.7,
            )
            payload = selection.to_dict()

        self.assertIn("tests/test_auth.py", payload["selected_files"])
        summaries = "\n".join(payload["summaries"].values())
        self.assertIn("login failure", summaries)

    def test_output_validator_reports_quality_and_retry_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            result = validate_output(
                request=HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "Fix src/app.py"}],
                ),
                response_text="Fix src/app.py by changing VALUE and adding a test.",
                workspace_dir=root,
                selected_files=["src/app.py"],
                token_usage={"estimated_input_tokens": 120, "max_context_tokens": 100},
            )

        self.assertFalse(result.passed)
        self.assertTrue(result.should_retry)
        self.assertEqual(result.retry_strategy, "compress_prompt")
        self.assertEqual(result.checks["token_budget"], "exceeded")

    def test_output_validator_applies_patch_in_temp_workspace_and_checks_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            patch = """```diff
diff --git a/src/app.py b/src/app.py
index 35d163b..03c7151 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
```"""

            result = validate_output(
                request=HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "Fix src/app.py"}],
                ),
                response_text=patch,
                workspace_dir=root,
                selected_files=["src/app.py"],
                validation_policy="strict_quality_checks",
                task_type="bug_fix",
            )

        self.assertTrue(result.passed)
        self.assertEqual(result.checks["patch_applies"], "yes")
        self.assertEqual(result.checks["workspace_patch_validation"]["status"], "passed")
        self.assertEqual(result.checks["workspace_patch_validation"]["patch_applies"], "yes")
        self.assertEqual(result.checks["syntax_valid"], "passed")

    def test_output_validator_rejects_patch_with_syntax_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
            patch = """```diff
diff --git a/src/app.py b/src/app.py
index 867a3ee..b77d49d 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
-def ok():
-    return 1
+def broken(:
+    return 1
```"""

            result = validate_output(
                request=HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "Fix src/app.py"}],
                ),
                response_text=patch,
                workspace_dir=root,
                selected_files=["src/app.py"],
                validation_policy="strict_quality_checks",
                task_type="bug_fix",
            )

        self.assertFalse(result.passed)
        self.assertEqual(result.checks["workspace_patch_validation"]["status"], "failed")
        self.assertEqual(result.checks["workspace_patch_validation"]["patch_applies"], "yes")
        self.assertEqual(result.checks["syntax_valid"], "failed")
        self.assertTrue(any("syntax check failed" in issue for issue in result.issues))

    def test_router_boost_mode_and_efficiency_scorecards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                workspace_dir=root,
                state_dir=root / "state",
                free_only=False,
                repo_context_enabled=False,
                boost_mode="balanced",
                default_route=["fast", "quality"],
                agents={
                    "fast": AgentConfig(
                        name="fast",
                        provider="openai-compatible",
                        model="fast",
                        base_url="http://127.0.0.1:9999",
                        free=True,
                        speed_score=1.0,
                        coding_score=0.4,
                        context_window=32_000,
                    ),
                    "quality": AgentConfig(
                        name="quality",
                        provider="openai",
                        model="quality",
                        free=False,
                        coding_score=1.0,
                        reasoning_score=1.0,
                        context_window=128_000,
                    ),
                },
            )
            router = AgentRouter(config, provider_factory=_OkProvider)
            decision = router.decide(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "Fix the small bug in src/app.py fast."}],
                    raw={"agent_hub": {"boost_mode": "fast_fix"}},
                )
            )

        self.assertEqual(decision.boost_mode, "fast_fix")
        self.assertEqual(decision.routing_mode, "fastest")
        self.assertIn("boost_plan", decision.to_dict())
        self.assertIn("anchored_bug_context", decision.boost_plan["algorithms"])
        self.assertIn("route_efficiency", decision.candidate_scores[0])
        self.assertIn("task_policy", decision.to_dict())

    def test_compatible_chat_inherits_config_boost_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                workspace_dir=root,
                state_dir=root / "state",
                free_only=False,
                repo_context_enabled=False,
                boost_mode="save_tokens",
                default_route=["cheap"],
                agents={
                    "cheap": AgentConfig(
                        name="cheap",
                        provider="openai-compatible",
                        model="cheap-model",
                        base_url="http://127.0.0.1:9999",
                        free=True,
                        context_window=32_000,
                    ),
                },
            )
            request = request_from_openai_chat(
                {
                    "model": "agent-hub-coding",
                    "messages": [{"role": "user", "content": "Summarize this file."}],
                }
            )
            request.route = None
            decision = AgentRouter(config, provider_factory=_OkProvider).decide(request)

        self.assertEqual(request.api_shape, "openai-chat")
        self.assertEqual(decision.boost_mode, "save_tokens")
        self.assertEqual(decision.routing_mode, "cheapest")

    def test_efficiency_routing_beats_base_model_with_less_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                workspace_dir=root,
                state_dir=root / "state",
                free_only=False,
                repo_context_enabled=False,
                boost_mode="save_tokens",
                default_route=["base-codex", "efficient-free"],
                agents={
                    "base-codex": AgentConfig(
                        name="base-codex",
                        provider="openai",
                        model="codex-base",
                        free=False,
                        coding_score=0.92,
                        reasoning_score=0.92,
                        speed_score=0.45,
                        context_window=128_000,
                        max_tokens=1_200,
                        cost_per_million_input=5.0,
                        cost_per_million_output=15.0,
                    ),
                    "efficient-free": AgentConfig(
                        name="efficient-free",
                        provider="openai-compatible",
                        provider_type="groq",
                        model="qwen-free",
                        base_url="https://example.invalid/v1",
                        free=True,
                        coding_score=0.88,
                        reasoning_score=0.88,
                        speed_score=0.9,
                        context_window=64_000,
                        max_tokens=320,
                        cost_per_million_input=0.0,
                        cost_per_million_output=0.0,
                    ),
                },
            )
            decision = AgentRouter(config, provider_factory=_OkProvider).decide(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "Explain this helper and suggest one small cleanup."}],
                )
            )

        self.assertEqual(decision.selected_agent, "efficient-free")
        selected = decision.candidate_scores[0]
        comparison = selected["route_efficiency"]["base_model_comparison"]
        self.assertEqual(comparison["baseline_agent"], "base-codex")
        self.assertTrue(comparison["beats_base_model_for_less_tokens"])
        self.assertGreater(comparison["estimated_token_savings"], 0)
        self.assertGreater(comparison["routing_adjustment"], 0)
        self.assertLess(selected["estimated_output_tokens"], 1_200)

    def test_router_applies_boost_plan_target_to_provider_context(self) -> None:
        _CaptureProvider.last_request = None
        base_log = "\n".join(
            f"WARNING: src/cache.py:{line}: repeated cache miss while resolving token budget"
            for line in range(180)
        )
        messages = [
            {"role": "assistant", "content": f"Tool result run {run}\n{base_log}\nINFO run={run}"}
            for run in range(8)
        ]
        messages.append({"role": "user", "content": "Fix token budget routing in src/cache.py."})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                workspace_dir=root,
                state_dir=root / "state",
                free_only=False,
                repo_context_enabled=False,
                boost_mode="save_tokens",
                default_route=["cheap"],
                agents={
                    "cheap": AgentConfig(
                        name="cheap",
                        provider="openai-compatible",
                        model="cheap",
                        base_url="http://127.0.0.1:9999",
                        free=True,
                        context_window=40_000,
                    ),
                },
            )
            response = AgentRouter(config, provider_factory=_CaptureProvider).route(
                HubRequest(session_id="s", messages=messages)
            )

        self.assertEqual(response.agent, "cheap")
        self.assertIsNotNone(_CaptureProvider.last_request)
        raw = _CaptureProvider.last_request.raw if _CaptureProvider.last_request is not None else {}
        usage = raw["agent_hub"]["context_usage"]
        self.assertEqual(raw["agent_hub"]["optimization_plan"]["object"], "agent_hub.optimization_plan")
        self.assertEqual(raw["agent_hub"]["optimization_trace"]["object"], "agent_hub.optimization_trace")
        self.assertIn("retry_policy", raw["agent_hub"]["optimization_plan"])
        self.assertLess(usage["target_context_tokens"], usage["max_context_tokens"])
        self.assertTrue(usage["target_context_reached"])
        self.assertLessEqual(usage["estimated_input_tokens"], usage["target_context_tokens"])
        self.assertGreaterEqual(usage["saved_percent"], 40.0)
        self.assertIn("semantic_delta_compaction", " ".join(usage["warnings"]))
        self.assertEqual(response.raw["agent_hub"]["optimization_trace"]["actual_provider_input_tokens"], 600)
        self.assertEqual(response.raw["agent_hub"]["optimization_trace"]["token_accounting_source"], "actual_provider_usage")

    def test_cooperative_codex_boost_keeps_codex_final_with_free_digest(self) -> None:
        _CooperativeProvider.calls = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = HubConfig(
                workspace_dir=root,
                state_dir=root / "state",
                free_only=False,
                repo_context_enabled=False,
                boost_mode="save_tokens",
                approval_mode="auto",
                default_route=["free-helper", "codex-cli"],
                agents={
                    "free-helper": AgentConfig(
                        name="free-helper",
                        provider="openai-compatible",
                        provider_type="groq",
                        model="free-qwen",
                        base_url="http://127.0.0.1:9999",
                        free=True,
                        enabled=True,
                        coding_score=0.95,
                        reasoning_score=0.9,
                        speed_score=0.8,
                        context_window=64_000,
                        supports_tools=True,
                    ),
                    "codex-cli": AgentConfig(
                        name="codex-cli",
                        provider="codex-cli",
                        provider_type="codex-cli",
                        model="gpt-5.5",
                        free=False,
                        enabled=True,
                        coding_score=0.92,
                        reasoning_score=0.92,
                        speed_score=0.5,
                        context_window=400_000,
                    ),
                },
            )
            config.routing.update(
                {
                    "cooperative_codex_mode": True,
                    "cooperative_codex_min_confidence": 0.5,
                    "cooperative_codex_max_productivity_loss": 0.3,
                    "free_first": False,
                }
            )
            response = AgentRouter(config, provider_factory=_CooperativeProvider).route(
                HubRequest(
                    session_id="s",
                    preferred_agent="codex-cli",
                    messages=[
                        {"role": "user", "content": "Explain the cache token budget code in src/cache.py."}
                    ],
                    raw={"agent_hub": {"boost_mode": "save_tokens", "cooperative_codex": True}},
                )
            )

        self.assertEqual(response.agent, "codex-cli")
        self.assertEqual([agent for agent, _request in _CooperativeProvider.calls], ["free-helper", "codex-cli"])
        final_request = _CooperativeProvider.calls[-1][1]
        self.assertTrue(
            any(message.get("agent_hub_cooperative_codex_digest") for message in final_request.messages)
        )
        final_hub = final_request.raw["agent_hub"]
        cooperative = final_hub["cooperative_codex"]
        self.assertTrue(cooperative["active"])
        self.assertEqual(cooperative["worker_agent"], "free-helper")
        self.assertEqual(cooperative["paid_final_agent"], "codex-cli")
        self.assertEqual(cooperative["roles"]["paid_model"], "final_reasoning_and_action")
        self.assertTrue(final_hub["context_usage"]["cooperative_codex"]["active"])
        self.assertEqual(response.raw["agent_hub"]["cooperative_codex"]["worker_agent"], "free-helper")


class _OkProvider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        return ProviderResult(text="ok", model=self.agent.model)


class _CaptureProvider:
    last_request: HubRequest | None = None

    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        type(self).last_request = request
        return ProviderResult(text="ok", model=self.agent.model, usage={"prompt_tokens": 600, "completion_tokens": 10})


class _CooperativeProvider:
    calls: list[tuple[str, HubRequest]] = []

    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        type(self).calls.append((self.agent.name, request))
        if self.agent.name == "free-helper":
            return ProviderResult(
                text="Digest: inspect src/cache.py, keep failing token budget test, avoid unrelated config churn.",
                model=self.agent.model,
                usage={"prompt_tokens": 120, "completion_tokens": 36},
            )
        return ProviderResult(
            text=(
                "Final Codex answer: the cache token budget code should preserve the compacted "
                "context estimate, compare it with the effective model budget, and avoid changing "
                "unrelated configuration while explaining the token accounting clearly."
            ),
            model=self.agent.model,
            usage={"prompt_tokens": 600, "completion_tokens": 80},
        )


if __name__ == "__main__":
    unittest.main()
