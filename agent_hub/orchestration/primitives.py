from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


PrimitiveKind = Literal["stage", "branch", "join", "vote", "critique", "retry", "escalate", "rollback"]


@dataclass(frozen=True, slots=True)
class AgentRole:
    id: str
    label: str
    purpose: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "purpose": self.purpose}


@dataclass(frozen=True, slots=True)
class OrchestrationPrimitive:
    kind: PrimitiveKind
    description: str
    requires_validation_gate: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "description": self.description,
            "requires_validation_gate": self.requires_validation_gate,
        }


@dataclass(slots=True)
class OrchestrationPlan:
    stages: list[OrchestrationPrimitive]
    roles: list[AgentRole] = field(default_factory=list)
    max_concurrency: int = 1
    token_budget: int | None = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.max_concurrency < 1:
            errors.append("max_concurrency_must_be_positive")
        if self.token_budget is not None and self.token_budget < 1:
            errors.append("token_budget_must_be_positive")
        if not self.stages:
            errors.append("orchestration_plan_requires_stages")
        if any(stage.kind == "rollback" for stage in self.stages) and not any(
            stage.requires_validation_gate for stage in self.stages
        ):
            errors.append("rollback_requires_validation_gate")
        return errors

    def to_dict(self) -> dict[str, object]:
        return {
            "object": "agent_hub.orchestration_plan",
            "valid": not self.validate(),
            "errors": self.validate(),
            "max_concurrency": self.max_concurrency,
            "token_budget": self.token_budget,
            "roles": [role.to_dict() for role in self.roles],
            "stages": [stage.to_dict() for stage in self.stages],
        }


def default_agent_roles() -> list[AgentRole]:
    return [
        AgentRole("planner", "Planner", "Breaks the task into verifiable steps."),
        AgentRole("researcher", "Researcher", "Collects evidence and repository context."),
        AgentRole("coder", "Coder", "Implements scoped code changes."),
        AgentRole("reviewer", "Reviewer", "Checks behavior, tests, and maintainability."),
        AgentRole("security_reviewer", "Security Reviewer", "Checks privacy, policy, and unsafe actions."),
        AgentRole("validator", "Validator", "Runs proof, tests, and acceptance checks."),
        AgentRole("documentation_writer", "Documentation Writer", "Updates user-facing docs."),
        AgentRole("finalizer", "Finalizer", "Summarizes outcome and remaining risk."),
    ]


def default_orchestration_primitives() -> list[OrchestrationPrimitive]:
    return [
        OrchestrationPrimitive("stage", "Run a single ordered unit of work."),
        OrchestrationPrimitive("branch", "Run bounded parallel alternatives."),
        OrchestrationPrimitive("join", "Merge branch outputs into one state."),
        OrchestrationPrimitive("vote", "Select among candidate outputs."),
        OrchestrationPrimitive("critique", "Review output against task criteria.", True),
        OrchestrationPrimitive("retry", "Repeat a failed stage with bounded attempts."),
        OrchestrationPrimitive("escalate", "Move to a stronger model, role, or workflow.", True),
        OrchestrationPrimitive("rollback", "Restore a checkpoint after validation failure.", True),
    ]
