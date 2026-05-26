from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProviderCallPlan:
    """Declarative hook for future parallel provider calls."""

    agent_names: list[str] = field(default_factory=list)
    role: str = "worker"
    parallel: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_names": list(self.agent_names),
            "role": self.role,
            "parallel": self.parallel,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class RoleStrategy:
    """Maps workflow roles to preferred agents without executing them."""

    assignments: dict[str, str] = field(default_factory=dict)

    def agent_for(self, role: str, available_agents: list[str]) -> str | None:
        assigned = self.assignments.get(role)
        if assigned in available_agents:
            return assigned
        return available_agents[0] if available_agents else None

    def to_dict(self) -> dict[str, Any]:
        return {"assignments": dict(self.assignments)}


@dataclass(slots=True)
class ConsensusStrategy:
    """Configuration shell for future voting or agreement strategies."""

    name: str = "first_success"
    min_votes: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "min_votes": max(1, int(self.min_votes)),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class MergeStrategy:
    """Configuration shell for future result merging."""

    name: str = "best_score"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "metadata": dict(self.metadata)}


@dataclass(slots=True)
class WorkflowExtensionPoints:
    provider_calls: list[ProviderCallPlan] = field(default_factory=list)
    roles: RoleStrategy = field(default_factory=RoleStrategy)
    consensus: ConsensusStrategy = field(default_factory=ConsensusStrategy)
    merge: MergeStrategy = field(default_factory=MergeStrategy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_calls": [plan.to_dict() for plan in self.provider_calls],
            "roles": self.roles.to_dict(),
            "consensus": self.consensus.to_dict(),
            "merge": self.merge.to_dict(),
        }


__all__ = [
    "ConsensusStrategy",
    "MergeStrategy",
    "ProviderCallPlan",
    "RoleStrategy",
    "WorkflowExtensionPoints",
]
