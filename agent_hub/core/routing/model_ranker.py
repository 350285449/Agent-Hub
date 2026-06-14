from __future__ import annotations

from typing import Any


def rank_candidate_scores(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        scores,
        key=lambda row: (
            -float(row.get("final_routing_score", row.get("routing_score", 0.0)) or 0.0),
            str(row.get("agent") or ""),
        ),
    )


def best_candidate(scores: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = rank_candidate_scores(scores)
    return ranked[0] if ranked else None
