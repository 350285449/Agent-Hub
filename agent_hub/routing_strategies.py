from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class RoutingDecisionContext:
    """Read-only context shape exposed to routing strategy plugins."""

    route: str = ""
    task_type: str = "general"
    api_shape: str = ""
    needs_tools: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "task_type": self.task_type,
            "api_shape": self.api_shape,
            "needs_tools": self.needs_tools,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RoutingStrategyDescriptor:
    id: str
    label: str
    routing_mode: str
    description: str
    fallback_policy: dict[str, Any] = field(default_factory=dict)
    score_weights: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_profile(self, *, source: str = "builtin") -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "routing_mode": self.routing_mode,
            "description": self.description,
            "fallback_policy": dict(self.fallback_policy),
            "metadata": {
                "strategy_id": self.id,
                "score_weights": dict(self.score_weights),
                **dict(self.metadata),
            },
            "source": source,
        }

    def explain(self, context: RoutingDecisionContext | None = None) -> dict[str, Any]:
        return {
            "strategy": self.id,
            "routing_mode": self.routing_mode,
            "score_weights": dict(self.score_weights),
            "fallback_policy": dict(self.fallback_policy),
            "decision_context": context.to_dict() if context else {},
        }


class RoutingStrategy(Protocol):
    descriptor: RoutingStrategyDescriptor

    def explain(self, context: RoutingDecisionContext) -> dict[str, Any]:
        ...


class StaticRoutingStrategy:
    def __init__(self, descriptor: RoutingStrategyDescriptor) -> None:
        self.descriptor = descriptor

    def explain(self, context: RoutingDecisionContext) -> dict[str, Any]:
        return self.descriptor.explain(context)


BUILTIN_ROUTING_STRATEGIES: dict[str, RoutingStrategyDescriptor] = {
    "coding": RoutingStrategyDescriptor(
        id="coding",
        label="Coding",
        routing_mode="coding",
        description="Prefer strong coding models with ordinary failover.",
        fallback_policy={"max_provider_attempts": 5, "order": "ranked"},
        score_weights={"coding": 1.0, "tools": 0.35, "latency": 0.15, "cost": 0.1},
    ),
    "research": RoutingStrategyDescriptor(
        id="research",
        label="Research",
        routing_mode="best_available",
        description="Prefer quality and long-context providers for investigation.",
        fallback_policy={"max_provider_attempts": 5, "order": "ranked"},
        score_weights={"reasoning": 0.8, "context_window": 0.5, "latency": 0.1},
    ),
    "private": RoutingStrategyDescriptor(
        id="private",
        label="Private",
        routing_mode="local_private",
        description="Restrict routing to local or private-network providers.",
        fallback_policy={"max_provider_attempts": 3, "order": "local_only"},
        score_weights={"privacy": 1.0, "locality": 1.0, "cost": 0.1},
    ),
    "cheapest": RoutingStrategyDescriptor(
        id="cheapest",
        label="Cheapest",
        routing_mode="cheapest",
        description="Prefer free or lowest-cost providers first.",
        fallback_policy={"max_provider_attempts": 5, "order": "cost_first"},
        score_weights={"cost": 1.0, "free": 0.7, "latency": 0.1},
    ),
    "fastest": RoutingStrategyDescriptor(
        id="fastest",
        label="Fastest",
        routing_mode="fastest",
        description="Prefer low-latency providers first.",
        fallback_policy={"max_provider_attempts": 4, "order": "latency_first"},
        score_weights={"latency": 1.0, "speed": 0.8, "cost": 0.05},
    ),
    "enterprise": RoutingStrategyDescriptor(
        id="enterprise",
        label="Enterprise",
        routing_mode="best_available",
        description="Prefer policy-aware routing with explicit audit metadata.",
        fallback_policy={"max_provider_attempts": 5, "order": "policy_first"},
        score_weights={"policy": 1.0, "quality": 0.8, "privacy": 0.5},
        metadata={"audit_required": True},
    ),
}


def builtin_routing_profiles() -> dict[str, dict[str, Any]]:
    return {key: descriptor.to_profile(source="builtin") for key, descriptor in BUILTIN_ROUTING_STRATEGIES.items()}


def routing_strategy_catalog() -> dict[str, Any]:
    strategies = [
        {**descriptor.to_profile(source="builtin"), "explanation": descriptor.explain()}
        for descriptor in BUILTIN_ROUTING_STRATEGIES.values()
    ]
    return {
        "object": "agent_hub.routing_strategies",
        "data": strategies,
        "count": len(strategies),
    }


__all__ = [
    "BUILTIN_ROUTING_STRATEGIES",
    "RoutingDecisionContext",
    "RoutingStrategy",
    "RoutingStrategyDescriptor",
    "StaticRoutingStrategy",
    "builtin_routing_profiles",
    "routing_strategy_catalog",
]
