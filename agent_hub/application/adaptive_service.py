from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from ..config import HubConfig
from ..models import HubRequest
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
        return summary

    def record_feedback_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        request_id = str(payload.get("request_id") or payload.get("id") or "").strip()
        rating = str(payload.get("rating") or "").strip().lower()
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
        status = 200 if result.get("matched") else 404
        return {"object": "agent_hub.feedback", **result}, status

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
        return {
            "object": "agent_hub.routing_simulation",
            "dry_run": True,
            "message": "No provider request was sent and no adaptive state was changed.",
            "route": auto_request.route,
            "workflow_selection": selection.to_dict(),
            "routing_decision": decision.to_dict(),
            "recommendations": recommendations,
            "role_plan": role_plan,
            "optimization": self.optimization_summary(),
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
    hub = dict(raw.get("agent_hub") or {})
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
    raw = dict(request.raw or {})
    hub = dict(raw.get("agent_hub") or {})
    hub["workflow_role"] = role
    hub["prefer"] = prefer
    raw["agent_hub"] = hub
    raw["workflow_role"] = role
    raw["prefer"] = prefer
    return replace(request, raw=raw, preferred_agent=None)


__all__ = ["AdaptiveApplicationService"]
