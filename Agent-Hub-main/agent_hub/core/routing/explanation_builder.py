from __future__ import annotations

from typing import Any


def selected_explanation(selected: dict[str, Any] | None) -> str:
    if not selected:
        return "No candidate was selected."
    return (
        f"{selected.get('agent') or selected.get('model') or 'candidate'} ranked highest "
        f"with score {selected.get('final_routing_score', selected.get('routing_score', '--'))}."
    )


def build_route_explanation(
    *,
    selected: dict[str, Any] | None,
    rejected: list[dict[str, Any]] | None = None,
    memory: list[dict[str, Any]] | None = None,
    risks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "object": "agent_hub.routing.explanation",
        "summary": selected_explanation(selected),
        "selected": selected or {},
        "rejected_models": [
            {
                "agent": row.get("agent"),
                "model": row.get("model"),
                "reason": row.get("why") or row.get("skip_reason") or row.get("reason") or "",
            }
            for row in rejected or []
            if isinstance(row, dict)
        ],
        "memory_adjustments": list(memory or []),
        "failure_prediction": dict(risks or {}),
    }
