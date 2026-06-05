from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from ..api.compatibility import available_model_ids, model_rows
from ..config import HubConfig
from ..enterprise import export_enterprise_audit
from ..evaluation import ProviderScoreStore
from ..models import HubRequest
from ..plugins import discover_plugins
from ..server_routes.middleware import api_token, public_bind_host
from ..version import backend_version, build_metadata, config_runtime_hash


BACKEND_VERSION = backend_version()
BACKEND_FEATURES = {
    "native_agent_streaming": True,
    "native_agent_tool_schemas": True,
    "agent_progress_v2": True,
    "workspace_edit_events": True,
    "active_file_context_resolution": True,
    "current_folder_context": True,
    "workspace_shell_commands": True,
    "file_write_tools": True,
    "fast_write_finalize": True,
    "multi_file_apply_patch": True,
    "post_edit_validation": True,
    "team_agent_mode": True,
    "transparent_openai_responses": True,
    "openrouter_style_api_path": True,
    "provider_presets": True,
    "automatic_config_initialization": True,
    "model_recommendations": True,
    "quota_aware_failover": True,
    "persistent_provider_health": True,
    "adaptive_latency_routing": True,
    "provider_health_metrics": True,
    "provider_health_scoring": True,
    "native_provider_streaming": True,
    "shell_command_permission_policy": True,
    "agent_hub_model_aliases": True,
    "openai_tool_call_passthrough": True,
    "anthropic_messages_compatibility": True,
    "anthropic_tool_use_passthrough": True,
    "local_dummy_auth_compatibility": True,
    "workspace_checkpoints": True,
    "validation_repair_loops": True,
    "validation_rollback": True,
    "context_change_bar": True,
    "agent_context_compaction": True,
    "context_usage_bar": True,
    "strict_repository_context": True,
    "grouped_patch_enforcement": True,
    "repository_context_scoring": True,
    "repository_graph_propagation": True,
    "semantic_related_file_detection": True,
    "anti_hallucination_edit_blocking": True,
    "limits_endpoint": True,
    "response_limit_headers": True,
    "central_permission_manager": True,
    "provider_permission_gate": True,
    "debug_echo_gate": True,
    "cline_tool_model_gate": True,
    "central_token_budget_manager": True,
    "tool_security_classifier": True,
    "secret_detection": True,
    "mandatory_public_api_auth": True,
    "trusted_session_approvals": True,
    "prompt_injection_defense": True,
    "provider_privacy_mode": True,
    "structured_observability": True,
    "capability_graph": True,
    "safe_mode": True,
    "cline_compatibility_mode": True,
    "protected_context_categories": True,
    "context_debug_endpoints": True,
    "context_engine_v2": True,
    "deterministic_workflows": True,
    "adaptive_learning_router": True,
    "routing_memory": True,
    "routing_memory_api": True,
    "routing_intelligence_api": True,
    "repository_dna": True,
    "repository_specific_routing": True,
    "workspace_memory": True,
    "multi_agent_debate": True,
    "model_tournament_mode": True,
    "automatic_escalation": True,
    "response_confidence_scoring": True,
    "failure_prediction": True,
    "cost_optimizer": True,
    "model_performance_database": True,
    "model_leaderboard": True,
    "cost_dashboard": True,
    "benchmark_results_dashboard": True,
    "workspace_rollback_api": True,
    "structured_user_feedback": True,
    "autonomous_night_mode_plan": True,
    "ai_team_visualization": True,
    "auto_workflow_selection": True,
    "optimization_analytics": True,
    "optimization_dashboard": True,
    "routing_simulation": True,
    "mcp_tool_compatibility_layer": True,
    "tool_execution_loop": True,
    "external_mcp_bridge": True,
    "repo_aware_coding": True,
    "provider_evaluation": True,
    "dashboard_status_endpoints": True,
    "raw_provider_response_debugging": True,
    "response_normalization_hardening": True,
    "streaming_recovery": True,
    "context_safety_cap": True,
    "repo_ignore_patterns": True,
    "plugin_sdk_foundation": True,
    "signed_plugin_manifests": True,
    "plugin_sandbox_foundation": True,
    "enterprise_foundation_models": True,
    "enterprise_audit_logs": True,
    "config_migration": True,
    "events_endpoint": True,
    "deployment_templates": True,
    "readiness_scorecard": True,
    "feature_maturity_status": True,
    "production_acceptance_check": True,
    "vscode_readiness_surface": True,
}


class DiagnosticsApplicationService:
    """Application boundary for diagnostics summaries that read local state."""

    def __init__(self, config: HubConfig) -> None:
        self.config = config

    def provider_scores(self) -> dict[str, Any]:
        return ProviderScoreStore(self.config.state_dir).load()

    def provider_scores_body(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.provider_scores",
            "benchmark_types": [
                "coding",
                "reasoning",
                "summarization",
                "tool_calling",
                "long_context",
                "latency",
            ],
            "data": self.provider_scores(),
        }

    def model_leaderboard_body(self, router: Any) -> dict[str, Any]:
        scores = self.provider_scores()
        health = router.health_snapshot()
        rows: list[dict[str, Any]] = []
        for name, agent in self.config.agents.items():
            score = scores.get(name, {}) if isinstance(scores.get(name), dict) else {}
            state = health.get(name, {}) if isinstance(health.get(name), dict) else {}
            successes = int(score.get("successes", state.get("success_count", 0)) or 0)
            failures = int(score.get("failures", state.get("failure_count", 0)) or 0)
            samples = successes + failures
            success_rate = successes / samples if samples else float(state.get("reliability_score", 0.7) or 0.7)
            rows.append(
                {
                    "agent": name,
                    "provider": agent.provider,
                    "model": agent.model,
                    "overall_score": float(score.get("overall_score", 0.0) or 0.0),
                    "success_rate": round(success_rate, 4),
                    "test_pass_rate": round(success_rate, 4),
                    "average_latency_ms": float(
                        score.get("average_latency_ms", state.get("average_latency_ms", 0.0)) or 0.0
                    ),
                    "free": bool(agent.free),
                    "cost_per_million_input": agent.cost_per_million_input,
                    "cost_per_million_output": agent.cost_per_million_output,
                    "task_scores": dict(score.get("task_scores") or {}),
                    "task_sample_counts": dict(score.get("task_sample_counts") or {}),
                    "samples": int(score.get("sample_count", samples) or samples),
                    "measurement_status": "measured" if samples or score.get("sample_count") else "needs_data",
                }
            )
        rows.sort(
            key=lambda row: (
                -float(row["overall_score"]),
                -float(row["success_rate"]),
                float(row["average_latency_ms"] or 0.0),
            )
        )
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        try:
            dna = router.repository_intelligence.repository_dna().to_dict()
        except Exception:
            dna = {}
        sample_count = sum(int(row.get("samples", 0) or 0) for row in rows)
        measured_agent_count = sum(1 for row in rows if int(row.get("samples", 0) or 0) > 0)
        leader = next(
            (
                row
                for row in rows
                if int(row.get("samples", 0) or 0) > 0
                or float(row.get("overall_score", 0.0) or 0.0) > 0.0
            ),
            None,
        )
        return {
            "object": "agent_hub.model_leaderboard",
            "routing_basis": "real outcomes, task success, latency, cost, and failure history",
            "summary": {
                "agent_count": len(rows),
                "measured_agent_count": measured_agent_count,
                "sample_count": sample_count,
                "best_agent": leader.get("agent") if leader else None,
                "best_model": leader.get("model") if leader else None,
                "data_state": "ready" if sample_count else "waiting_for_benchmarks_or_traffic",
            },
            "empty_state": (
                None
                if sample_count
                else {
                    "title": "No measured model outcomes yet",
                    "message": (
                        "The leaderboard can rank configured agents, but it needs benchmark "
                        "or live-routing outcomes before scores are meaningful."
                    ),
                    "actions": [
                        "Run: python -m agent_hub eval --route coding --json",
                        "Run: python -m agent_hub benchmark-suite --route coding --limit 24 --json",
                        "Send real requests through Agent Hub so routing memory can learn outcomes.",
                    ],
                }
            ),
            "repository": dna,
            "routing_memory": router.routing_memory.stats(),
            "data": rows,
        }

    def benchmark_results_body(self) -> dict[str, Any]:
        reports_dir = Path(self.config.state_dir) / "benchmark_reports"
        reports: list[dict[str, Any]] = []
        if reports_dir.exists():
            for path in sorted(reports_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:20]:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                reports.append(
                    {
                        "name": path.name,
                        "updated_at": path.stat().st_mtime,
                        "summary": payload.get("summary", {}),
                        "results": payload.get("results", payload.get("data", [])),
                    }
                )
        return {
            "object": "agent_hub.benchmark_results",
            "count": len(reports),
            "summary": {
                "report_count": len(reports),
                "latest_report": reports[0]["name"] if reports else None,
                "total_result_count": sum(
                    len(report.get("results", []))
                    for report in reports
                    if isinstance(report.get("results"), list)
                ),
                "data_state": "ready" if reports else "waiting_for_benchmark_reports",
            },
            "empty_state": (
                None
                if reports
                else {
                    "title": "No benchmark reports yet",
                    "message": (
                        "Benchmark dashboards are populated after a benchmark suite writes "
                        "reports into the Agent Hub state directory."
                    ),
                    "actions": [
                        "Run: python -m agent_hub benchmark-suite --route coding --limit 24 --json",
                        "Use --output to save a specific report path.",
                        "Check provider readiness first with: python -m agent_hub doctor",
                    ],
                }
            ),
            "reports": reports,
        }

    def workspace_checkpoints_body(self) -> dict[str, Any]:
        root = Path(self.config.workspace_dir).resolve()
        state_dir = Path(self.config.state_dir)
        if not state_dir.is_absolute():
            state_dir = root / state_dir
        checkpoints_dir = state_dir.resolve() / "workspace-checkpoints"
        checkpoints: list[dict[str, Any]] = []
        if checkpoints_dir.exists():
            for path in sorted(checkpoints_dir.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
                if not path.is_dir() or path.name.startswith("."):
                    continue
                try:
                    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                checkpoints.append(
                    {
                        "id": str(manifest.get("id") or path.name),
                        "created_at": manifest.get("created_at"),
                        "reason": str(manifest.get("reason") or ""),
                        "paths": [
                            str(item.get("path"))
                            for item in manifest.get("files", [])
                            if isinstance(item, dict) and item.get("path")
                        ],
                    }
                )
        return {
            "object": "agent_hub.workspace_checkpoints",
            "count": len(checkpoints),
            "data": checkpoints,
        }

    def cost_dashboard_body(self, optimization: dict[str, Any]) -> dict[str, Any]:
        cost_by_provider = optimization.get("cost_by_provider", {})
        cost_by_model = optimization.get("cost_by_model", {})
        cost_by_task_type = optimization.get("cost_by_task_type", {})
        cost_by_day = optimization.get("cost_by_day", {})
        known_cost = optimization.get("known_cost_usd", optimization.get("total_known_cost_usd"))
        average_known_cost = optimization.get("average_known_cost_usd")
        has_cost_data = (
            known_cost is not None
            or average_known_cost is not None
            or _has_mapping_values(cost_by_provider)
            or _has_mapping_values(cost_by_model)
            or _has_mapping_values(cost_by_task_type)
            or _has_mapping_values(cost_by_day)
        )
        return {
            "object": "agent_hub.cost_dashboard",
            "summary": {
                "data_state": "ready" if has_cost_data else "waiting_for_priced_usage",
                "known_cost_usd": known_cost,
                "average_known_cost_usd": average_known_cost,
                "providers_tracked": len(cost_by_provider) if isinstance(cost_by_provider, dict) else 0,
                "models_tracked": len(cost_by_model) if isinstance(cost_by_model, dict) else 0,
                "task_types_tracked": len(cost_by_task_type) if isinstance(cost_by_task_type, dict) else 0,
            },
            "empty_state": (
                None
                if has_cost_data
                else {
                    "title": "No known cost data yet",
                    "message": (
                        "Agent Hub can estimate costs only when provider pricing is configured "
                        "and requests include token usage."
                    ),
                    "actions": [
                        "Add cost_per_million_input and cost_per_million_output to agents you want tracked.",
                        "Run: python -m agent_hub estimate --route coding --output-tokens 1000 --json \"fix tests\"",
                        "Send requests through priced providers so optimization data can accumulate.",
                    ],
                }
            ),
            "cost_by_provider": cost_by_provider,
            "cost_by_model": cost_by_model,
            "cost_by_task_type": cost_by_task_type,
            "cost_by_day": cost_by_day,
            "known_cost_usd": known_cost,
            "average_known_cost_usd": average_known_cost,
            "money_saved": optimization.get("cost_optimizer", {}),
        }

    def readiness_body(
        self,
        router: Any,
        *,
        provider_health: dict[str, dict[str, Any]] | None = None,
        setup_guidance: dict[str, Any] | None = None,
        plugins: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider_health = provider_health if isinstance(provider_health, dict) else router.health_snapshot()
        setup_guidance = (
            setup_guidance
            if isinstance(setup_guidance, dict)
            else _setup_guidance(self.config, provider_health)
        )
        plugins = plugins if isinstance(plugins, dict) else self.plugins_body()
        leaderboard = self.model_leaderboard_body(router)
        benchmarks = self.benchmark_results_body()
        feature_status = _feature_status(
            self.config,
            provider_health,
            setup_guidance,
            plugins,
            leaderboard=leaderboard,
            benchmarks=benchmarks,
        )
        items = _readiness_items(
            self.config,
            provider_health,
            setup_guidance,
            plugins,
            leaderboard=leaderboard,
            benchmarks=benchmarks,
        )
        total_weight = sum(_float(item.get("weight")) or 0.0 for item in items) or 1.0
        earned = sum(_float(item.get("earned")) or 0.0 for item in items)
        score = int(round((earned / total_weight) * 100))
        action_items = [item for item in items if item.get("status") == "action"]
        warning_items = [item for item in items if item.get("status") == "warn"]
        if action_items:
            state = "needs_setup"
        elif score >= 90:
            state = "production_ready"
        elif score >= 75:
            state = "solid_beta"
        else:
            state = "needs_attention"
        next_step = action_items[0] if action_items else (warning_items[0] if warning_items else None)
        return {
            "object": "agent_hub.readiness",
            "score": score,
            "rating": round(score / 10, 1),
            "state": state,
            "summary": {
                "total_weight": int(total_weight),
                "earned": round(earned, 2),
                "action_count": len(action_items),
                "warning_count": len(warning_items),
                "ok_count": sum(1 for item in items if item.get("status") == "ok"),
            },
            "next_step": next_step,
            "items": items,
            "feature_status": feature_status,
        }

    def production_check_body(
        self,
        router: Any,
        *,
        provider_health: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        provider_health = provider_health if isinstance(provider_health, dict) else router.health_snapshot()
        setup_guidance = _setup_guidance(self.config, provider_health)
        plugins = self.plugins_body()
        readiness = self.readiness_body(
            router,
            provider_health=provider_health,
            setup_guidance=setup_guidance,
            plugins=plugins,
        )
        dashboards = {
            "cost": self.cost_dashboard_body({}),
            "leaderboard": self.model_leaderboard_body(router),
            "benchmarks": self.benchmark_results_body(),
        }
        checks = _production_checks(
            self.config,
            router,
            provider_health,
            setup_guidance,
            plugins,
            readiness,
            dashboards,
        )
        total_weight = sum(_float(check.get("weight")) or 0.0 for check in checks) or 1.0
        earned = sum(_float(check.get("earned")) or 0.0 for check in checks)
        score = int(round((earned / total_weight) * 100))
        failed = [
            check
            for check in checks
            if not check.get("ok") and check.get("severity") in {"critical", "major"}
        ]
        warnings = [
            check
            for check in checks
            if not check.get("ok") and check.get("severity") not in {"critical", "major"}
        ]
        return {
            "object": "agent_hub.production_check",
            "ok": not failed and score >= 90,
            "score": score,
            "rating": round(score / 10, 1),
            "state": "passed" if not failed and score >= 90 else "needs_attention",
            "summary": {
                "total_weight": int(total_weight),
                "earned": round(earned, 2),
                "failed_count": len(failed),
                "warning_count": len(warnings),
                "passed_count": sum(1 for check in checks if check.get("ok")),
            },
            "failed": failed,
            "warnings": warnings,
            "checks": checks,
            "readiness": readiness,
        }

    def backend_health_body(self, router: Any, *, context_diagnostics: dict[str, Any]) -> dict[str, Any]:
        config = self.config
        provider_health = router.health_snapshot()
        setup_guidance = _setup_guidance(config, provider_health)
        plugins = self.plugins_body()
        readiness = self.readiness_body(
            router,
            provider_health=provider_health,
            setup_guidance=setup_guidance,
            plugins=plugins,
        )
        return {
            "status": "ok",
            "running": True,
            "server_status": "running",
            "version": BACKEND_VERSION,
            "build": build_metadata(),
            "runtime": {"config_hash": config_runtime_hash(config)},
            "features": BACKEND_FEATURES,
            "agents": [
                name
                for name, agent in config.agents.items()
                if agent.enabled
            ],
            "configured_agents": list(config.agents),
            "free_only": config.free_only,
            "allow_shell_tools": config.allow_shell_tools,
            "shell_command_policy": config.shell_command_policy,
            "approval_mode": config.approval_mode,
            "debug_echo_enabled": config.debug_echo_enabled,
            "routing_memory": {
                "enabled": config.routing_memory_enabled,
                "store_prompts": config.routing_memory_store_prompts,
                "retention_days": config.routing_memory_retention_days,
            },
            "repository_intelligence": {
                "repository_dna_enabled": config.repository_dna_enabled,
                "workspace_memory_enabled": config.workspace_memory_enabled,
                "failure_prediction_enabled": config.failure_prediction_enabled,
                "cost_optimizer_enabled": config.cost_optimizer_enabled,
                "autonomous_night_mode_enabled": config.autonomous_night_mode_enabled,
            },
            "permission_policy": {
                "approval_mode": config.approval_mode,
                "safe_mode": config.approval_mode == "safe",
                "readonly_mode": config.approval_mode == "readonly",
                "shell_command_policy": config.shell_command_policy,
                "external_provider_approval": True,
                "file_write_approval": config.approval_mode in {"ask", "safe", "readonly", "deny"},
                "dangerous_command_blocking": True,
                "secret_detection": True,
            },
            "prefer_multi_file_patches": config.prefer_multi_file_patches,
            "grouped_patch_enforcement": {
                "enabled": config.prefer_multi_file_patches,
            },
            "context_change_bar": {
                "enabled": config.context_change_bar_enabled,
                "mode": config.context_change_bar_mode,
                "threshold": config.context_change_bar_threshold,
            },
            "agent_context_compaction": {
                "enabled": config.agent_context_compaction_enabled,
                "budget_tokens": config.agent_context_budget_tokens,
                "mode": config.context_mode,
            },
            "token_budget": {
                "mode": config.context_mode,
                "budget_tokens": config.agent_context_budget_tokens,
                "max_context_tokens": config.max_context_tokens,
                "compatibility_mode": config.compatibility_mode,
                "adaptive_modes": ["minimal", "balanced", "deep"],
                "cline_compatibility_mode": config.cline_compatibility_mode,
                "protected_categories": [
                    "recent_tool_calls",
                    "task_progress",
                    "todos",
                    "active_editor",
                    "workspace_state",
                    "mcp_state",
                    "latest_reasoning",
                ],
            },
            "context_diagnostics": context_diagnostics,
            "setup_guidance": setup_guidance,
            "readiness": readiness,
            "feature_status": readiness["feature_status"],
            "streaming": {
                "force_compatibility_streaming": config.force_compatibility_streaming,
            },
            "repo_ignore_patterns": config.repo_ignore_patterns,
            "plugins": plugins,
            "repository_context_scoring": {
                "enabled": config.context_change_bar_enabled,
                "light_minimum": 3,
                "strict_minimum": 6,
                "changed_file_threshold": config.context_change_bar_threshold,
            },
            "repository_graph": {
                "enabled": True,
                "node_count": 0,
                "related_file_detection_enabled": True,
                "strict_anti_hallucination_enforcement_enabled": (
                    config.context_change_bar_enabled
                    and config.context_change_bar_mode == "strict"
                ),
            },
            "workspace_dir": str(config.workspace_dir),
            "initialization": config.initialization_report,
            "provider_health": provider_health,
            "providers": router.provider_status(),
            "capability_graph": router.capability_graph(),
            "active_providers": [
                name
                for name, agent in sorted(config.agents.items())
                if agent.enabled and provider_health.get(name, {}).get("available")
            ],
            "limits": self.limits_body(router),
            "recommendations": router.recommend(
                HubRequest(
                    session_id="health",
                    route="cloud-agent",
                    messages=[{"role": "user", "content": "select an agent model"}],
                    record_session=False,
                ),
                limit=5,
                needs_tools=True,
                include_unavailable=True,
            ),
            "models": self.model_rows(router),
            "available_models": self.available_model_ids(router),
        }

    def limits_body(self, router: Any) -> dict[str, Any]:
        config = self.config
        health = router.health_snapshot(include_history=True)
        recommendations = router.recommend(
            HubRequest(
                session_id="limits",
                route="cloud-agent",
                messages=[{"role": "user", "content": "select an agent model"}],
                record_session=False,
            ),
            limit=8,
            needs_tools=True,
            include_unavailable=True,
        )
        active = next((row for row in recommendations if row.get("available")), None)
        if active is None and recommendations:
            active = recommendations[0]
        providers = [
            _provider_limit_row(name, agent, health.get(name, {}))
            for name, agent in sorted(config.agents.items())
            if agent.enabled
        ]
        failed_models: list[dict[str, Any]] = []
        for row in providers:
            if row.get("last_error_message"):
                failed_models.append(
                    {
                        "agent": row["agent"],
                        "provider": row["provider"],
                        "model": row["model"],
                        "reason": row["last_error_message"],
                        "cooldown_until": row["cooldown_until"],
                    }
                )
        return {
            "object": "agent_hub.limits",
            "status": "running",
            "running": True,
            "active_model": _active_model_row(active),
            "active_providers": [
                row["agent"]
                for row in providers
                if row.get("available")
            ],
            "providers": providers,
            "limits": providers,
            "provider_health": health,
            "cooldowns": {
                row["agent"]: row["cooldown_until"]
                for row in providers
                if row.get("cooldown_until")
            },
            "available_models": self.available_model_ids(router),
            "failed_models": failed_models,
            "fallback_models": failed_models,
            "recommendations": recommendations,
        }

    def plugins_body(self) -> dict[str, Any]:
        return discover_plugins(self.config).to_dict()

    def enterprise_audit_body(self, query: dict[str, str] | None = None) -> dict[str, Any]:
        query = query or {}
        export = export_enterprise_audit(
            self.config.state_dir,
            limit=_positive_int(query.get("limit"), default=100, maximum=1000),
            user=query.get("user") or query.get("actor_id"),
            workspace=query.get("workspace") or query.get("workspace_id"),
            action=query.get("action"),
            allowed=_allowed_query(query),
            start_at=query.get("start_at") or query.get("from"),
            end_at=query.get("end_at") or query.get("to"),
            retention_days=getattr(self.config, "enterprise_audit_retention_days", None),
        )
        events = export["events"]
        return {
            "object": "agent_hub.enterprise_audit",
            "count": len(events),
            "recent": events,
            "export": export,
        }

    def active_provider_names(self, router: Any) -> list[str]:
        health = router.health_snapshot()
        return [
            name
            for name, agent in sorted(self.config.agents.items())
            if agent.enabled and health.get(name, {}).get("available")
        ]

    def available_model_ids(self, router: Any) -> list[str]:
        return available_model_ids(self.config, router)

    def model_rows(self, router: Any) -> list[dict[str, Any]]:
        return model_rows(self.config, router)


def _provider_limit_row(
    name: str,
    agent: Any,
    health: dict[str, Any],
) -> dict[str, Any]:
    return {
        "agent": name,
        "provider": agent.provider,
        "provider_name": agent.provider,
        "provider_type": agent.provider_type,
        "model": agent.model,
        "available": bool(health.get("available")),
        "degraded": bool(health.get("degraded")),
        "remaining": health.get("remaining", "unknown"),
        "quota_state": health.get("quota_state", "unknown"),
        "quota_source": health.get("quota_source", "unknown"),
        "quota_remaining": health.get("quota_remaining"),
        "requests_remaining": health.get("requests_remaining"),
        "tokens_remaining": health.get("tokens_remaining"),
        "credits_remaining": health.get("credits_remaining"),
        "rate_limit_reset_at": health.get("rate_limit_reset_at"),
        "cooldown_until": health.get("cooldown_until"),
        "unavailable_until": health.get("unavailable_until"),
        "last_error_type": health.get("last_error_type"),
        "last_error_message": health.get("last_error_message"),
        "average_latency_seconds": health.get("average_latency_seconds"),
        "tokens_per_second": health.get("average_tokens_per_second"),
        "context_limit": health.get("context_window"),
        "output_limit": health.get("max_output_tokens"),
        "last_request_source": health.get("last_request_source"),
        "last_failover_attempts": health.get("last_failover_attempts"),
        "stream_interruption_count": health.get("stream_interruption_count", 0),
        "success_count": health.get("success_count", 0),
        "failure_count": health.get("failure_count", 0),
    }


def _active_model_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "agent": row.get("agent"),
        "provider": row.get("provider"),
        "provider_name": row.get("provider"),
        "provider_type": row.get("provider_type"),
        "model": row.get("model"),
        "available": row.get("available"),
        "remaining": row.get("remaining", "unknown"),
        "quota_state": row.get("quota_state", "unknown"),
        "requests_remaining": row.get("requests_remaining"),
        "tokens_remaining": row.get("tokens_remaining"),
        "credits_remaining": row.get("credits_remaining"),
        "rate_limit_reset_at": row.get("rate_limit_reset_at"),
        "cooldown_until": row.get("cooldown_until"),
        "average_latency_seconds": row.get("average_latency_seconds"),
        "tokens_per_second": row.get("tokens_per_second"),
        "context_limit": row.get("context_limit"),
        "output_limit": row.get("output_limit"),
        "source_client": row.get("last_request_source"),
    }


def _allowed_query(query: dict[str, str]) -> bool | None:
    if "allowed" in query:
        return _query_bool(query["allowed"])
    if "allow" in query and _query_bool(query["allow"]) is True:
        return True
    for key in ("deny", "denied"):
        if key in query and _query_bool(query[key]) is True:
            return False
    return None


def _query_bool(value: str) -> bool | None:
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "allow", "allowed"}:
        return True
    if text in {"0", "false", "no", "off", "deny", "denied"}:
        return False
    return None


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, maximum))


def _has_mapping_values(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(item not in (None, "", {}, []) for item in value.values())


def _readiness_items(
    config: HubConfig,
    provider_health: dict[str, dict[str, Any]],
    setup_guidance: dict[str, Any],
    plugins: dict[str, Any],
    *,
    leaderboard: dict[str, Any],
    benchmarks: dict[str, Any],
) -> list[dict[str, Any]]:
    agents = list(config.agents.values())
    enabled_agents = [agent for agent in agents if agent.enabled]
    active_names = _active_names(config, provider_health)
    items = [
        _readiness_item(
            "providers_configured",
            "Providers are configured and enabled",
            "ok" if enabled_agents else "action",
            10,
            10 if enabled_agents else (4 if agents else 0),
            (
                f"{len(enabled_agents)} enabled provider(s) configured."
                if enabled_agents
                else (
                    "Provider entries exist but all are disabled."
                    if agents
                    else "No providers are configured."
                )
            ),
            None if enabled_agents else "python -m agent_hub init --with-cloud-examples",
        ),
        _readiness_item(
            "route_ready_provider",
            "At least one provider is route-ready",
            "ok" if active_names else "action",
            20,
            20 if active_names else (8 if enabled_agents else 0),
            (
                f"Available provider(s): {', '.join(active_names[:8])}."
                if active_names
                else "No enabled provider currently reports as available."
            ),
            None if active_names else "python -m agent_hub doctor --providers",
        ),
        _security_readiness_item(config),
        _context_readiness_item(config),
        _observability_readiness_item(config, provider_health),
        _data_product_readiness_item(leaderboard, benchmarks),
        _advanced_readiness_item(config),
        _plugin_readiness_item(config, plugins),
    ]
    if isinstance(setup_guidance.get("next_step"), dict) and setup_guidance.get("action_count"):
        route_item = next((item for item in items if item["id"] == "route_ready_provider"), None)
        if route_item is not None and not route_item.get("command"):
            route_item["command"] = setup_guidance["next_step"].get("command")
    return items


def _security_readiness_item(config: HubConfig) -> dict[str, Any]:
    public_auth_ok = not public_bind_host(str(config.host or "")) or bool(api_token(config))
    shell_guarded = not config.allow_shell_tools or config.shell_command_policy in {"ask", "deny"}
    controls = {
        "approval mode is guarded": config.approval_mode != "auto",
        "secret scanning enabled": config.secret_scanning_enabled,
        "prompt injection defense enabled": config.prompt_injection_defense_enabled,
        "provider privacy mode enabled": config.provider_privacy_mode_enabled,
        "public bind has API auth": public_auth_ok,
        "shell execution is guarded": shell_guarded,
    }
    missing = [label for label, ok in controls.items() if not ok]
    earned = 20 * ((len(controls) - len(missing)) / len(controls))
    status = "ok"
    command = None
    if missing:
        status = "warn"
        command = "Use approval_mode=safe and keep secret_scanning/provider_privacy enabled."
    if not public_auth_ok or not config.secret_scanning_enabled or not config.provider_privacy_mode_enabled:
        status = "action"
        command = (
            "Set api_auth_token/api_auth_token_env for public bind and keep "
            "secret_scanning_enabled/provider_privacy_mode_enabled true."
        )
    return _readiness_item(
        "security_guardrails",
        "Security guardrails are production-safe",
        status,
        20,
        earned,
        "All core guardrails are enabled." if not missing else "Missing: " + ", ".join(missing) + ".",
        command,
    )


def _context_readiness_item(config: HubConfig) -> dict[str, Any]:
    controls = {
        "context compaction": config.agent_context_compaction_enabled,
        "Cline compatibility": config.cline_compatibility_mode,
        "repository context": config.repo_context_enabled,
        "context change bar": config.context_change_bar_enabled,
    }
    missing = [label for label, ok in controls.items() if not ok]
    earned = 10 * ((len(controls) - len(missing)) / len(controls))
    return _readiness_item(
        "context_safety",
        "Context handling is guarded",
        "ok" if not missing else "warn",
        10,
        earned,
        "Context compaction and compatibility protections are enabled."
        if not missing
        else "Disabled: " + ", ".join(missing) + ".",
        None if not missing else "Re-enable context compaction and compatibility protections.",
    )


def _observability_readiness_item(
    config: HubConfig,
    provider_health: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    controls = {
        "routing memory": config.routing_memory_enabled,
        "adaptive learning": config.adaptive_learning_enabled,
        "provider health snapshot": bool(provider_health),
        "structured dashboard endpoints": True,
    }
    missing = [label for label, ok in controls.items() if not ok]
    earned = 15 * ((len(controls) - len(missing)) / len(controls))
    return _readiness_item(
        "observability_learning",
        "Observability and learning are active",
        "ok" if not missing else "warn",
        15,
        earned,
        "Routing memory, adaptive learning, and health snapshots are available."
        if not missing
        else "Disabled or empty: " + ", ".join(missing) + ".",
        None if not missing else "Enable routing_memory_enabled and adaptive_learning_enabled.",
    )


def _data_product_readiness_item(
    leaderboard: dict[str, Any],
    benchmarks: dict[str, Any],
) -> dict[str, Any]:
    leaderboard_summary = _dict(leaderboard.get("summary"))
    benchmark_summary = _dict(benchmarks.get("summary"))
    measured_agents = int(leaderboard_summary.get("measured_agent_count", 0) or 0)
    benchmark_reports = int(benchmark_summary.get("report_count", 0) or 0)
    has_leaderboard_data = measured_agents > 0
    has_benchmark_data = benchmark_reports > 0
    if has_leaderboard_data and has_benchmark_data:
        status = "ok"
        earned = 10
        detail = f"{measured_agents} measured agent(s), {benchmark_reports} benchmark report(s)."
        command = None
    elif has_leaderboard_data or has_benchmark_data:
        status = "warn"
        earned = 8
        detail = "Some performance data exists, but benchmark and live outcome coverage are incomplete."
        command = "Run python -m agent_hub benchmark-suite --route coding --limit 24 --json."
    else:
        status = "warn"
        earned = 5
        detail = "Dashboards are usable, but leaderboard and benchmark data have not accumulated yet."
        command = "Run python -m agent_hub eval --route coding --json."
    return _readiness_item(
        "data_products",
        "Dashboards have real performance data",
        status,
        10,
        earned,
        detail,
        command,
    )


def _advanced_readiness_item(config: HubConfig) -> dict[str, Any]:
    controls = {
        "failure prediction": config.failure_prediction_enabled,
        "cost optimizer": config.cost_optimizer_enabled,
        "model tournament": config.model_tournament_enabled,
        "automatic escalation": config.automatic_escalation_enabled,
        "night mode plan": True,
    }
    missing = [label for label, ok in controls.items() if not ok]
    earned = 10 * ((len(controls) - len(missing)) / len(controls))
    if not config.autonomous_night_mode_enabled:
        earned = min(earned, 8.0)
    detail = "Advanced routing intelligence is enabled."
    if missing:
        detail = "Disabled: " + ", ".join(missing) + "."
    elif not config.autonomous_night_mode_enabled:
        detail = "Advanced routing is enabled; autonomous night mode remains plan-only by default."
    return _readiness_item(
        "advanced_intelligence",
        "Advanced intelligence is usable and honest",
        "ok" if not missing and config.autonomous_night_mode_enabled else "warn",
        10,
        earned,
        detail,
        None if not missing else "Re-enable failure prediction, tournament mode, and escalation.",
    )


def _plugin_readiness_item(config: HubConfig, plugins: dict[str, Any]) -> dict[str, Any]:
    errors = plugins.get("errors") if isinstance(plugins.get("errors"), list) else []
    if not config.plugins_enabled:
        return _readiness_item(
            "plugins_integrations",
            "Plugin and MCP foundations are discoverable",
            "warn",
            5,
            2,
            "Plugin discovery is disabled.",
            "Set plugins_enabled=true to inspect plugin manifests.",
        )
    if errors:
        return _readiness_item(
            "plugins_integrations",
            "Plugin and MCP foundations are discoverable",
            "warn",
            5,
            3,
            f"{len(errors)} plugin discovery error(s) need attention.",
            "Check /v1/plugins for manifest errors.",
        )
    if config.plugin_execution_enabled:
        return _readiness_item(
            "plugins_integrations",
            "Plugin and MCP foundations are discoverable",
            "ok",
            5,
            5,
            "Plugin discovery and execution policy are enabled.",
        )
    return _readiness_item(
        "plugins_integrations",
        "Plugin and MCP foundations are discoverable",
        "ok",
        5,
        4,
        "Plugin manifests and trust policy are available; third-party code execution is disabled by default.",
    )


def _feature_status(
    config: HubConfig,
    provider_health: dict[str, dict[str, Any]],
    setup_guidance: dict[str, Any],
    plugins: dict[str, Any],
    *,
    leaderboard: dict[str, Any],
    benchmarks: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    active_names = _active_names(config, provider_health)
    leaderboard_summary = _dict(leaderboard.get("summary"))
    benchmark_summary = _dict(benchmarks.get("summary"))
    plugin_errors = plugins.get("errors") if isinstance(plugins.get("errors"), list) else []
    return {
        "provider_routing": {
            "state": "ready" if active_names else "needs_setup",
            "detail": ", ".join(active_names[:8]) if active_names else "No provider reports as available.",
        },
        "setup_guidance": {
            "state": "ready" if setup_guidance.get("ready") else "needs_action",
            "action_count": setup_guidance.get("action_count", 0),
            "warning_count": setup_guidance.get("warning_count", 0),
        },
        "security": {
            "state": "ready" if _security_readiness_item(config)["status"] == "ok" else "needs_review",
            "approval_mode": config.approval_mode,
            "provider_privacy_mode_enabled": config.provider_privacy_mode_enabled,
            "secret_scanning_enabled": config.secret_scanning_enabled,
        },
        "model_leaderboard": {
            "state": leaderboard_summary.get("data_state", "unknown"),
            "measured_agent_count": leaderboard_summary.get("measured_agent_count", 0),
            "sample_count": leaderboard_summary.get("sample_count", 0),
        },
        "benchmark_results_dashboard": {
            "state": benchmark_summary.get("data_state", "unknown"),
            "report_count": benchmark_summary.get("report_count", 0),
        },
        "cost_dashboard": {
            "state": "ready_needs_priced_usage",
            "detail": "Endpoint and HTML dashboard are available; meaningful totals require priced usage data.",
        },
        "autonomous_night_mode": {
            "state": "plan_enabled" if config.autonomous_night_mode_enabled else "plan_only_disabled",
            "detail": "Night mode returns a safety plan and does not execute unattended work by default.",
        },
        "plugins": {
            "state": (
                "disabled"
                if not config.plugins_enabled
                else ("needs_manifest_fixes" if plugin_errors else "execution_enabled" if config.plugin_execution_enabled else "foundation")
            ),
            "count": plugins.get("count", 0),
            "errors": len(plugin_errors),
        },
        "external_mcp_bridge": {
            "state": "foundation",
            "detail": "Internal MCP-shaped tools and config metadata are present; external execution stays policy-gated.",
        },
    }


def _readiness_item(
    item_id: str,
    label: str,
    status: str,
    weight: int,
    earned: float,
    detail: str,
    command: str | None = None,
) -> dict[str, Any]:
    bounded = max(0.0, min(float(weight), float(earned)))
    item: dict[str, Any] = {
        "id": item_id,
        "label": label,
        "status": status,
        "ok": status == "ok",
        "weight": weight,
        "earned": round(bounded, 2),
        "detail": detail,
    }
    if command:
        item["command"] = command
    return item


def _active_names(config: HubConfig, provider_health: dict[str, dict[str, Any]]) -> list[str]:
    return [
        name
        for name, agent in sorted(config.agents.items())
        if agent.enabled and provider_health.get(name, {}).get("available")
    ]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _setup_guidance(config: HubConfig, provider_health: dict[str, dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    agents = list(config.agents.values())
    enabled_agents = [agent for agent in agents if agent.enabled]
    active_agents = [
        agent
        for agent in enabled_agents
        if provider_health.get(agent.name, {}).get("available")
    ]
    if not agents:
        items.append(
            _setup_item(
                "configure_agents",
                "action",
                "Configure at least one provider",
                "No agents are configured, so Agent Hub cannot route requests.",
                "python -m agent_hub init --with-cloud-examples",
            )
        )
    else:
        items.append(
            _setup_item(
                "configure_agents",
                "ok",
                "Provider entries exist",
                f"{len(agents)} agent(s) are configured.",
            )
        )
    if agents and not enabled_agents:
        items.append(
            _setup_item(
                "enable_provider",
                "action",
                "Enable a provider",
                "All configured agents are disabled.",
                "python -m agent_hub agents",
            )
        )
    elif enabled_agents:
        items.append(
            _setup_item(
                "enable_provider",
                "ok",
                "At least one provider is enabled",
                f"{len(enabled_agents)} agent(s) are enabled.",
            )
        )
    missing_keys = [
        agent
        for agent in enabled_agents
        if agent.api_key_env and not agent.resolved_api_key
    ]
    if missing_keys and not active_agents:
        first = missing_keys[0]
        items.append(
            _setup_item(
                "provider_api_keys",
                "action",
                "Set required provider API keys",
                f"{first.name} is missing {first.api_key_env}.",
                f"Set {first.api_key_env} before starting Agent Hub.",
            )
        )
    elif missing_keys:
        items.append(
            _setup_item(
                "provider_api_keys",
                "warn",
                "Some API-key providers are not ready",
                ", ".join(f"{agent.name}:{agent.api_key_env}" for agent in missing_keys[:5]),
            )
        )
    else:
        items.append(
            _setup_item(
                "provider_api_keys",
                "ok",
                "No missing API keys detected",
                "Enabled API-key providers either have keys or do not require one.",
            )
        )
    probe_errors = (
        config.initialization_report.get("probe_errors")
        if isinstance(config.initialization_report, dict)
        else {}
    )
    if isinstance(probe_errors, dict) and probe_errors and not active_agents:
        first_name, first_error = next(iter(probe_errors.items()))
        items.append(
            _setup_item(
                "local_model_probe",
                "action",
                "Start or fix the local model server",
                f"{first_name} probe failed: {first_error}",
                "python -m agent_hub local-models",
            )
        )
    elif isinstance(probe_errors, dict) and probe_errors:
        items.append(
            _setup_item(
                "local_model_probe",
                "warn",
                "Some local model probes failed",
                ", ".join(str(name) for name in list(probe_errors)[:5]),
                "python -m agent_hub local-models",
            )
        )
    if active_agents:
        items.append(
            _setup_item(
                "route_ready",
                "ok",
                "At least one provider is route-ready",
                ", ".join(agent.name for agent in active_agents[:8]),
            )
        )
    else:
        items.append(
            _setup_item(
                "route_ready",
                "action",
                "Make a provider route-ready",
                "No enabled provider currently reports as available.",
                "python -m agent_hub doctor --providers",
            )
        )
    if config.approval_mode == "auto":
        items.append(
            _setup_item(
                "approval_mode",
                "warn",
                "Approval mode is auto",
                "Trusted cloud providers may run without interactive approval unless security policy blocks them.",
                "Use approval_mode=safe or ask for stricter interactive review.",
            )
        )
    else:
        items.append(
            _setup_item(
                "approval_mode",
                "ok",
                "Approval mode is guarded",
                f"Current mode: {config.approval_mode}.",
            )
        )
    action_count = sum(1 for item in items if item["status"] == "action")
    warning_count = sum(1 for item in items if item["status"] == "warn")
    next_step = next((item for item in items if item["status"] == "action"), None)
    if next_step is None:
        next_step = next((item for item in items if item["status"] == "warn"), None)
    return {
        "object": "agent_hub.setup_guidance",
        "ready": action_count == 0,
        "action_count": action_count,
        "warning_count": warning_count,
        "next_step": next_step,
        "items": items,
    }


def _setup_item(
    item_id: str,
    status: str,
    label: str,
    detail: str,
    command: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": item_id,
        "status": status,
        "ok": status == "ok",
        "label": label,
        "detail": detail,
    }
    if command:
        item["command"] = command
    return item


__all__ = ["BACKEND_FEATURES", "BACKEND_VERSION", "DiagnosticsApplicationService"]
