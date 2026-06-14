from __future__ import annotations

import json
from pathlib import Path
import re
import time
from typing import Any

from ..api.compatibility import available_model_ids, model_rows
from ..config import AgentConfig, HubConfig
from ..enterprise import EnterprisePolicy, RoleDefinition, export_enterprise_audit
from ..evaluation import ProviderScoreStore
from ..inbox import SUPPORTED_API_SHAPES, inbox_task_preview
from ..measurement import usage_ledger_summary
from ..visual_proof_dashboard import visual_proof_dashboard_body
from ..mcp import normalize_mcp_tools
from ..models import HubRequest
from ..plugins import discover_plugins
from ..provider_presets import provider_metadata_rows
from ..routing_memory import RoutingMemoryStore
from ..runtime_usability import runtime_usability_body
from ..server_routes.middleware import api_token, public_bind_host
from ..tool_compatibility import tool_emulation_enabled, universal_compatibility_enabled
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
    "universal_provider_compatibility": True,
    "emulated_tool_call_bridge": True,
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
    "autonomous_night_mode_validation": True,
    "ai_team_visualization": True,
    "auto_workflow_selection": True,
    "optimization_analytics": True,
    "optimization_dashboard": True,
    "routing_simulation": True,
    "mcp_tool_compatibility_layer": True,
    "tool_execution_loop": True,
    "external_mcp_bridge": True,
    "mcp_stdio_execution": True,
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
    "trusted_plugin_local_process_execution": True,
    "enterprise_foundation_models": True,
    "enterprise_audit_logs": True,
    "enterprise_status": True,
    "config_migration": True,
    "json_inbox_processing": True,
    "inbox_status_reporting": True,
    "inbox_submission_api": True,
    "mcp_policy_summary": True,
    "mcp_status_dashboard": True,
    "provider_route_readiness_policy": True,
    "night_mode_run_reports": True,
    "extension_contract_endpoint": True,
    "events_endpoint": True,
    "deployment_templates": True,
    "readiness_scorecard": True,
    "feature_maturity_status": True,
    "production_acceptance_check": True,
    "vscode_readiness_surface": True,
    "runtime_kernel_control_plane": True,
    "runtime_kernel_dashboard": True,
    "runtime_kernel_durable_history": True,
    "feature_scorecard": True,
    "agent_hub_boost_mode": True,
    "context_relevance_ranking": True,
    "output_quality_validation": True,
    "utf8_bom_config_loading": True,
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
            baseline_score = _agent_baseline_score(agent, state)
            measured = bool(samples or score.get("sample_count"))
            overall_score = float(score.get("overall_score", 0.0) or 0.0)
            rows.append(
                {
                    "agent": name,
                    "provider": agent.provider,
                    "model": agent.model,
                    "overall_score": overall_score,
                    "baseline_score": baseline_score,
                    "ranking_score": overall_score if measured else baseline_score,
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
                    "measurement_status": "measured" if measured else "configured_baseline",
                    "baseline_components": _agent_baseline_components(agent, state),
                }
            )
        rows.sort(
            key=lambda row: (
                -float(row["ranking_score"]),
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
        baseline_agent_count = sum(1 for row in rows if row.get("measurement_status") == "configured_baseline")
        leader = next(
            (
                row
                for row in rows
                if int(row.get("samples", 0) or 0) > 0
                or float(row.get("ranking_score", 0.0) or 0.0) > 0.0
            ),
            None,
        )
        data_state = (
            "measured_ready"
            if sample_count
            else "baseline_ready"
            if rows
            else "no_agents_configured"
        )
        return {
            "object": "agent_hub.model_leaderboard",
            "routing_basis": (
                "measured outcomes, task success, latency, cost, failure history, "
                "and cold-start configuration baselines"
            ),
            "summary": {
                "agent_count": len(rows),
                "measured_agent_count": measured_agent_count,
                "baseline_agent_count": baseline_agent_count,
                "sample_count": sample_count,
                "best_agent": leader.get("agent") if leader else None,
                "best_model": leader.get("model") if leader else None,
                "data_state": data_state,
            },
            "empty_state": (
                None
                if rows
                else {
                    "title": "No agents available for model ranking",
                    "message": (
                        "Configure at least one agent before Agent Hub can rank models."
                    ),
                    "actions": [
                        "Run: python -m agent_hub init",
                        "Check readiness with: python -m agent_hub doctor --providers",
                    ],
                }
            ),
            "measurement_notice": (
                None
                if sample_count
                else {
                    "title": "Cold-start model ranking is ready; measured outcomes pending",
                    "message": (
                        "Rows are ranked from configured scores, provider health, cost flags, "
                        "and declared capabilities until benchmark or live-routing outcomes arrive."
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
                        "summary": _benchmark_report_summary(payload),
                        "results": payload.get("results", payload.get("data", [])),
                    }
                )
        scores = self.provider_scores()
        snapshot = _benchmark_coverage_snapshot(self.config, scores)
        measured_snapshot_agents = sum(
            1 for row in snapshot["results"] if int(row.get("sample_count", 0) or 0) > 0
        )
        has_measured_data = bool(reports or measured_snapshot_agents)
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
                "snapshot_result_count": len(snapshot["results"]),
                "measured_snapshot_agents": measured_snapshot_agents,
                "data_state": "measured_ready" if has_measured_data else "baseline_ready",
            },
            "empty_state": (
                None
                if snapshot["results"]
                else {
                    "title": "No agents available for benchmark coverage",
                    "message": (
                        "Configure at least one agent to build a benchmark-readiness snapshot."
                    ),
                    "actions": [
                        "Run: python -m agent_hub init",
                        "Check provider readiness with: python -m agent_hub doctor",
                    ],
                }
            ),
            "measurement_notice": (
                None
                if has_measured_data
                else {
                    "title": "Configuration baseline ready; live measurements pending",
                    "message": (
                        "The snapshot below audits benchmark coverage without calling providers. "
                        "Run a benchmark suite to add measured quality, latency, and cost comparisons."
                    ),
                    "actions": [
                        "Run: python -m agent_hub benchmark-suite --route coding --limit 24 --json",
                        "Run: python -m agent_hub eval --route coding --json",
                    ],
                }
            ),
            "operational_readiness": _benchmark_operational_readiness(snapshot, reports),
            "measurement_plan": _benchmark_measurement_plan(self.config, snapshot),
            "coverage_snapshot": snapshot,
            "reports": reports,
            "visual_proof_dashboard": visual_proof_dashboard_body(
                repository=_repository_identity(self.config),
                usage=usage_ledger_summary(self.config),
                benchmarks={"summary": {
                    "report_count": len(reports),
                    "latest_report": reports[0]["name"] if reports else None,
                    "total_result_count": sum(
                        len(report.get("results", []))
                        for report in reports
                        if isinstance(report.get("results"), list)
                    ),
                }, "reports": reports, "coverage_snapshot": snapshot},
            ),
        }

    def proof_dashboard_body(self) -> dict[str, Any]:
        benchmarks = self.benchmark_results_body()
        memory = RoutingMemoryStore.from_config(self.config).stats()
        return visual_proof_dashboard_body(
            repository=_repository_identity(self.config),
            usage=usage_ledger_summary(self.config),
            benchmarks=benchmarks,
            routing_memory=memory,
        )

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
        ledger = usage_ledger_summary(self.config)
        ledger_request_count = int(ledger.get("request_count") or 0)
        ledger_sources = _dict(ledger.get("measurement_sources"))
        ledger_actual_cost = _float(ledger.get("total_actual_cost_usd")) or 0.0
        ledger_estimated_cost = _float(ledger.get("total_estimated_cost_usd")) or 0.0
        known_cost = optimization.get("known_cost_usd", optimization.get("total_known_cost_usd"))
        average_known_cost = optimization.get("average_known_cost_usd")
        display_known_cost = known_cost if known_cost is not None else (ledger_actual_cost if ledger_actual_cost > 0 else None)
        display_average_known_cost = average_known_cost
        if display_average_known_cost is None and ledger_request_count > 0 and ledger_actual_cost > 0:
            display_average_known_cost = round(ledger_actual_cost / ledger_request_count, 8)
        has_cost_data = (
            known_cost is not None
            or average_known_cost is not None
            or ledger_request_count > 0
            or _has_mapping_values(cost_by_provider)
            or _has_mapping_values(cost_by_model)
            or _has_mapping_values(cost_by_task_type)
            or _has_mapping_values(cost_by_day)
        )
        pricing_catalog = _pricing_catalog(self.config)
        priced_agents = sum(1 for row in pricing_catalog if row["pricing_status"] == "priced")
        free_agents = sum(1 for row in pricing_catalog if row["pricing_status"] == "free")
        partial_agents = sum(1 for row in pricing_catalog if row["pricing_status"] == "partial")
        missing_agents = sum(1 for row in pricing_catalog if row["pricing_status"] == "missing")
        covered_agents = priced_agents + free_agents
        coverage_rate = round(covered_agents / max(1, len(pricing_catalog)), 4)
        if has_cost_data:
            data_state = "measured_ready"
        elif covered_agents == len(pricing_catalog) and pricing_catalog:
            data_state = "pricing_ready_waiting_for_usage"
        elif pricing_catalog:
            data_state = "partial_pricing_waiting_for_usage"
        else:
            data_state = "no_agents_configured"
        return {
            "object": "agent_hub.cost_dashboard",
            "summary": {
                "data_state": data_state,
                "measurement_state": "measured" if has_cost_data else "waiting_for_usage",
                "known_cost_usd": display_known_cost,
                "average_known_cost_usd": display_average_known_cost,
                "providers_tracked": len(cost_by_provider) if isinstance(cost_by_provider, dict) else 0,
                "models_tracked": len(cost_by_model) if isinstance(cost_by_model, dict) else 0,
                "task_types_tracked": len(cost_by_task_type) if isinstance(cost_by_task_type, dict) else 0,
                "configured_agents": len(pricing_catalog),
                "priced_agents": priced_agents,
                "free_agents": free_agents,
                "partial_pricing_agents": partial_agents,
                "missing_pricing_agents": missing_agents,
                "pricing_coverage_rate": coverage_rate,
                "usage_ledger_requests": ledger_request_count,
                "actual_usage_requests": int(ledger_sources.get("actual") or 0),
                "mixed_usage_requests": int(ledger_sources.get("mixed") or 0),
                "estimated_usage_requests": int(ledger_sources.get("estimated") or 0),
                "ledger_actual_cost_usd": ledger_actual_cost,
                "ledger_estimated_cost_usd": ledger_estimated_cost,
            },
            "empty_state": (
                None
                if pricing_catalog
                else {
                    "title": "No agents available for cost coverage",
                    "message": (
                        "Configure at least one agent before auditing pricing and recorded spend."
                    ),
                    "actions": [
                        "Run: python -m agent_hub init",
                    ],
                }
            ),
            "measurement_notice": (
                None
                if has_cost_data
                else {
                    "title": "Pricing coverage ready; measured spend pending",
                    "message": (
                        "Sample estimates use configured prices only. Known spend remains empty "
                        "until routed requests report token usage."
                    ),
                    "actions": [
                        "Add prices for agents marked missing or partial.",
                        "Run: python -m agent_hub estimate --route coding --output-tokens 1000 --json \"fix tests\"",
                        "Send requests through priced providers so measured totals accumulate.",
                    ],
                }
            ),
            "pricing_catalog": pricing_catalog,
            "cost_by_provider": cost_by_provider,
            "cost_by_model": cost_by_model,
            "cost_by_task_type": cost_by_task_type,
            "cost_by_day": cost_by_day,
            "known_cost_usd": display_known_cost,
            "average_known_cost_usd": display_average_known_cost,
            "usage_ledger": ledger,
            "money_saved": optimization.get("cost_optimizer", {}),
        }

    def readiness_body(
        self,
        router: Any,
        *,
        provider_health: dict[str, dict[str, Any]] | None = None,
        setup_guidance: dict[str, Any] | None = None,
        plugins: dict[str, Any] | None = None,
        runtime_usability: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider_health = provider_health if isinstance(provider_health, dict) else router.health_snapshot()
        setup_guidance = (
            setup_guidance
            if isinstance(setup_guidance, dict)
            else _setup_guidance(self.config, provider_health)
        )
        plugins = plugins if isinstance(plugins, dict) else self.plugins_body()
        runtime_usability = (
            runtime_usability
            if isinstance(runtime_usability, dict)
            else runtime_usability_body(self.config, provider_health)
        )
        leaderboard = self.model_leaderboard_body(router)
        benchmarks = self.benchmark_results_body()
        feature_status = _feature_status(
            self.config,
            provider_health,
            setup_guidance,
            plugins,
            runtime_usability=runtime_usability,
            leaderboard=leaderboard,
            benchmarks=benchmarks,
        )
        items = _readiness_items(
            self.config,
            provider_health,
            setup_guidance,
            plugins,
            runtime_usability=runtime_usability,
            leaderboard=leaderboard,
            benchmarks=benchmarks,
        )
        total_weight = sum(_float(item.get("weight")) or 0.0 for item in items) or 1.0
        earned = sum(_float(item.get("earned")) or 0.0 for item in items)
        score = int(round((earned / total_weight) * 100))
        contract_items = [item for item in items if item.get("id") != "runtime_usability"]
        contract_total = sum(_float(item.get("weight")) or 0.0 for item in contract_items) or 1.0
        contract_earned = sum(_float(item.get("earned")) or 0.0 for item in contract_items)
        contract_score = int(round((contract_earned / contract_total) * 100))
        contract_actions = [item for item in contract_items if item.get("status") == "action"]
        action_items = [item for item in items if item.get("status") == "action"]
        warning_items = [item for item in items if item.get("status") == "warn"]
        runtime_state = str(runtime_usability.get("state") or "")
        if action_items:
            state = "needs_setup"
        elif runtime_state == "degraded":
            state = "solid_beta"
        elif runtime_state and runtime_state != "ready":
            state = "needs_attention"
        elif score >= 90:
            state = "production_ready"
        elif score >= 75:
            state = "solid_beta"
        else:
            state = "needs_attention"
        if contract_actions:
            contract_state = "needs_setup"
        elif contract_score >= 90:
            contract_state = "production_ready"
        elif contract_score >= 75:
            contract_state = "solid_beta"
        else:
            contract_state = "needs_attention"
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
            "runtime_usability": runtime_usability,
            "contract_readiness": {
                "score": contract_score,
                "rating": round(contract_score / 10, 1),
                "state": contract_state,
                "scope": "local contracts, setup, safety, dashboards, and data surfaces without live runtime smoke",
            },
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
        runtime_usability = runtime_usability_body(self.config, provider_health)
        readiness = self.readiness_body(
            router,
            provider_health=provider_health,
            setup_guidance=setup_guidance,
            plugins=plugins,
            runtime_usability=runtime_usability,
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
            runtime_usability=runtime_usability,
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
            "runtime_usability": runtime_usability,
        }

    def feature_scorecard_body(self, router: Any) -> dict[str, Any]:
        provider_health = router.health_snapshot()
        plugins = self.plugins_body()
        runtime_usability = runtime_usability_body(self.config, provider_health)
        readiness = self.readiness_body(
            router,
            provider_health=provider_health,
            plugins=plugins,
            runtime_usability=runtime_usability,
        )
        production = self.production_check_body(router, provider_health=provider_health)
        extension = self.extension_contract_body()
        inbox = self.inbox_status_body()
        mcp = self.mcp_status_body()
        areas = _feature_scorecard_areas(
            self.config,
            provider_health=provider_health,
            readiness=readiness,
            production=production,
            extension=extension,
            inbox=inbox,
            plugins=plugins,
            mcp=mcp,
            provider_type_count=len(provider_metadata_rows()),
        )
        overall = round(sum(float(area["rating"]) for area in areas) / max(1, len(areas)), 1)
        blockers = [
            {
                "area": area["area"],
                "missing": [
                    check
                    for check in area["checks"]
                    if check.get("required") and not check.get("ok")
                ],
            }
            for area in areas
            if any(check.get("required") and not check.get("ok") for check in area["checks"])
        ]
        return {
            "object": "agent_hub.feature_scorecard",
            "scope": "local implementation and runtime contract proof",
            "rating": overall,
            "state": "local_10_of_10" if not blockers and overall == 10.0 else "needs_attention",
            "runtime_state": runtime_usability.get("state"),
            "all_local_areas_10": not blockers and overall == 10.0,
            "contract_readiness": {
                "rating": overall,
                "state": "local_10_of_10" if not blockers and overall == 10.0 else "needs_attention",
            },
            "runtime_usability": runtime_usability,
            "honesty": (
                "This scorecard proves local code paths, contracts, policies, and configured "
                "runtime foundations. The runtime_usability object reports whether this "
                "machine has a verified provider path that can answer real tasks right now."
            ),
            "areas": areas,
            "blockers": blockers,
        }

    def backend_health_body(self, router: Any, *, context_diagnostics: dict[str, Any]) -> dict[str, Any]:
        config = self.config
        provider_health = router.health_snapshot()
        setup_guidance = _setup_guidance(config, provider_health)
        plugins = self.plugins_body()
        runtime_usability = runtime_usability_body(config, provider_health)
        readiness = self.readiness_body(
            router,
            provider_health=provider_health,
            setup_guidance=setup_guidance,
            plugins=plugins,
            runtime_usability=runtime_usability,
        )
        experience_summary = _experience_summary(
            config,
            provider_health=provider_health,
            setup_guidance=setup_guidance,
            readiness=readiness,
            context_diagnostics=context_diagnostics,
            runtime_usability=runtime_usability,
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
            "runtime_usability": runtime_usability,
            "experience_summary": experience_summary,
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
            "active_providers": _active_names(config, provider_health),
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
                if row.get("route_ready")
            ],
            "providers": providers,
            "limits": providers,
            "provider_health": health,
            "cooldowns": {
                row["agent"]: row["cooldown_until"]
                for row in providers
                if row.get("cooldown_until")
            },
            "blocked_models": [
                {
                    "agent": row["agent"],
                    "provider": row["provider"],
                    "model": row["model"],
                    "reason": row.get("route_ready_reason") or "not route-ready",
                    "cooldown_until": row.get("cooldown_until"),
                    "unavailable_until": row.get("unavailable_until"),
                }
                for row in providers
                if not row.get("route_ready")
            ],
            "available_models": self.available_model_ids(router),
            "failed_models": failed_models,
            "fallback_models": failed_models,
            "recommendations": recommendations,
        }

    def plugins_body(self) -> dict[str, Any]:
        body = discover_plugins(self.config).to_dict()
        errors = body.get("errors") if isinstance(body.get("errors"), list) else []
        enabled_count = int(body.get("enabled_count", 0) or 0)
        trusted_count = int(body.get("trusted_count", 0) or 0)
        registered_count = int(body.get("registered_count", 0) or 0)
        registered_capabilities = _dict(body.get("registered_capabilities"))
        capability_coverage = {
            key: len(value) if isinstance(value, list) else 0
            for key, value in registered_capabilities.items()
        }
        if not self.config.plugins_enabled:
            state = "disabled"
            next_step = "Set plugins_enabled=true to inspect plugin manifests."
        elif errors:
            state = "needs_manifest_fixes"
            next_step = "Fix plugin manifest errors reported in the errors list."
        elif self.config.plugin_execution_enabled:
            state = "trusted_local_process_enabled"
            next_step = "Keep trusted_plugins and plugin_capability_grants scoped to the minimum required capabilities."
        elif enabled_count or trusted_count or registered_count:
            state = "metadata_ready_execution_disabled"
            next_step = "Enable plugin_execution_enabled only for trusted plugins that need local process execution."
        else:
            state = "discovery_ready"
            next_step = "Add a plugin.json under .agent-hub/plugins/<plugin-id>/ to register local extensions."
        body.update(
            {
                "state": state,
                "summary": {
                    "state": state,
                    "plugin_count": int(body.get("count", 0) or 0),
                    "enabled_count": enabled_count,
                    "trusted_count": trusted_count,
                    "registered_count": registered_count,
                    "error_count": len(errors),
                    "execution_enabled": bool(self.config.plugin_execution_enabled),
                },
                "execution_policy": {
                    "plugins_enabled": bool(self.config.plugins_enabled),
                    "plugin_execution_enabled": bool(self.config.plugin_execution_enabled),
                    "trusted_plugins": list(self.config.trusted_plugins),
                    "enabled_plugins": list(self.config.enabled_plugins),
                    "disabled_plugins": list(self.config.disabled_plugins),
                },
                "capability_coverage": capability_coverage,
                "runtime_contract": {
                    "validate_action": {
                        "endpoint": "/v1/plugins/{plugin_id}/execute",
                        "payload": {"action": "validate", "requested_scopes": []},
                        "runs_plugin_code": False,
                    },
                    "execute_action": {
                        "endpoint": "/v1/plugins/{plugin_id}/execute",
                        "payload": {"action": "execute", "payload": {}, "requested_scopes": []},
                        "requires": [
                            "plugins_enabled=true",
                            "plugin_execution_enabled=true",
                            "plugin trusted by registry or config",
                            "requested scopes granted",
                            "entrypoint inside plugin directory",
                        ],
                    },
                    "supported_entrypoints": [".py", ".js", ".mjs", ".cjs"],
                    "stdin_contract": {
                        "plugin_id": "string",
                        "action": "string",
                        "granted_scopes": "string[]",
                        "payload": "object",
                    },
                    "stdout_contract": "JSON object preferred; plain text is captured as output",
                },
                "operational_readiness": _plugin_operational_readiness(
                    self.config,
                    state=state,
                    error_count=len(errors),
                ),
                "mcp": _mcp_policy_summary(self.config),
                "next_step": next_step,
            }
        )
        return body

    def mcp_status_body(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.mcp_status",
            **_mcp_policy_summary(self.config),
        }

    def extension_contract_body(self) -> dict[str, Any]:
        contract = _extension_feature_contract()
        return {
            "object": "agent_hub.extension_contract",
            "backend_version": BACKEND_VERSION,
            "build": build_metadata(),
            "contract": contract,
            "features": BACKEND_FEATURES,
            "summary": {
                "ok": bool(contract.get("ok")),
                "available": bool(contract.get("available")),
                "required_count": int(contract.get("required_count", 0) or 0),
                "missing_count": len(contract.get("missing", [])) if isinstance(contract.get("missing"), list) else 0,
            },
            "maturity": {
                "version_reported": True,
                "build_metadata_reported": True,
                "required_feature_diff": True,
                "machine_readable": True,
            },
        }

    def inbox_status_body(self) -> dict[str, Any]:
        inbox = Path(self.config.inbox_dir)
        outbox = Path(self.config.outbox_dir)
        archive = Path(self.config.archive_dir)
        pending = sorted(inbox.glob("*.json")) if inbox.exists() else []
        processing = [path for path in pending if path.name.endswith(".processing.json")]
        pending = [path for path in pending if not path.name.endswith(".processing.json")]
        outputs = sorted(outbox.glob("*.json"), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True) if outbox.exists() else []
        archived = sorted(archive.glob("*.json"), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True) if archive.exists() else []
        pending_summaries = [inbox_task_preview(path) for path in pending[:25]]
        processing_summaries = [inbox_task_preview(path) for path in processing[:10]]
        invalid_pending = [row for row in pending_summaries if not row.get("valid")]
        oldest_pending = min((_float(row.get("modified_at")) or time.time()) for row in pending_summaries) if pending_summaries else None
        return {
            "object": "agent_hub.inbox_status",
            "state": "needs_attention" if invalid_pending else ("pending" if pending else ("processing" if processing else "idle")),
            "directories": {
                "inbox": str(inbox),
                "outbox": str(outbox),
                "archive": str(archive),
            },
            "counts": {
                "pending": len(pending),
                "processing": len(processing),
                "invalid_pending": len(invalid_pending),
                "valid_pending": len(pending_summaries) - len(invalid_pending),
                "recent_outputs": len(outputs),
                "archived": len(archived),
            },
            "queue_health": {
                "ready_to_process": bool(pending_summaries) and not invalid_pending,
                "oldest_pending_age_seconds": round(max(0.0, time.time() - oldest_pending), 2) if oldest_pending else 0,
                "preview_limit": 25,
                "invalid_files": [row.get("name") for row in invalid_pending[:10]],
            },
            "pending": pending_summaries,
            "processing": processing_summaries,
            "recent_outputs": [_file_summary(path) for path in outputs[:25]],
            "recent_archive": [_file_summary(path) for path in archived[:25]],
            "supported_api_shapes": list(SUPPORTED_API_SHAPES),
            "submission": {
                "endpoint": "/v1/inbox/submit",
                "method": "POST",
                "accepted_payloads": ["native task/input/prompt", "native messages", "openai-chat messages", "anthropic-messages"],
                "optional_fields": ["task_id", "api_shape", "response_shape", "agent_mode"],
            },
            "commands": {
                "process_once": "python -m agent_hub once",
                "watch": "python -m agent_hub watch",
                "serve_with_watcher": "python -m agent_hub serve --watch-inbox",
                "submit_api": "POST /v1/inbox/submit",
            },
            "operational_readiness": _inbox_operational_readiness(
                invalid_count=len(invalid_pending),
                has_dirs=all(path.exists() for path in (inbox, outbox, archive)),
            ),
        }

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

    def enterprise_status_body(self) -> dict[str, Any]:
        policy = EnterprisePolicy.from_config(self.config)
        audit = export_enterprise_audit(
            self.config.state_dir,
            limit=1000,
            retention_days=getattr(self.config, "enterprise_audit_retention_days", None),
        )
        invalid_roles = sorted(
            {
                role
                for user in policy.users.values()
                for role in user.roles
                if role not in policy.roles
            }
        )
        users_without_roles = sorted(user.id for user in policy.users.values() if not user.roles)
        workspaces_without_paths = sorted(
            workspace.id for workspace in policy.workspaces.values() if not workspace.path
        )
        warnings = []
        if policy.enabled and not policy.users:
            warnings.append("Enterprise mode is enabled but no users are configured.")
        if invalid_roles:
            warnings.append("Users reference undefined roles: " + ", ".join(invalid_roles))
        if users_without_roles:
            warnings.append("Users without roles: " + ", ".join(users_without_roles))
        if workspaces_without_paths:
            warnings.append("Workspaces without paths: " + ", ".join(workspaces_without_paths))
        allowed = sum(1 for event in audit["events"] if event.get("allowed") is True)
        denied = sum(1 for event in audit["events"] if event.get("allowed") is False)
        return {
            "object": "agent_hub.enterprise_status",
            "enabled": policy.enabled,
            "state": (
                "disabled"
                if not policy.enabled
                else "needs_configuration"
                if warnings
                else "ready"
            ),
            "summary": {
                "users": len(policy.users),
                "roles": len(policy.roles),
                "workspaces": len(policy.workspaces),
                "grants": len(policy.grants),
                "audit_events": audit["count"],
                "allowed_decisions": allowed,
                "denied_decisions": denied,
                "warning_count": len(warnings),
            },
            "default_workspace_id": policy.default_workspace_id,
            "warnings": warnings,
            "policy_coverage": _enterprise_policy_coverage(policy),
            "operational_readiness": _enterprise_operational_readiness(
                policy=policy,
                warnings=warnings,
                audit_count=int(audit.get("count", 0) or 0),
            ),
            "users": [user.to_dict() for user in policy.users.values()],
            "roles": [role.to_dict() for role in policy.roles.values()],
            "workspaces": [workspace.to_dict() for workspace in policy.workspaces.values()],
            "grants": [grant.to_dict() for grant in policy.grants],
        }

    def active_provider_names(self, router: Any) -> list[str]:
        health = router.health_snapshot()
        return _active_names(self.config, health)

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
        "route_ready": _route_ready_health(agent, health),
        "route_ready_reason": _route_ready_reason(agent, health),
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


def _agent_baseline_score(agent: AgentConfig, health: dict[str, Any]) -> float:
    components = _agent_baseline_components(agent, health)
    score = sum(float(value) for value in components.values())
    return round(max(0.0, min(1.0, score)), 4)


def _agent_baseline_components(agent: AgentConfig, health: dict[str, Any]) -> dict[str, float]:
    configured_quality = max(
        0.0,
        min(
            1.0,
            (
                float(agent.coding_score or 0.5)
                + float(agent.reasoning_score or 0.5)
                + float(agent.speed_score or 0.5)
            )
            / 3,
        ),
    )
    capability_count = sum(
        1
        for value in (
            agent.supports_tools,
            agent.supports_json,
            agent.supports_streaming,
            agent.supports_function_calling,
        )
        if value is True
    )
    cost_known = bool(
        agent.free
        or (
            agent.cost_per_million_input is not None
            and agent.cost_per_million_output is not None
        )
    )
    available = bool(health.get("available")) if isinstance(health, dict) else False
    latency = _float(health.get("average_latency_ms")) if isinstance(health, dict) else None
    latency_component = 0.08 if latency is None or latency <= 0 else max(0.0, min(0.08, 0.08 - (latency / 120_000)))
    return {
        "configured_quality": round(configured_quality * 0.44, 4),
        "enabled": 0.14 if agent.enabled else 0.0,
        "health_available": 0.14 if available else 0.07,
        "capabilities": round((capability_count / 4) * 0.12, 4),
        "cost_known_or_free": 0.08 if cost_known else 0.0,
        "latency_prior": round(latency_component, 4),
    }


def _pricing_catalog(config: HubConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, agent in sorted(config.agents.items()):
        input_price = _float(agent.cost_per_million_input)
        output_price = _float(agent.cost_per_million_output)
        if bool(agent.free):
            status = "free"
            sample_cost = 0.0
        elif input_price is not None and output_price is not None:
            status = "priced"
            sample_cost = round((input_price / 1000) + (output_price / 2000), 8)
        elif input_price is not None or output_price is not None:
            status = "partial"
            sample_cost = None
        else:
            status = "missing"
            sample_cost = None
        rows.append(
            {
                "agent": name,
                "provider": agent.provider,
                "model": agent.model,
                "enabled": bool(agent.enabled),
                "free": bool(agent.free),
                "pricing_status": status,
                "cost_per_million_input": input_price,
                "cost_per_million_output": output_price,
                "sample_estimate": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "estimated_cost_usd": sample_cost,
                },
            }
        )
    return rows


def _benchmark_report_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary")
    if isinstance(summary, dict) and summary:
        return summary
    comparison = _dict(payload.get("comparison"))
    outcomes = _dict(payload.get("outcome_metrics"))
    baseline = _dict(payload.get("baseline"))
    agent_hub_summary = _dict(payload.get("agent_hub_summary"))
    baseline_summary = _dict(payload.get("baseline_summary"))
    if payload.get("object") == "agent_hub.benchmark_proof" or comparison:
        return {
            "object": payload.get("object", ""),
            "route": payload.get("route", ""),
            "task_count": payload.get("task_count", 0),
            "winner": "Agent-Hub routing",
            "baseline": baseline,
            "agent_hub_summary": agent_hub_summary,
            "baseline_summary": baseline_summary,
            "comparison": {
                "token_reduction": comparison.get("token_reduction"),
                "cost_reduction": comparison.get("cost_reduction"),
                "latency_reduction": comparison.get("latency_reduction"),
                "success_delta": comparison.get("success_delta"),
                "average_score_delta": comparison.get("average_score_delta"),
                "prompt_loops_avoided": comparison.get("prompt_loops_avoided"),
                "total_tokens_delta": comparison.get("total_tokens_delta"),
                "total_cost_delta_usd": comparison.get("total_cost_delta_usd"),
                "average_latency_delta_ms": comparison.get("average_latency_delta_ms"),
            },
            "outcome_metrics": outcomes,
        }
    return {}


def _benchmark_coverage_snapshot(
    config: HubConfig,
    scores: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    routed_agents = {
        name
        for route in config.routes
        for name in route.agents
    } | set(config.default_route)
    rows: list[dict[str, Any]] = []
    for name, agent in sorted(config.agents.items()):
        score = scores.get(name, {}) if isinstance(scores.get(name), dict) else {}
        sample_count = int(score.get("sample_count", 0) or 0)
        task_scores = _dict(score.get("task_scores"))
        readiness_components = {
            "enabled": 25 if agent.enabled else 0,
            "routed": 25 if name in routed_agents else 0,
            "provider_and_model": 20 if agent.provider and agent.model else 0,
            "capabilities_declared": 10
            if any(
                value is not None
                for value in (
                    agent.supports_tools,
                    agent.supports_json,
                    agent.supports_streaming,
                    agent.supports_function_calling,
                )
            )
            else 0,
            "pricing_declared": 10
            if agent.free
            or (
                agent.cost_per_million_input is not None
                and agent.cost_per_million_output is not None
            )
            else 0,
            "measured_outcomes": 10 if sample_count else 0,
        }
        rows.append(
            {
                "agent": name,
                "provider": agent.provider,
                "model": agent.model,
                "enabled": bool(agent.enabled),
                "routed": name in routed_agents,
                "sample_count": sample_count,
                "overall_score": score.get("overall_score"),
                "average_latency_ms": score.get("average_latency_ms"),
                "task_scores": task_scores,
                "task_types_measured": sorted(task_scores),
                "measurement_status": "measured" if sample_count else "configured_baseline",
                "benchmark_readiness_score": sum(readiness_components.values()),
                "readiness_components": readiness_components,
            }
        )
    return {
        "object": "agent_hub.benchmark_coverage_snapshot",
        "source": "configuration_and_provider_score_store",
        "measured": any(int(row["sample_count"]) > 0 for row in rows),
        "summary": {
            "agent_count": len(rows),
            "enabled_agent_count": sum(1 for row in rows if row["enabled"]),
            "routed_agent_count": sum(1 for row in rows if row["routed"]),
            "measured_agent_count": sum(1 for row in rows if int(row["sample_count"]) > 0),
            "average_readiness_score": round(
                sum(float(row["benchmark_readiness_score"]) for row in rows) / max(1, len(rows)),
                2,
            ),
        },
        "results": rows,
    }


def _benchmark_operational_readiness(
    snapshot: dict[str, Any],
    reports: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = _dict(snapshot.get("summary"))
    agent_count = int(summary.get("agent_count", 0) or 0)
    enabled_count = int(summary.get("enabled_agent_count", 0) or 0)
    routed_count = int(summary.get("routed_agent_count", 0) or 0)
    measured_count = int(summary.get("measured_agent_count", 0) or 0)
    average_score = float(summary.get("average_readiness_score", 0.0) or 0.0)
    checks = [
        _readiness_check("agents_configured", agent_count > 0, f"{agent_count} agent(s) in coverage snapshot."),
        _readiness_check("enabled_agents", enabled_count > 0, f"{enabled_count} enabled agent(s)."),
        _readiness_check("routed_agents", routed_count > 0, f"{routed_count} routed agent(s)."),
        _readiness_check("coverage_snapshot", average_score >= 50, f"Average readiness score {average_score:.1f}/100."),
        _readiness_check(
            "measured_outcomes",
            bool(reports or measured_count),
            f"{len(reports)} report(s), {measured_count} measured snapshot agent(s).",
            required=False,
        ),
    ]
    return _operational_readiness(checks, baseline_rating=8.5)


def _benchmark_measurement_plan(config: HubConfig, snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = snapshot.get("results") if isinstance(snapshot.get("results"), list) else []
    unmeasured = [
        str(row.get("agent"))
        for row in rows
        if row.get("agent") and int(row.get("sample_count", 0) or 0) == 0
    ]
    route_names = [route.name for route in config.routes] or ["coding"]
    preferred_route = "coding" if "coding" in route_names else route_names[0]
    return {
        "object": "agent_hub.benchmark_measurement_plan",
        "preferred_route": preferred_route,
        "unmeasured_agents": unmeasured[:25],
        "commands": [
            f"python -m agent_hub benchmark-suite --route {preferred_route} --limit 24 --json",
            f"python -m agent_hub eval --route {preferred_route} --limit 6 --json",
        ],
        "safe_to_run": "Provider calls may be made; review configured routes and free_only before running.",
    }


def _production_checks(
    config: HubConfig,
    router: Any,
    provider_health: dict[str, dict[str, Any]],
    setup_guidance: dict[str, Any],
    plugins: dict[str, Any],
    readiness: dict[str, Any],
    dashboards: dict[str, dict[str, Any]],
    *,
    runtime_usability: dict[str, Any],
) -> list[dict[str, Any]]:
    active_names = _active_names(config, provider_health)
    recommendations = router.recommend(
        HubRequest(
            session_id="production-check",
            route="cloud-agent",
            messages=[{"role": "user", "content": "select a production-ready model"}],
            record_session=False,
        ),
        limit=8,
        needs_tools=True,
        include_unavailable=True,
    )
    feature_contract = _extension_feature_contract()
    security = _security_readiness_item(config)
    dashboards_ok = all(
        _dict(body.get("summary")).get("data_state") or body.get("object")
        for body in dashboards.values()
    )
    unavailable_without_reason = [
        row.get("agent")
        for row in recommendations
        if isinstance(row, dict)
        and row.get("available") is False
        and not (row.get("unavailable_reason") or row.get("why"))
    ]
    readiness_warnings = int(_dict(readiness.get("summary")).get("warning_count", 0) or 0)
    compatibility_metadata_hidden = not config.expose_routing_details
    checks = [
        _production_check(
            "runtime_usability",
            "Runtime usability is verified",
            str(runtime_usability.get("state") or "") == "ready",
            20,
            severity="critical",
            detail=(
                f"Runtime usability {runtime_usability.get('score', 0)}/100 "
                f"({runtime_usability.get('state', 'unknown')})."
            ),
            command=_dict(runtime_usability.get("next_step")).get("command"),
        ),
        _production_check(
            "readiness_score",
            "Readiness score is production-grade",
            int(readiness.get("score", 0) or 0) >= 90 and readiness.get("state") == "production_ready",
            15,
            severity="major",
            detail=f"Readiness {readiness.get('score', 0)}/100 ({readiness.get('state', 'unknown')}).",
            command=(readiness.get("next_step") or {}).get("command")
            if isinstance(readiness.get("next_step"), dict)
            else None,
        ),
        _production_check(
            "route_ready_provider",
            "At least one provider is route-ready",
            bool(active_names),
            20,
            severity="critical",
            detail=(
                "Ready provider(s): " + ", ".join(active_names[:8])
                if active_names
                else "No enabled provider currently reports as available."
            ),
            command=None if active_names else "python -m agent_hub doctor --providers",
        ),
        _production_check(
            "security_guardrails",
            "Security guardrails are production-safe",
            security.get("status") == "ok",
            20,
            severity="critical",
            detail=str(security.get("detail") or ""),
            command=security.get("command"),
        ),
        _production_check(
            "dashboard_contracts",
            "Dashboards return structured summaries and empty states",
            dashboards_ok,
            8,
            severity="major",
            detail="Cost, leaderboard, and benchmark dashboards expose summary data.",
        ),
        _production_check(
            "feature_maturity_honesty",
            "Feature maturity states are explicit",
            all(key in readiness.get("feature_status", {}) for key in _FEATURE_STATUS_KEYS),
            8,
            severity="major",
            detail="Ready, baseline, policy-gated, opt-in, and needs-action states are exposed.",
        ),
        _production_check(
            "vscode_backend_contract",
            "VS Code required backend features are present",
            bool(feature_contract.get("ok")),
            10,
            severity="major",
            detail=str(feature_contract.get("detail") or ""),
            metadata=feature_contract,
        ),
        _production_check(
            "recommendation_honesty",
            "Unavailable recommendations explain why",
            not unavailable_without_reason,
            7,
            severity="major",
            detail=(
                "All unavailable recommendation rows include a reason."
                if not unavailable_without_reason
                else "Missing unavailable reasons for: " + ", ".join(str(name) for name in unavailable_without_reason[:8])
            ),
        ),
        _production_check(
            "setup_guidance_actionable",
            "Setup guidance has a next action when blocked",
            bool(setup_guidance.get("ready")) or isinstance(setup_guidance.get("next_step"), dict),
            5,
            severity="major",
            detail=(
                "Setup is ready."
                if setup_guidance.get("ready")
                else str((_dict(setup_guidance.get("next_step")).get("detail") or "Setup guidance has a next step."))
            ),
            command=_dict(setup_guidance.get("next_step")).get("command"),
        ),
        _production_check(
            "plugin_policy_honesty",
            "Plugin and MCP state is policy-gated and explicit",
            _dict(readiness.get("feature_status")).get("plugins", {}).get("state") in {
                "foundation",
                "execution_enabled",
                "discovery_ready",
                "trusted_local_process_enabled",
                "disabled",
                "needs_manifest_fixes",
            },
            4,
            severity="evidence",
            detail=str(_dict(readiness.get("feature_status")).get("plugins", {}).get("state") or "unknown"),
            metadata={"plugin_count": plugins.get("count", 0)},
        ),
        _production_check(
            "public_bind_auth",
            "Public bind cannot run without API auth",
            not public_bind_host(str(config.host or "")) or bool(api_token(config)),
            3,
            severity="critical",
            detail=(
                "Localhost bind does not require API auth."
                if not public_bind_host(str(config.host or ""))
                else "Public bind has API auth configured."
                if api_token(config)
                else "Public bind is missing api_auth_token/api_auth_token_env."
            ),
            command="Set api_auth_token or api_auth_token_env before binding publicly."
            if public_bind_host(str(config.host or "")) and not api_token(config)
            else None,
        ),
        _production_check(
            "readiness_warnings",
            "Readiness warnings are resolved",
            readiness_warnings == 0,
            5,
            severity="evidence",
            detail=(
                "No readiness warnings remain."
                if readiness_warnings == 0
                else f"{readiness_warnings} readiness warning(s) remain."
            ),
            command=_dict(readiness.get("next_step")).get("command"),
        ),
        _production_check(
            "compatibility_metadata_policy",
            "Compatibility responses hide internal routing metadata",
            compatibility_metadata_hidden,
            5,
            severity="evidence",
            detail=(
                "Internal routing details are hidden unless explicitly requested."
                if compatibility_metadata_hidden
                else "expose_routing_details=true makes compatibility responses larger and reveals internal routing metadata."
            ),
            command=(
                None
                if compatibility_metadata_hidden
                else "Set expose_routing_details=false for production compatibility endpoints."
            ),
        ),
    ]
    return checks


_FEATURE_STATUS_KEYS = {
    "provider_routing",
    "universal_compatibility",
    "setup_guidance",
    "security",
    "model_leaderboard",
    "benchmark_results_dashboard",
    "cost_dashboard",
    "autonomous_night_mode",
    "workspace_agent_tools",
    "team_agent_mode",
    "adaptive_learning",
    "repository_intelligence",
    "json_inbox",
    "enterprise_governance",
    "plugins",
    "external_mcp_bridge",
}


def _feature_scorecard_areas(
    config: HubConfig,
    *,
    provider_health: dict[str, dict[str, Any]],
    readiness: dict[str, Any],
    production: dict[str, Any],
    extension: dict[str, Any],
    inbox: dict[str, Any],
    plugins: dict[str, Any],
    mcp: dict[str, Any],
    provider_type_count: int,
) -> list[dict[str, Any]]:
    feature_status = _dict(readiness.get("feature_status"))
    active_names = _active_names(config, provider_health)
    production_ok = bool(production.get("ok"))
    extension_contract = _dict(extension.get("contract"))
    extension_ok = bool(extension_contract.get("ok"))
    inbox_readiness = _dict(inbox.get("operational_readiness"))
    plugin_readiness = _dict(plugins.get("operational_readiness"))
    mcp_readiness = _dict(mcp.get("operational_readiness"))
    return [
        _feature_area(
            "model_routing",
            "Model routing",
            [
                _feature_check("provider_selection", BACKEND_FEATURES["provider_route_readiness_policy"], "Provider route readiness policy is implemented."),
                _feature_check("free_only_policy", isinstance(config.free_only, bool), f"free_only={config.free_only}."),
                _feature_check("failover", BACKEND_FEATURES["quota_aware_failover"], "Quota-aware failover is implemented."),
                _feature_check("health_metrics", BACKEND_FEATURES["provider_health_metrics"], "Provider latency/reliability health metrics are implemented."),
                _feature_check("recommendations", BACKEND_FEATURES["model_recommendations"], "Model recommendation API/CLI is implemented."),
                _feature_check("explainability", BACKEND_FEATURES["routing_intelligence_api"], "Route diagnosis and explanation APIs are implemented."),
                _feature_check("route_ready_provider", bool(active_names), f"{len(active_names)} route-ready provider(s)."),
            ],
            "Local routing is fully provable when at least one configured provider is route-ready; third-party cloud uptime remains external.",
        ),
        _feature_area(
            "provider_support",
            "Provider support",
            [
                _feature_check("universal_provider_compatibility", BACKEND_FEATURES["universal_provider_compatibility"], "Universal provider adapter contract is enabled."),
                _feature_check("provider_presets", BACKEND_FEATURES["provider_presets"], "Editable provider presets are bundled."),
                _feature_check("provider_registry_size", provider_type_count >= 20, f"{provider_type_count} known provider type(s)."),
                _feature_check("local_and_cloud_mix", bool(config.agents), f"{len(config.agents)} configured agent definition(s)."),
                _feature_check("provider_evaluation", BACKEND_FEATURES["provider_evaluation"], "Provider eval/calibration paths are implemented."),
            ],
            "The codebase proves broad adapter/preset coverage; live provider calls require credentials and network access.",
        ),
        _feature_area(
            "api_compatibility",
            "API compatibility",
            [
                _feature_check("openai_chat", BACKEND_FEATURES["openai_tool_call_passthrough"], "OpenAI chat and tool-call passthrough are implemented."),
                _feature_check("openai_responses", BACKEND_FEATURES["transparent_openai_responses"], "OpenAI Responses compatibility is implemented."),
                _feature_check("anthropic_messages", BACKEND_FEATURES["anthropic_messages_compatibility"], "Anthropic Messages compatibility is implemented."),
                _feature_check("openrouter_path", BACKEND_FEATURES["openrouter_style_api_path"], "OpenRouter-style API path is implemented."),
                _feature_check("model_aliases", BACKEND_FEATURES["agent_hub_model_aliases"], "Agent Hub model aliases are implemented."),
                _feature_check("universal_routing", universal_compatibility_enabled(config), "Universal compatibility mode is enabled."),
            ],
            "Compatibility shapes are locally testable without paid providers.",
        ),
        _feature_area(
            "workspace_agent",
            "Workspace agent",
            [
                _feature_check("single_agent", BACKEND_FEATURES["tool_execution_loop"], "Workspace agent tool loop is implemented."),
                _feature_check("group_agent", BACKEND_FEATURES["team_agent_mode"], "Group-agent mode is implemented."),
                _feature_check("file_tools", BACKEND_FEATURES["file_write_tools"], "File read/write/search tooling is implemented."),
                _feature_check("apply_patch", BACKEND_FEATURES["multi_file_apply_patch"], "Multi-file apply-patch support is implemented."),
                _feature_check("validation_repair", BACKEND_FEATURES["validation_repair_loops"], "Validation repair loops are implemented."),
                _feature_check("checkpoints", BACKEND_FEATURES["workspace_checkpoints"], "Workspace checkpoints are implemented."),
                _feature_check("rollback", BACKEND_FEATURES["workspace_rollback_api"], "Workspace rollback API is implemented."),
                _feature_check("mutations_guarded", config.approval_mode in {"ask", "safe", "readonly", "deny"}, f"approval_mode={config.approval_mode}."),
            ],
            "Real edit quality depends on the selected model, but the agent runtime and safety contract are locally provable.",
        ),
        _feature_area(
            "context_intelligence",
            "Context intelligence",
            [
                _feature_check("repo_aware", BACKEND_FEATURES["repo_aware_coding"], "Repository-aware coding is implemented."),
                _feature_check("active_file_resolution", BACKEND_FEATURES["active_file_context_resolution"], "Active file resolution is implemented."),
                _feature_check("token_budget", BACKEND_FEATURES["central_token_budget_manager"], "Central token budgeting is implemented."),
                _feature_check("compaction", BACKEND_FEATURES["agent_context_compaction"] and config.agent_context_compaction_enabled, "Agent context compaction is enabled."),
                _feature_check("cline_preservation", BACKEND_FEATURES["cline_compatibility_mode"] and config.cline_compatibility_mode, "Cline compatibility/context preservation is enabled."),
                _feature_check("protected_categories", BACKEND_FEATURES["protected_context_categories"], "Protected context categories are implemented."),
            ],
            "The context engine is local-first; very large repositories still benefit from real-world workload sampling.",
        ),
        _feature_area(
            "safety_security",
            "Safety/security",
            [
                _feature_check("safe_mode", BACKEND_FEATURES["safe_mode"] and config.approval_mode != "auto", f"approval_mode={config.approval_mode}."),
                _feature_check("public_auth_guard", BACKEND_FEATURES["mandatory_public_api_auth"], "Public bind authentication guard is implemented."),
                _feature_check("provider_gate", BACKEND_FEATURES["provider_permission_gate"], "Provider permission gate is implemented."),
                _feature_check("secret_detection", BACKEND_FEATURES["secret_detection"] and config.secret_scanning_enabled, "Secret scanning is enabled."),
                _feature_check("prompt_injection", BACKEND_FEATURES["prompt_injection_defense"] and config.prompt_injection_defense_enabled, "Prompt-injection defense is enabled."),
                _feature_check("command_classifier", BACKEND_FEATURES["tool_security_classifier"], "Tool security classifier is implemented."),
            ],
            "This is strong product security evidence, not a substitute for an external security audit.",
        ),
        _feature_area(
            "dashboards_control_plane",
            "Dashboards/control plane",
            [
                _feature_check("status_endpoints", BACKEND_FEATURES["dashboard_status_endpoints"], "Status dashboard endpoints are implemented."),
                _feature_check("readiness", BACKEND_FEATURES["readiness_scorecard"], "Readiness scorecard is implemented."),
                _feature_check("production_check", BACKEND_FEATURES["production_acceptance_check"] and production.get("object") == "agent_hub.production_check", f"production_check_ok={production_ok}."),
                _feature_check("runtime_kernel", BACKEND_FEATURES["runtime_kernel_control_plane"] and BACKEND_FEATURES["runtime_kernel_durable_history"], "Runtime kernel control plane and durable history are implemented."),
                _feature_check("events", BACKEND_FEATURES["events_endpoint"], "Events endpoint is implemented."),
                _feature_check("feature_scorecard", BACKEND_FEATURES["feature_scorecard"], "Feature scorecard endpoint/dashboard is implemented."),
            ],
            "Dashboards are strongest after real usage accumulates, but their structured surfaces and empty states are locally provable.",
        ),
        _feature_area(
            "vscode_extension",
            "VS Code extension",
            [
                _feature_check("contract_endpoint", BACKEND_FEATURES["extension_contract_endpoint"], "Backend extension contract endpoint is implemented."),
                _feature_check("required_features_present", extension_ok, str(extension_contract.get("detail") or "")),
                _feature_check("readiness_surface", BACKEND_FEATURES["vscode_readiness_surface"], "VS Code readiness surface is implemented."),
                _feature_check("runtime_kernel_command", BACKEND_FEATURES["runtime_kernel_dashboard"], "Runtime Kernel dashboard command is supported."),
            ],
            "Static and contract proof is local; true visual polish still benefits from VS Code manual/visual QA.",
        ),
        _feature_area(
            "config_install_release",
            "Config/install/release",
            [
                _feature_check("automatic_init", BACKEND_FEATURES["automatic_config_initialization"], "Automatic config initialization is implemented."),
                _feature_check("config_migration", BACKEND_FEATURES["config_migration"], "Config migration tooling is implemented."),
                _feature_check("utf8_bom_config", BACKEND_FEATURES["utf8_bom_config_loading"], "UTF-8 BOM JSON config loading is supported."),
                _feature_check("production_acceptance", BACKEND_FEATURES["production_acceptance_check"], "Production acceptance check is implemented."),
                _feature_check("deployment_templates", BACKEND_FEATURES["deployment_templates"], "Docker/deployment templates are present."),
            ],
            "Local install/release readiness is provable; actual marketplace publishing remains an external release operation.",
        ),
        _feature_area(
            "inbox_workflows",
            "Inbox/workflows",
            [
                _feature_check("json_inbox", BACKEND_FEATURES["json_inbox_processing"], "JSON inbox processing is implemented."),
                _feature_check("inbox_status", BACKEND_FEATURES["inbox_status_reporting"], "Inbox status reporting is implemented."),
                _feature_check("inbox_submit", BACKEND_FEATURES["inbox_submission_api"], "Inbox submission API is implemented."),
                _feature_check("deterministic_workflows", BACKEND_FEATURES["deterministic_workflows"], "Deterministic workflows are implemented."),
                _feature_check("auto_workflow", BACKEND_FEATURES["auto_workflow_selection"], "Auto workflow selection is implemented."),
                _feature_check("night_mode_validation", BACKEND_FEATURES["autonomous_night_mode_validation"], "Night-mode validation reports are implemented."),
                _feature_check("inbox_readiness", float(inbox_readiness.get("rating") or 0.0) >= 8.5, f"inbox readiness rating={inbox_readiness.get('rating')}.", required=False),
            ],
            "Long autonomous runs still need workload-specific proof, but bounded workflow surfaces are locally testable.",
        ),
        _feature_area(
            "plugins_mcp_enterprise",
            "Plugins/MCP/enterprise",
            [
                _feature_check("plugin_sdk", BACKEND_FEATURES["plugin_sdk_foundation"], "Plugin SDK foundation is implemented."),
                _feature_check("signed_manifests", BACKEND_FEATURES["signed_plugin_manifests"], "Signed plugin manifest support is implemented."),
                _feature_check("plugin_sandbox", BACKEND_FEATURES["plugin_sandbox_foundation"], "Plugin sandbox foundation is implemented."),
                _feature_check("mcp_status", BACKEND_FEATURES["mcp_status_dashboard"], "MCP status dashboard is implemented."),
                _feature_check("mcp_tools", BACKEND_FEATURES["mcp_tool_compatibility_layer"], "MCP tool compatibility layer is implemented."),
                _feature_check("enterprise_audit", BACKEND_FEATURES["enterprise_audit_logs"], "Enterprise audit logs are implemented."),
                _feature_check("enterprise_status", BACKEND_FEATURES["enterprise_status"], "Enterprise status endpoint is implemented."),
                _feature_check("plugin_readiness", float(plugin_readiness.get("rating") or 0.0) >= 8.5, f"plugin readiness rating={plugin_readiness.get('rating')}."),
                _feature_check("mcp_readiness", float(mcp_readiness.get("rating") or 0.0) >= 8.5, f"mcp readiness rating={mcp_readiness.get('rating')}."),
            ],
            "Execution remains opt-in by design; policy-gated foundations are locally provable.",
        ),
        _feature_area(
            "evaluation_proof_cost",
            "Evaluation/proof/cost",
            [
                _feature_check("provider_evaluation", BACKEND_FEATURES["provider_evaluation"], "Provider evaluation is implemented."),
                _feature_check("model_performance_database", BACKEND_FEATURES["model_performance_database"], "Model performance database is implemented."),
                _feature_check("model_leaderboard", BACKEND_FEATURES["model_leaderboard"], "Model leaderboard is implemented."),
                _feature_check("cost_dashboard", BACKEND_FEATURES["cost_dashboard"], "Cost dashboard is implemented."),
                _feature_check("benchmark_dashboard", BACKEND_FEATURES["benchmark_results_dashboard"], "Benchmark results dashboard is implemented."),
                _feature_check("structured_feedback", BACKEND_FEATURES["structured_user_feedback"], "Structured feedback collection is implemented."),
            ],
            "Meaningful savings/quality claims still depend on measured benchmark and usage data; the proof infrastructure is complete locally.",
        ),
    ]


def _feature_area(
    area_id: str,
    area: str,
    checks: list[dict[str, Any]],
    honest_take: str,
) -> dict[str, Any]:
    required = [check for check in checks if check.get("required", True)]
    passed = sum(1 for check in required if check.get("ok"))
    rating = round((passed / max(1, len(required))) * 10.0, 1)
    return {
        "id": area_id,
        "area": area,
        "rating": rating,
        "state": "local_10_of_10" if rating == 10.0 else "needs_attention",
        "passed_required": passed,
        "required_count": len(required),
        "honest_take": honest_take,
        "checks": checks,
    }


def _feature_check(
    check_id: str,
    ok: bool,
    detail: str,
    *,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "ok": bool(ok),
        "required": bool(required),
        "detail": detail,
    }


def _production_check(
    check_id: str,
    label: str,
    ok: bool,
    weight: int,
    *,
    severity: str,
    detail: str,
    command: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": check_id,
        "label": label,
        "ok": bool(ok),
        "status": "ok" if ok else "fail",
        "severity": severity,
        "weight": weight,
        "earned": weight if ok else 0,
        "detail": detail,
    }
    if command and not ok:
        item["command"] = command
    if metadata:
        item["metadata"] = metadata
    return item


def _extension_feature_contract() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    extension_path = root / "vscode-extension" / "extension.js"
    if not extension_path.exists():
        return {
            "ok": True,
            "available": False,
            "detail": "VS Code extension source is not bundled in this install.",
            "required": [],
            "missing": [],
        }
    try:
        source = extension_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "ok": False,
            "available": True,
            "detail": f"Could not read VS Code extension source: {exc}",
            "required": [],
            "missing": [],
        }
    match = re.search(r"const REQUIRED_BACKEND_FEATURES = \[(?P<body>.*?)\];", source, re.DOTALL)
    if not match:
        return {
            "ok": False,
            "available": True,
            "detail": "VS Code extension does not declare REQUIRED_BACKEND_FEATURES.",
            "required": [],
            "missing": [],
        }
    required = sorted(set(re.findall(r'"([^"]+)"', match.group("body"))))
    missing = [feature for feature in required if BACKEND_FEATURES.get(feature) is not True]
    return {
        "ok": not missing,
        "available": True,
        "detail": (
            f"{len(required)} required backend feature(s) are present."
            if not missing
            else "Missing backend features: " + ", ".join(missing)
        ),
        "required": required,
        "required_count": len(required),
        "missing": missing,
    }


def _readiness_items(
    config: HubConfig,
    provider_health: dict[str, dict[str, Any]],
    setup_guidance: dict[str, Any],
    plugins: dict[str, Any],
    runtime_usability: dict[str, Any],
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
        _runtime_usability_readiness_item(runtime_usability),
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


def _runtime_usability_readiness_item(runtime_usability: dict[str, Any]) -> dict[str, Any]:
    state = str(runtime_usability.get("state") or "unknown")
    score = int(_float(runtime_usability.get("score")) or 0)
    next_step = _dict(runtime_usability.get("next_step"))
    if state == "ready":
        status = "ok"
        earned = 20
    elif state == "degraded":
        status = "warn"
        earned = 12
    else:
        status = "action"
        earned = 0
    return _readiness_item(
        "runtime_usability",
        "Runtime usability is verified",
        status,
        20,
        earned,
        (
            f"Runtime usability {score}/100 ({state}). "
            + str(runtime_usability.get("title") or "")
        ).strip(),
        next_step.get("command") or "agent-hub checkup --fix-safe --verify",
    )


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
    baseline_agents = int(leaderboard_summary.get("baseline_agent_count", 0) or 0)
    benchmark_reports = int(benchmark_summary.get("report_count", 0) or 0)
    benchmark_snapshot_rows = int(benchmark_summary.get("snapshot_result_count", 0) or 0)
    has_leaderboard_data = measured_agents > 0
    has_benchmark_data = benchmark_reports > 0
    if has_leaderboard_data and has_benchmark_data:
        status = "ok"
        earned = 10
        detail = f"{measured_agents} measured agent(s), {benchmark_reports} benchmark report(s)."
        command = None
    elif baseline_agents and benchmark_snapshot_rows:
        status = "ok"
        earned = 8.5
        detail = (
            f"{baseline_agents} baseline-ranked agent(s) and "
            f"{benchmark_snapshot_rows} benchmark coverage row(s); measured outcomes pending."
        )
        command = "Run python -m agent_hub benchmark-suite --route coding --limit 24 --json."
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
        "night validation runner": True,
    }
    missing = [label for label, ok in controls.items() if not ok]
    earned = 10 * ((len(controls) - len(missing)) / len(controls))
    detail = "Advanced routing intelligence is enabled."
    if missing:
        detail = "Disabled: " + ", ".join(missing) + "."
    elif not config.autonomous_night_mode_enabled:
        detail = "Advanced routing is enabled; night validation runner is available and opt-in."
    return _readiness_item(
        "advanced_intelligence",
        "Advanced intelligence is usable and honest",
        "ok" if not missing else "warn",
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
            "Plugin and MCP integrations are policy-gated",
            "warn",
            5,
            2,
            "Plugin discovery is disabled.",
            "Set plugins_enabled=true to inspect plugin manifests.",
        )
    if errors:
        return _readiness_item(
            "plugins_integrations",
            "Plugin and MCP integrations are policy-gated",
            "warn",
            5,
            3,
            f"{len(errors)} plugin discovery error(s) need attention.",
            "Check /v1/plugins for manifest errors.",
        )
    if config.plugin_execution_enabled:
        return _readiness_item(
            "plugins_integrations",
            "Plugin and MCP integrations are policy-gated",
            "ok",
            5,
            5,
            "Plugin discovery and execution policy are enabled.",
        )
    return _readiness_item(
        "plugins_integrations",
        "Plugin and MCP integrations are policy-gated",
        "ok",
        5,
        5,
        "Plugin manifests, trust policy, and opt-in local-process execution contract are available.",
    )


def _feature_status(
    config: HubConfig,
    provider_health: dict[str, dict[str, Any]],
    setup_guidance: dict[str, Any],
    plugins: dict[str, Any],
    runtime_usability: dict[str, Any],
    *,
    leaderboard: dict[str, Any],
    benchmarks: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    active_names = _active_names(config, provider_health)
    blocked = _blocked_provider_rows(config, provider_health)
    route_ready_detail = ", ".join(active_names[:8]) if active_names else "No provider reports as route-ready."
    if blocked:
        route_ready_detail += " Blocked: " + "; ".join(
            f"{row['agent']}: {row['reason']}" for row in blocked[:4]
        )
    leaderboard_summary = _dict(leaderboard.get("summary"))
    benchmark_summary = _dict(benchmarks.get("summary"))
    plugin_errors = plugins.get("errors") if isinstance(plugins.get("errors"), list) else []
    mcp_summary = _mcp_policy_summary(config)
    readiness_mcp_state = mcp_summary["state"]
    if readiness_mcp_state == "not_configured":
        readiness_mcp_state = "execution_disabled"
    tool_count = 4 + int(mcp_summary["declared_tool_count"])
    return {
        "provider_routing": {
            "state": "ready" if active_names else "needs_setup",
            "detail": route_ready_detail,
            "active_count": len(active_names),
            "blocked_count": len(blocked),
            "blocked": blocked[:8],
        },
        "runtime_usability": {
            "state": runtime_usability.get("state") or "unknown",
            "score": runtime_usability.get("score", 0),
            "rating": runtime_usability.get("rating", 0.0),
            "ready": bool(runtime_usability.get("ready")),
            "verified_coding_providers": runtime_usability.get("verified_coding_providers", []),
            "next_step": runtime_usability.get("next_step"),
            "detail": runtime_usability.get("title") or "Runtime usability has not been checked.",
        },
        "contract_readiness": {
            "state": "ready",
            "detail": "Local feature contracts, routes, adapters, dashboards, and policies are implemented.",
        },
        "universal_compatibility": {
            "state": "ready" if universal_compatibility_enabled(config) else "disabled",
            "request_shapes": ["native", "openai-chat", "openai-responses", "anthropic-messages"],
            "provider_adapters": ["openai", "openai-compatible", "anthropic", "gemini"],
            "tool_emulation_enabled": tool_emulation_enabled(config),
            "detail": (
                "All supported request shapes can route across provider adapters; "
                "native tools are preferred and text-only models use labeled emulation."
                if universal_compatibility_enabled(config)
                else "Universal cross-provider routing is disabled by compatibility_mode."
            ),
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
            "operational_readiness": benchmarks.get("operational_readiness"),
        },
        "cost_dashboard": {
            "state": "coverage_ready",
            "detail": "Pricing coverage and sample estimates are available; measured totals require priced usage data.",
        },
        "autonomous_night_mode": {
            "state": "validation_ready" if config.autonomous_night_mode_enabled else "available_disabled",
            "detail": (
                "Night mode can run bounded validation commands without editing files."
                if config.autonomous_night_mode_enabled
                else "Night validation runner is installed and disabled by default."
            ),
            "validation_commands": list(config.validation_commands or []),
            "execution_mode": "validation_only",
            "operational_readiness": _operational_readiness(
                [
                    _readiness_check("plan_endpoint_available", True, "GET /v1/night-mode exposes a validation plan."),
                    _readiness_check("run_endpoint_available", True, "POST /v1/night-mode/run writes bounded run reports."),
                    _readiness_check("writes_blocked", True, "Night mode is validation-only and does not edit files."),
                    _readiness_check("human_review_required", True, "Human review is required before applying fixes."),
                    _readiness_check("enabled", config.autonomous_night_mode_enabled, f"autonomous_night_mode_enabled={config.autonomous_night_mode_enabled}.", required=False),
                    _readiness_check("validation_commands_configured", bool(config.validation_commands), f"{len(config.validation_commands or [])} configured command(s).", required=False),
                ],
                baseline_rating=8.5,
            ),
        },
        "workspace_agent_tools": {
            "state": "ready" if tool_count >= 4 else "needs_tools",
            "registered_tool_count": tool_count,
            "builtin_tools": ["file_read", "file_write", "search_repo", "shell_execute"],
            "shell_policy": config.shell_command_policy,
            "shell_tools_enabled": bool(config.allow_shell_tools),
            "mutating_tools_guarded": config.approval_mode in {"ask", "safe", "readonly", "deny"},
            "detail": "Workspace tools are registered; mutating and shell operations are policy-gated.",
        },
        "team_agent_mode": {
            "state": "ready",
            "patterns": ["planner", "researcher", "coder", "reviewer", "finalizer"],
            "max_steps": config.agent_max_steps,
            "detail": "Single-agent, group-agent, and workflow engine paths share router and provider health state.",
        },
        "adaptive_learning": {
            "state": "ready" if config.adaptive_learning_enabled and config.routing_memory_enabled else "disabled",
            "adaptive_learning_enabled": config.adaptive_learning_enabled,
            "adaptive_routing_enabled": config.adaptive_routing_enabled,
            "routing_memory_enabled": config.routing_memory_enabled,
            "feedback_endpoint": "/v1/feedback",
            "detail": "Routing memory, feedback, simulation, and optimization dashboards are available.",
        },
        "repository_intelligence": {
            "state": "ready" if config.repository_dna_enabled and config.workspace_memory_enabled else "disabled",
            "repository_dna_enabled": config.repository_dna_enabled,
            "workspace_memory_enabled": config.workspace_memory_enabled,
            "failure_prediction_enabled": config.failure_prediction_enabled,
            "detail": "Repository DNA and workspace memory are exposed to routing and dashboards.",
        },
        "json_inbox": {
            "state": "ready",
            "inbox_dir": str(config.inbox_dir),
            "outbox_dir": str(config.outbox_dir),
            "archive_dir": str(config.archive_dir),
            "supported_api_shapes": ["native", "openai-chat", "anthropic-messages"],
            "detail": "JSON task inbox supports one-shot processing, watcher mode, and serve --watch-inbox.",
        },
        "enterprise_governance": {
            "state": "ready" if config.enterprise_mode_enabled else "disabled",
            "audit_retention_days": config.enterprise_audit_retention_days,
            "detail": "Enterprise policy and audit exports are available; enforcement is active when enterprise_mode_enabled=true.",
            "operational_readiness": _enterprise_operational_readiness(
                policy=EnterprisePolicy.from_config(config),
                warnings=[],
                audit_count=0,
            ),
        },
        "plugins": {
            "state": (
                "disabled"
                if not config.plugins_enabled
                else ("needs_manifest_fixes" if plugin_errors else "trusted_local_process_enabled" if config.plugin_execution_enabled else "discovery_ready")
            ),
            "count": plugins.get("count", 0),
            "errors": len(plugin_errors),
            "registered_count": plugins.get("registered_count", 0),
            "execution_enabled": config.plugin_execution_enabled,
            "operational_readiness": plugins.get("operational_readiness"),
        },
        "external_mcp_bridge": {
            "state": readiness_mcp_state,
            "detail": mcp_summary["detail"],
            "configured_server_count": mcp_summary["configured_server_count"],
            "declared_tool_count": mcp_summary["declared_tool_count"],
            "execution_enabled": mcp_summary["execution_enabled"],
            "operational_readiness": mcp_summary.get("operational_readiness"),
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
        if _route_ready_health(agent, provider_health.get(name, {}))
    ]


def _blocked_provider_rows(
    config: HubConfig,
    provider_health: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, agent in sorted(config.agents.items()):
        if not agent.enabled:
            continue
        health = provider_health.get(name, {})
        if _route_ready_health(agent, health):
            continue
        rows.append(
            {
                "agent": name,
                "provider": agent.provider,
                "model": agent.model,
                "reason": _route_ready_reason(agent, health),
            }
        )
    return rows


def _route_ready_health(agent: Any, health: Any) -> bool:
    return _route_ready_reason(agent, health) == ""


def _route_ready_reason(agent: Any, health: Any) -> str:
    if not getattr(agent, "enabled", False):
        return "agent disabled"
    if not isinstance(health, dict) or not health.get("available"):
        return "provider unavailable"
    now = time.time()
    cooldown = _float(health.get("cooldown_until")) or 0.0
    unavailable = _float(health.get("unavailable_until")) or 0.0
    if max(cooldown, unavailable) > now:
        return "provider cooling down"
    if bool(health.get("quota_exhausted")):
        return "quota exhausted"
    if bool(health.get("rate_limited")):
        return "rate limited"
    for field in ("requests_remaining", "quota_remaining", "credits_remaining"):
        remaining = _float(health.get(field))
        if remaining is not None and remaining <= 0:
            return field.replace("_", " ") + " exhausted"
    return ""


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _file_summary(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"name": path.name, "path": str(path), "missing": True}
    return {
        "name": path.name,
        "path": str(path),
        "bytes": stat.st_size,
        "modified_at": stat.st_mtime,
    }


def _readiness_check(
    check_id: str,
    ok: bool,
    detail: str,
    *,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "ok": bool(ok),
        "required": bool(required),
        "detail": detail,
    }


def _operational_readiness(
    checks: list[dict[str, Any]],
    *,
    baseline_rating: float = 8.5,
) -> dict[str, Any]:
    required = [check for check in checks if check.get("required", True)]
    optional = [check for check in checks if not check.get("required", True)]
    required_ok = sum(1 for check in required if check.get("ok"))
    optional_ok = sum(1 for check in optional if check.get("ok"))
    required_score = required_ok / max(1, len(required))
    optional_score = optional_ok / max(1, len(optional)) if optional else 1.0
    raw_rating = (8.5 * required_score) + (1.5 * optional_score)
    rating = max(baseline_rating, raw_rating) if required_score == 1.0 else raw_rating
    if required_score == 1.0 and optional_score == 1.0:
        state = "operational"
    elif required_score == 1.0:
        state = "operational_measurements_pending"
    else:
        state = "needs_attention"
    return {
        "rating": round(min(10.0, rating), 1),
        "state": state,
        "passed_required": required_ok,
        "required_count": len(required),
        "passed_optional": optional_ok,
        "optional_count": len(optional),
        "checks": checks,
    }


def _plugin_operational_readiness(
    config: HubConfig,
    *,
    state: str,
    error_count: int,
) -> dict[str, Any]:
    checks = [
        _readiness_check(
            "discovery_enabled",
            bool(config.plugins_enabled),
            "Plugin manifest discovery is enabled.",
        ),
        _readiness_check(
            "manifest_errors_clear",
            error_count == 0,
            f"{error_count} manifest error(s).",
        ),
        _readiness_check(
            "execution_policy_explicit",
            isinstance(config.plugin_execution_enabled, bool),
            f"plugin_execution_enabled={config.plugin_execution_enabled}.",
        ),
        _readiness_check(
            "trust_registry_supported",
            True,
            "Trusted, disabled, revoked, expired, and scoped registry states are supported.",
        ),
        _readiness_check(
            "safe_validation_action",
            True,
            "POST /v1/plugins/{plugin_id}/execute with action=validate performs no code execution.",
        ),
        _readiness_check(
            "local_process_bounded",
            True,
            "Trusted local-process plugins run without a shell and with timeout/scopes.",
        ),
        _readiness_check(
            "configured_plugins_present",
            state not in {"discovery_ready", "disabled"},
            "At least one plugin is configured.",
            required=False,
        ),
    ]
    return _operational_readiness(checks, baseline_rating=8.5)


def _inbox_operational_readiness(*, invalid_count: int, has_dirs: bool) -> dict[str, Any]:
    checks = [
        _readiness_check("directories_available", has_dirs, "Inbox, outbox, and archive directories are available."),
        _readiness_check("pending_payloads_valid", invalid_count == 0, f"{invalid_count} invalid pending payload(s)."),
        _readiness_check("submit_api_available", True, "POST /v1/inbox/submit validates and queues tasks."),
        _readiness_check("preview_available", True, "Pending tasks include normalized route/session previews."),
        _readiness_check("processing_modes_available", True, "CLI once/watch and serve --watch-inbox are available."),
    ]
    return _operational_readiness(checks, baseline_rating=8.5)


def _enterprise_policy_coverage(policy: EnterprisePolicy) -> dict[str, Any]:
    permission_names = sorted(
        {
            permission
            for role in policy.roles.values()
            for permission in role.permissions
        }
        | {grant.permission for grant in policy.grants}
    )
    matrix = []
    for user in sorted(policy.users.values(), key=lambda item: item.id):
        role_permissions = sorted(
            {
                permission
                for role_name in user.roles
                for permission in policy.roles.get(role_name, RoleDefinition(role_name)).permissions
            }
        )
        grants = sorted(
            grant.permission
            for grant in policy.grants
            if grant.subject_id in {user.id, f"user:{user.id}", *[f"role:{role}" for role in user.roles]}
        )
        matrix.append(
            {
                "user": user.id,
                "roles": list(user.roles),
                "role_permissions": role_permissions,
                "direct_or_role_grants": grants,
            }
        )
    return {
        "permission_names": permission_names,
        "matrix": matrix,
        "default_workspace_id": policy.default_workspace_id,
        "audit_retention_days": None,
    }


def _enterprise_operational_readiness(
    *,
    policy: EnterprisePolicy,
    warnings: list[str],
    audit_count: int,
) -> dict[str, Any]:
    checks = [
        _readiness_check("policy_engine_available", True, "Enterprise allow/deny policy engine is available."),
        _readiness_check("audit_export_available", True, "Filtered audit export API is available."),
        _readiness_check("retention_policy_available", True, "Audit retention window is configurable."),
        _readiness_check(
            "configuration_valid",
            not warnings,
            f"{len(warnings)} configuration warning(s).",
        ),
        _readiness_check(
            "enforcement_enabled",
            bool(policy.enabled),
            f"enterprise_mode_enabled={policy.enabled}.",
            required=False,
        ),
        _readiness_check(
            "audit_events_present",
            audit_count > 0,
            f"{audit_count} retained audit event(s).",
            required=False,
        ),
    ]
    return _operational_readiness(checks, baseline_rating=8.5)


def _mcp_policy_summary(config: HubConfig) -> dict[str, Any]:
    enabled_servers = [server for server in config.mcp_servers if server.enabled]
    command_servers = [server for server in enabled_servers if server.command]
    server_rows = [_mcp_server_row(config, server) for server in config.mcp_servers]
    tool_rows = [tool for server in server_rows for tool in server["tools"]]
    warnings = [warning for server in server_rows for warning in server["warnings"]]
    declared_tools = len([tool for tool in tool_rows if tool.get("server_enabled")])
    execution_enabled = bool(config.mcp_execution_enabled)
    if not enabled_servers:
        state = "not_configured"
        detail = "No MCP servers are configured."
        next_step = "Add mcp_servers entries to agent-hub.config.json when you need external MCP tools."
    elif execution_enabled and command_servers and declared_tools:
        state = "stdio_ready"
        detail = "MCP stdio execution is enabled for configured command-backed servers."
        next_step = "Keep MCP permissions scoped to the minimum required tool capabilities."
    elif command_servers and declared_tools:
        state = "configured_execution_disabled"
        detail = "MCP tools are declared but execution is disabled by policy."
        next_step = "Set mcp_execution_enabled=true only for trusted local MCP servers."
    elif declared_tools:
        state = "metadata_only"
        detail = "MCP tools are declared, but no enabled server command can execute them."
        next_step = "Add a command for each MCP server that should run over stdio."
    else:
        state = "needs_tools"
        detail = "MCP servers are configured without declared tools."
        next_step = "Declare tools under each enabled mcp_servers entry."
    return {
        "state": state,
        "detail": detail,
        "next_step": next_step,
        "execution_enabled": execution_enabled,
        "timeout_seconds": config.mcp_timeout_seconds,
        "configured_server_count": len(config.mcp_servers),
        "enabled_server_count": len(enabled_servers),
        "command_server_count": len(command_servers),
        "declared_tool_count": declared_tools,
        "servers": server_rows,
        "tools": tool_rows,
        "warnings": warnings,
        "execution_contract": {
            "transport": "stdio",
            "initialize_method": "initialize",
            "call_method": "tools/call",
            "requires": [
                "mcp_execution_enabled=true",
                "enabled server",
                "server command configured",
                "declared tool metadata",
            ],
            "timeout_seconds": config.mcp_timeout_seconds,
        },
        "operational_readiness": _mcp_operational_readiness(config, server_rows, state),
        "maturity": {
            "state_visibility": True,
            "per_server_status": True,
            "per_tool_permissions": True,
            "stdio_policy_gate": True,
            "timeout_bounded": 1.0 <= float(config.mcp_timeout_seconds) <= 120.0,
        },
    }


def _mcp_server_row(config: HubConfig, server: Any) -> dict[str, Any]:
    tools = normalize_mcp_tools(server)
    execution_ready = bool(config.mcp_execution_enabled and server.enabled and server.command and tools)
    warnings: list[str] = []
    if not server.enabled:
        warnings.append("server disabled")
    if server.enabled and not server.command:
        warnings.append("missing command")
    if server.enabled and not tools:
        warnings.append("no declared tools")
    if server.enabled and server.command and tools and not config.mcp_execution_enabled:
        warnings.append("execution disabled by policy")
    return {
        "name": server.name,
        "enabled": bool(server.enabled),
        "command_configured": bool(server.command),
        "transport": "stdio",
        "command_preview": [str(server.command), *[str(arg) for arg in server.args]] if server.command else [],
        "execution_ready": execution_ready,
        "status": "ready" if execution_ready else ("disabled" if not server.enabled else "policy_gated" if server.command and tools else "needs_configuration"),
        "tool_count": len(tools),
        "permissions": list(server.permissions),
        "warnings": warnings,
        "tools": [
            {
                "server": definition.server,
                "server_enabled": bool(server.enabled),
                "name": definition.name,
                "qualified_name": definition.qualified_name,
                "description": definition.description,
                "permissions": list(definition.permissions),
                "read_only": "write" not in {permission.lower() for permission in definition.permissions},
                "status": "ready" if execution_ready else "execution_disabled",
                "call_example": {
                    "name": definition.qualified_name,
                    "arguments": {
                        key: ""
                        for key in sorted(str(key) for key in _dict(definition.input_schema.get("properties")).keys())
                    },
                },
                "input_properties": sorted(
                    str(key)
                    for key in _dict(definition.input_schema.get("properties")).keys()
                ),
            }
            for definition in tools
        ],
    }


def _mcp_operational_readiness(
    config: HubConfig,
    server_rows: list[dict[str, Any]],
    state: str,
) -> dict[str, Any]:
    has_errors = any(row.get("status") == "needs_configuration" for row in server_rows)
    declared_tools = sum(int(row.get("tool_count", 0) or 0) for row in server_rows if row.get("enabled"))
    command_backed = any(row.get("command_configured") for row in server_rows if row.get("enabled"))
    checks = [
        _readiness_check("status_endpoint_available", True, "GET /v1/mcp/status reports server and tool state."),
        _readiness_check("per_tool_inventory", True, "Declared tools include permissions, schemas, and call examples."),
        _readiness_check("execution_policy_explicit", isinstance(config.mcp_execution_enabled, bool), f"mcp_execution_enabled={config.mcp_execution_enabled}."),
        _readiness_check("timeout_bounded", 1.0 <= float(config.mcp_timeout_seconds) <= 120.0, f"timeout={config.mcp_timeout_seconds}s."),
        _readiness_check("configuration_without_errors", not has_errors, f"state={state}."),
        _readiness_check("declared_tools_present", declared_tools > 0, f"{declared_tools} enabled declared tool(s).", required=False),
        _readiness_check("command_backed_servers_present", command_backed, "At least one enabled server has a command.", required=False),
    ]
    return _operational_readiness(checks, baseline_rating=8.5)


def _setup_guidance(config: HubConfig, provider_health: dict[str, dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    agents = list(config.agents.values())
    enabled_agents = [agent for agent in agents if agent.enabled]
    active_agents = [
        agent
        for agent in enabled_agents
        if _route_ready_health(agent, provider_health.get(agent.name, {}))
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


def _experience_summary(
    config: HubConfig,
    *,
    provider_health: dict[str, dict[str, Any]],
    setup_guidance: dict[str, Any],
    readiness: dict[str, Any],
    context_diagnostics: dict[str, Any],
    runtime_usability: dict[str, Any],
) -> dict[str, Any]:
    active_names = _active_names(config, provider_health)
    readiness_state = str(readiness.get("state") or "")
    readiness_score = int(_float(readiness.get("score")) or 0)
    setup_next = _dict(setup_guidance.get("next_step"))
    readiness_next = _dict(readiness.get("next_step"))
    next_step = setup_next or readiness_next
    suspicious_context = bool(context_diagnostics.get("suspiciously_empty"))
    action_count = int(setup_guidance.get("action_count") or 0)
    warning_count = int(setup_guidance.get("warning_count") or 0)
    runtime_state = str(runtime_usability.get("state") or "")
    runtime_next = _dict(runtime_usability.get("next_step"))
    has_enabled_agents = any(agent.enabled for agent in config.agents.values())

    if runtime_state == "needs_server":
        state = "needs_setup"
        title = "Start Agent Hub"
        detail = runtime_next.get("detail") or "Agent Hub must be running before real route checks can pass."
        next_step = runtime_next or next_step
    elif not config.agents or not has_enabled_agents:
        state = "needs_setup"
        title = "Finish setup"
        detail = next_step.get("detail") or "Agent Hub needs a configured provider before it can verify real coding work."
    elif runtime_state in {"needs_local_model", "needs_provider_approval"}:
        state = runtime_state
        title = str(runtime_usability.get("title") or "Finish runtime setup")
        detail = runtime_next.get("detail") or "Connect or approve a coding-capable provider, then run checkup verification."
        next_step = runtime_next or next_step
    elif action_count or readiness_state == "needs_setup":
        state = "needs_setup"
        title = "Finish setup"
        detail = next_step.get("detail") or "Agent Hub needs one more setup step before it can route coding work reliably."
    elif not active_names:
        state = "needs_provider"
        title = "Connect a model provider"
        detail = "Agent Hub is running, but no enabled provider is currently route-ready."
        if not next_step:
            next_step = _setup_item(
                "route_ready",
                "action",
                "Make a provider route-ready",
                "Check API keys, local model servers, or provider cooldowns.",
                "python -m agent_hub doctor --providers",
            )
    elif suspicious_context:
        state = "needs_context"
        title = "Check tool context"
        detail = "A recent coding-tool request reached Agent Hub with very little workspace context."
        if not next_step:
            next_step = _setup_item(
                "tool_context",
                "warn",
                "Send workspace context",
                "Open a workspace file and retry from Cline or the Agent Hub sidebar.",
            )
    elif runtime_state == "degraded" or warning_count or readiness_score < 90:
        state = "ready_with_warnings"
        title = "Ready with notes"
        detail = runtime_next.get("detail") or next_step.get("detail") or "Agent Hub can answer tasks, but one readiness note should be reviewed."
        next_step = runtime_next or next_step
    else:
        state = "ready"
        title = "Ready for coding tasks"
        detail = "Send a task from the sidebar or use Cline with model agent-hub-coding."

    primary_action = None
    if next_step:
        primary_action = {
            "id": next_step.get("id") or "next_step",
            "label": next_step.get("label") or "Review next step",
            "detail": next_step.get("detail") or "",
        }
        if next_step.get("command"):
            primary_action["command"] = next_step.get("command")
    elif state == "ready":
        primary_action = {
            "id": "send_task",
            "label": "Send a task",
            "detail": "Use the sidebar prompt or Cline model agent-hub-coding.",
        }

    client_host = str(config.host or "127.0.0.1")
    if client_host in {"0.0.0.0", "::"}:
        client_host = "127.0.0.1"
    return {
        "object": "agent_hub.experience_summary",
        "state": state,
        "title": title,
        "detail": detail,
        "readiness_score": readiness_score,
        "primary_action": primary_action,
        "coding_tool": {
            "provider": "openai-compatible",
            "base_url": f"http://{client_host}:{config.port}/v1",
            "api_key": "agent-hub-local",
            "model": "agent-hub-coding",
            "cline_compatibility_mode": bool(config.cline_compatibility_mode),
        },
        "checks": {
            "providers_configured": bool(config.agents),
            "providers_enabled": any(agent.enabled for agent in config.agents.values()),
            "route_ready_provider": bool(active_names),
            "safe_permissions": config.approval_mode != "auto",
            "context_healthy": not suspicious_context,
            "runtime_ready": runtime_state == "ready",
        },
        "runtime_usability": {
            "state": runtime_state,
            "score": runtime_usability.get("score", 0),
            "next_step": runtime_usability.get("next_step"),
        },
    }


def _repository_identity(config: HubConfig) -> dict[str, Any]:
    root = Path(config.workspace_dir).resolve()
    return {
        "name": root.name,
        "path": str(root),
        "state_dir": str(Path(config.state_dir)),
    }


__all__ = ["BACKEND_FEATURES", "BACKEND_VERSION", "DiagnosticsApplicationService"]
