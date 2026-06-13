from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from ..config import HubConfig
from ..models import HubRequest
from ..observability import recent_events
from ..repository_intelligence import (
    build_autonomous_night_mode_plan,
    build_cost_optimizer_summary,
    build_failure_prediction,
    build_model_performance_database,
)
from ..workflows import WorkflowSelector, with_workflow_selection_raw


class AdaptiveApplicationService:
    """Application boundary for auto workflow and adaptive learning endpoints."""

    def __init__(
        self,
        config: HubConfig,
        *,
        router: Any,
        agent_runner: Any,
        team_agent_runner: Any,
        workflow_engine: Any,
    ) -> None:
        self.config = config
        self.router = router
        self.agent_runner = agent_runner
        self.team_agent_runner = team_agent_runner
        self.workflow_engine = workflow_engine

    def optimization_summary(self) -> dict[str, Any]:
        summary = self.router.adaptive_learning.optimization_summary()
        summary["adaptive_learning_enabled"] = bool(self.config.adaptive_learning_enabled)
        summary["adaptive_routing_enabled"] = bool(self.config.adaptive_routing_enabled)
        summary["adaptive_workflow_upgrades_enabled"] = bool(
            self.config.adaptive_workflow_upgrades_enabled
        )
        summary["routing_memory"] = self.router.routing_memory.stats()
        summary["cost_optimizer"] = build_cost_optimizer_summary(
            routing_events=recent_events(self.config.state_dir, "routing", limit=1000)
        )
        try:
            dna = self.router.repository_intelligence.repository_dna()
            summary["repository_dna"] = dna.to_dict()
            summary["workspace_memory"] = self.router.repository_intelligence.workspace_memory()
            summary["model_performance_database"] = build_model_performance_database(
                optimization=summary,
                routing_memory=summary["routing_memory"],
                dna=dna,
            )
            summary["autonomous_night_mode"] = build_autonomous_night_mode_plan(
                dna=dna,
                config=self.config,
            )
        except Exception:
            summary["repository_dna"] = {}
            summary["workspace_memory"] = {}
        return summary

    def record_feedback_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        request_id = str(payload.get("request_id") or payload.get("id") or "").strip()
        rating = str(payload.get("rating") or "").strip().lower()
        reason = str(payload.get("reason") or payload.get("feedback_reason") or "").strip().lower()
        workflow_success = payload.get("workflow_success")
        if not request_id:
            return (
                {"error": {"message": "request_id is required", "type": "invalid_feedback"}},
                400,
            )
        if workflow_success is not None and not isinstance(workflow_success, bool):
            return (
                {
                    "error": {
                        "message": "workflow_success must be boolean when provided",
                        "type": "invalid_feedback",
                    }
                },
                400,
            )
        try:
            result = self.router.adaptive_learning.record_feedback(
                request_id=request_id,
                rating=rating,
                workflow_success=workflow_success,
            )
        except ValueError as exc:
            return {"error": {"message": str(exc), "type": "invalid_feedback"}}, 400
        memory = self.router.routing_memory.record_feedback(
            request_id=request_id,
            rating=rating,
            reason=reason,
        )
        status = 200 if result.get("matched") else 404
        return {
            "object": "agent_hub.feedback",
            **result,
            "reason": reason,
            "routing_memory": memory,
        }, status

    def simulate_request(self, request: HubRequest) -> dict[str, Any]:
        """Dry-run auto workflow and router choices without provider calls."""

        selection = WorkflowSelector(self.config).select(request)
        auto_request = replace(
            request,
            raw=with_workflow_selection_raw(request, selection),
            stream=False,
            record_session=False,
        )
        decision = self.router.decide(auto_request)
        recommendations = self.router.recommend(
            auto_request,
            limit=10,
            include_unavailable=True,
        )
        role_plan = [
            {
                **role,
                "candidates": self.router.recommend(
                    _role_request(auto_request, role["role"], role["prefer"]),
                    limit=5,
                    needs_tools=role.get("needs_tools"),
                    prefer=role["prefer"],
                    include_unavailable=True,
                ),
            }
            for role in _workflow_role_plan(selection.pattern)
        ]
        optimization = self.optimization_summary()
        dna = optimization.get("repository_dna") if isinstance(optimization.get("repository_dna"), dict) else {}
        routing_events = recent_events(self.config.state_dir, "routing", limit=250)
        failure_prediction = build_failure_prediction(
            decision=decision,
            workflow_selection=selection.to_dict(),
            config=self.config,
        )
        debate_plan = _debate_plan(role_plan, selection.pattern)
        repair_loop = _repair_loop_plan(self.config)
        cost_optimizer = build_cost_optimizer_summary(
            decision=decision,
            routing_events=routing_events,
        )
        model_performance = build_model_performance_database(
            optimization=optimization,
            routing_memory=optimization.get("routing_memory", {}),
            dna=dna,
        )
        return {
            "object": "agent_hub.routing_simulation",
            "dry_run": True,
            "message": "No provider request was sent and no adaptive state was changed.",
            "route": auto_request.route,
            "workflow_selection": selection.to_dict(),
            "routing_decision": decision.to_dict(),
            "repository_dna": dna,
            "workspace_memory": optimization.get("workspace_memory", {}),
            "failure_prediction": failure_prediction,
            "debate_plan": debate_plan,
            "multi_agent_debate": debate_plan,
            "auto_repair_loop": repair_loop,
            "cost_optimizer": cost_optimizer,
            "model_performance_database": model_performance,
            "autonomous_night_mode": build_autonomous_night_mode_plan(dna=dna, config=self.config),
            "ai_team_visualization": _ai_team_visualization(role_plan, failure_prediction),
            "recommendations": recommendations,
            "role_plan": role_plan,
            "optimization": optimization,
        }

    def execute_auto(self, request: HubRequest) -> Any:
        selection = WorkflowSelector(self.config).select(request)
        auto_request = replace(
            request,
            raw=with_workflow_selection_raw(request, selection),
            stream=False,
        )
        started = time.perf_counter()
        if selection.pattern == "direct_route":
            response = self.router.route(auto_request)
        elif selection.pattern == "single_worker":
            response = self.agent_runner.run(auto_request)
        elif selection.pattern == "team_reviewed":
            response = self.team_agent_runner.run(auto_request)
        else:
            response = self.workflow_engine.execute(
                selection.workflow_kind,
                auto_request,
            ).response
        response = _with_workflow_selection_metadata(response, selection.to_dict())
        if self.config.adaptive_learning_enabled:
            self.router.adaptive_learning.record_workflow_result(
                request_id=response.request_id,
                pattern=selection.pattern,
                task_type=selection.task_type,
                success=_auto_response_success(response),
                latency_seconds=time.perf_counter() - started,
                recovered_by_failover=bool(response.failover),
                final_status=_auto_final_status(response),
                agent=response.agent,
                provider=response.provider,
                model=response.model,
                retry_count=_auto_retry_count(response),
            )
        return response


def _with_workflow_selection_metadata(response: Any, selection: dict[str, Any]) -> Any:
    raw = dict(response.raw) if isinstance(getattr(response, "raw", None), dict) else {}
    hub = dict(raw.get("agent_hub")) if isinstance(raw.get("agent_hub"), dict) else {}
    hub["workflow_selection"] = selection
    hub["workflow_pattern"] = selection.get("pattern")
    raw["agent_hub"] = hub
    return replace(response, raw=raw)


def _auto_final_status(response: Any) -> str:
    hub = response.raw.get("agent_hub") if isinstance(getattr(response, "raw", None), dict) else {}
    workflow = hub.get("workflow") if isinstance(hub, dict) else None
    state = workflow.get("state") if isinstance(workflow, dict) else None
    if isinstance(state, dict) and isinstance(state.get("final_status"), str):
        return state["final_status"]
    return "completed" if str(getattr(response, "text", "") or "").strip() else "empty"


def _auto_response_success(response: Any) -> bool:
    if _auto_final_status(response) == "blocked":
        return False
    hub = response.raw.get("agent_hub") if isinstance(getattr(response, "raw", None), dict) else {}
    workflow = hub.get("workflow") if isinstance(hub, dict) else None
    state = workflow.get("state") if isinstance(workflow, dict) else None
    validation = state.get("validation_result") if isinstance(state, dict) else None
    if isinstance(validation, dict) and validation.get("ok") is False:
        return False
    return bool(str(getattr(response, "text", "") or "").strip())


def _auto_retry_count(response: Any) -> int:
    hub = response.raw.get("agent_hub") if isinstance(getattr(response, "raw", None), dict) else {}
    workflow = hub.get("workflow") if isinstance(hub, dict) else None
    state = workflow.get("state") if isinstance(workflow, dict) else None
    workflow_retries = int(state.get("retries", 0)) if isinstance(state, dict) else 0
    return max(0, workflow_retries) + len(getattr(response, "failover", []) or [])


def _workflow_role_plan(pattern: str) -> list[dict[str, Any]]:
    if pattern == "direct_route":
        return []
    if pattern == "single_worker":
        return [{"role": "worker", "prefer": "coding", "needs_tools": True}]
    if pattern == "planned_worker":
        return [
            {"role": "planner", "prefer": "reasoning", "needs_tools": False},
            {"role": "coder", "prefer": "coding", "needs_tools": True},
        ]
    if pattern == "team_reviewed":
        return [
            {"role": "planner", "prefer": "reasoning", "needs_tools": False},
            {"role": "researcher", "prefer": "reasoning", "needs_tools": True},
            {"role": "worker_candidate", "prefer": "coding", "needs_tools": False},
            {"role": "judge", "prefer": "reasoning", "needs_tools": False},
            {"role": "coder", "prefer": "coding", "needs_tools": True},
            {"role": "reviewer", "prefer": "reasoning", "needs_tools": False},
            {"role": "finalizer", "prefer": "reasoning", "needs_tools": False},
        ]
    return [
        {"role": "planner", "prefer": "reasoning", "needs_tools": False},
        {"role": "coder", "prefer": "coding", "needs_tools": True},
        {"role": "reviewer", "prefer": "reasoning", "needs_tools": False},
    ]


def _role_request(request: HubRequest, role: str, prefer: str) -> HubRequest:
    raw = dict(request.raw) if isinstance(request.raw, dict) else {}
    hub = dict(raw.get("agent_hub")) if isinstance(raw.get("agent_hub"), dict) else {}
    hub["workflow_role"] = role
    hub["prefer"] = prefer
    raw["agent_hub"] = hub
    raw["workflow_role"] = role
    raw["prefer"] = prefer
    return replace(request, raw=raw, preferred_agent=None)


def _debate_plan(role_plan: list[dict[str, Any]], pattern: str) -> dict[str, Any]:
    worker = next((role for role in role_plan if role.get("role") == "worker_candidate"), None)
    candidates = worker.get("candidates") if isinstance(worker, dict) and isinstance(worker.get("candidates"), list) else []
    judge = next((role for role in role_plan if role.get("role") == "judge"), None)
    judge_candidates = judge.get("candidates") if isinstance(judge, dict) and isinstance(judge.get("candidates"), list) else []
    judge_model = judge_candidates[0] if judge_candidates else {}
    return {
        "enabled": pattern == "team_reviewed",
        "candidate_count": len(candidates),
        "candidates": [
            {
                "agent": row.get("agent"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "score": row.get("score"),
                "available": row.get("available"),
            }
            for row in candidates[:4]
            if isinstance(row, dict)
        ],
        "judge": {
            "agent": judge_model.get("agent"),
            "provider": judge_model.get("provider"),
            "model": judge_model.get("model"),
        },
        "selection_policy": "4 candidates -> automatic code review -> best implementation returned",
    }


def _repair_loop_plan(config: HubConfig) -> dict[str, Any]:
    return {
        "enabled": bool(config.auto_validate_after_edits),
        "pattern": "Generate -> Verify -> Repair",
        "max_attempts": int(config.validation_repair_attempts or 0),
        "validation_mode": config.validation_mode,
        "validation_commands": list(config.validation_commands),
        "rollback_on_validation_failure": bool(config.rollback_on_validation_failure),
    }


def _ai_team_visualization(role_plan: list[dict[str, Any]], prediction: dict[str, Any]) -> dict[str, Any]:
    role_labels = {
        "planner": "Planner",
        "researcher": "Researcher",
        "worker_candidate": "Debate",
        "judge": "Judge",
        "coder": "Coder",
        "reviewer": "Reviewer",
        "finalizer": "Finalizer",
        "worker": "Worker",
    }
    steps = []
    for index, role in enumerate(role_plan, start=1):
        candidates = role.get("candidates") if isinstance(role.get("candidates"), list) else []
        selected = candidates[0] if candidates else {}
        steps.append(
            {
                "index": index,
                "role": role.get("role"),
                "label": role_labels.get(str(role.get("role")), str(role.get("role") or "Role").title()),
                "status": "planned",
                "candidate_count": len(candidates),
                "agent": selected.get("agent") if isinstance(selected, dict) else "",
                "provider": selected.get("provider") if isinstance(selected, dict) else "",
                "model": selected.get("model") if isinstance(selected, dict) else "",
            }
        )
    if not steps:
        steps.append(
            {
                "index": 1,
                "role": "router",
                "label": "Router",
                "status": "planned",
                "candidate_count": 1,
            }
        )
    return {
        "object": "agent_hub.ai_team_visualization",
        "steps": steps,
        "estimated_time_seconds": prediction.get("estimated_time_seconds"),
        "estimated_cost_usd": prediction.get("estimated_cost_usd"),
        "chance_of_success": prediction.get("chance_of_success"),
    }


__all__ = ["AdaptiveApplicationService"]
