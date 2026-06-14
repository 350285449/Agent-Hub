from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RouteTrace:
    request_id: str
    selected_model: str = ""
    rejected_models: list[str] = field(default_factory=list)
    retries: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    tokens: dict[str, int] = field(default_factory=dict)
    cost_usd: float | None = None
    tests: dict[str, int] = field(default_factory=dict)
    user_accepted: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.routing.route_trace",
            "request_id": self.request_id,
            "selected_model": self.selected_model,
            "rejected_models": list(self.rejected_models),
            "retries": self.retries,
            "tokens": dict(self.tokens),
            "cost_usd": self.cost_usd,
            "tests": dict(self.tests),
            "user_accepted": self.user_accepted,
            "metadata": dict(self.metadata),
        }


def trace_from_decision(request_id: str, decision: dict[str, Any], *, retries: int = 0) -> RouteTrace:
    rejected = []
    for row in decision.get("candidate_scores", []) if isinstance(decision, dict) else []:
        if isinstance(row, dict) and row.get("agent") != decision.get("selected_agent"):
            rejected.append(str(row.get("model") or row.get("agent") or ""))
    return RouteTrace(
        request_id=request_id,
        selected_model=str(decision.get("selected_model") or ""),
        rejected_models=[item for item in rejected if item],
        retries=max(0, int(retries or 0)),
        metadata={"routing_mode": decision.get("routing_mode"), "selected_agent": decision.get("selected_agent")},
    )
