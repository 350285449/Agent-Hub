from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..api.compatibility import available_model_ids, model_rows
from ..config import HubConfig
from ..enterprise import export_enterprise_audit
from ..evaluation import ProviderScoreStore
from ..models import HubRequest
from ..plugins import discover_plugins
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
        return {
            "object": "agent_hub.model_leaderboard",
            "routing_basis": "real outcomes, task success, latency, cost, and failure history",
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
        return {
            "object": "agent_hub.cost_dashboard",
            "cost_by_provider": optimization.get("cost_by_provider", {}),
            "cost_by_model": optimization.get("cost_by_model", {}),
            "cost_by_task_type": optimization.get("cost_by_task_type", {}),
            "cost_by_day": optimization.get("cost_by_day", {}),
            "known_cost_usd": optimization.get("known_cost_usd", optimization.get("total_known_cost_usd")),
            "average_known_cost_usd": optimization.get("average_known_cost_usd"),
            "money_saved": optimization.get("cost_optimizer", {}),
        }

    def backend_health_body(self, router: Any, *, context_diagnostics: dict[str, Any]) -> dict[str, Any]:
        config = self.config
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
            "streaming": {
                "force_compatibility_streaming": config.force_compatibility_streaming,
            },
            "repo_ignore_patterns": config.repo_ignore_patterns,
            "plugins": self.plugins_body(),
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
            "provider_health": router.health_snapshot(),
            "providers": router.provider_status(),
            "capability_graph": router.capability_graph(),
            "active_providers": self.active_provider_names(router),
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


__all__ = ["BACKEND_FEATURES", "BACKEND_VERSION", "DiagnosticsApplicationService"]
