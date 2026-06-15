from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .primitives import AgentRole, OrchestrationPrimitive, default_agent_roles


@dataclass(frozen=True, slots=True)
class SwarmStage:
    id: str
    primitive: str
    roles: list[str] = field(default_factory=list)
    max_parallel: int = 1
    token_budget: int | None = None
    validation_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "primitive": self.primitive,
            "roles": list(self.roles),
            "max_parallel": self.max_parallel,
            "token_budget": self.token_budget,
            "validation_required": self.validation_required,
        }


@dataclass(slots=True)
class BoundedSwarmPlan:
    goal: str
    stages: list[SwarmStage]
    roles: list[AgentRole] = field(default_factory=default_agent_roles)
    max_concurrency: int = 2
    token_budget: int | None = None
    dry_run: bool = True

    def validate(self) -> list[str]:
        errors: list[str] = []
        role_ids = {role.id for role in self.roles}
        if self.max_concurrency < 1:
            errors.append("max_concurrency_must_be_positive")
        if self.max_concurrency > 8:
            errors.append("max_concurrency_exceeds_safe_limit")
        if self.token_budget is not None and self.token_budget < 1:
            errors.append("token_budget_must_be_positive")
        if not self.stages:
            errors.append("swarm_plan_requires_stages")
        for stage in self.stages:
            if stage.max_parallel < 1:
                errors.append(f"{stage.id}:max_parallel_must_be_positive")
            if stage.max_parallel > self.max_concurrency:
                errors.append(f"{stage.id}:max_parallel_exceeds_plan_concurrency")
            for role in stage.roles:
                if role not in role_ids:
                    errors.append(f"{stage.id}:unknown_role:{role}")
            if stage.primitive in {"vote", "critique", "rollback"} and not stage.validation_required:
                errors.append(f"{stage.id}:validation_gate_required")
        if not self.dry_run:
            errors.append("live_swarm_execution_not_enabled")
        return errors

    def to_dict(self) -> dict[str, Any]:
        errors = self.validate()
        return {
            "object": "agent_hub.bounded_swarm_plan",
            "valid": not errors,
            "errors": errors,
            "dry_run": self.dry_run,
            "goal": self.goal,
            "max_concurrency": self.max_concurrency,
            "token_budget": self.token_budget,
            "roles": [role.to_dict() for role in self.roles],
            "stages": [stage.to_dict() for stage in self.stages],
            "execution_policy": "dry_run_only",
        }


def bounded_swarm_plan_from_payload(payload: dict[str, Any]) -> BoundedSwarmPlan:
    payload = payload if isinstance(payload, dict) else {}
    goal = str(payload.get("goal") or payload.get("task") or "").strip()
    max_concurrency = _int_with_default(payload.get("max_concurrency"), 2)
    token_budget = _optional_int(payload.get("token_budget"))
    stages = _stages_from_payload(payload.get("stages"))
    if not stages:
        stages = default_swarm_stages()
    return BoundedSwarmPlan(
        goal=goal,
        stages=stages,
        max_concurrency=max_concurrency,
        token_budget=token_budget,
        dry_run=bool(payload.get("dry_run", True)),
    )


def default_swarm_stages() -> list[SwarmStage]:
    return [
        SwarmStage("plan", "stage", ["planner"], max_parallel=1),
        SwarmStage("research", "branch", ["researcher", "security_reviewer"], max_parallel=2),
        SwarmStage("implement", "stage", ["coder"], max_parallel=1),
        SwarmStage("review", "critique", ["reviewer", "validator"], max_parallel=2, validation_required=True),
        SwarmStage("finalize", "join", ["finalizer"], max_parallel=1),
    ]


def _stages_from_payload(value: Any) -> list[SwarmStage]:
    if not isinstance(value, list):
        return []
    stages: list[SwarmStage] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        roles = [str(role) for role in item.get("roles", []) if isinstance(role, str)]
        stages.append(
            SwarmStage(
                id=str(item.get("id") or f"stage-{index + 1}"),
                primitive=str(item.get("primitive") or "stage"),
                roles=roles,
                max_parallel=_int_with_default(item.get("max_parallel"), 1),
                token_budget=_optional_int(item.get("token_budget")),
                validation_required=bool(item.get("validation_required", False)),
            )
        )
    return stages


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_with_default(value: Any, default: int) -> int:
    parsed = _optional_int(value)
    return default if parsed is None else parsed


__all__ = [
    "BoundedSwarmPlan",
    "SwarmStage",
    "bounded_swarm_plan_from_payload",
    "default_swarm_stages",
]
