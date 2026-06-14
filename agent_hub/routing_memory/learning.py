from __future__ import annotations

from typing import Any

from .model_profiles import build_model_profiles


def learn_from_outcomes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    profiles = build_model_profiles(rows)
    recommendations = []
    for agent, segments in profiles["profiles"].items():
        for segment, stats in segments.items():
            recommendations.append({
                "agent": agent,
                "segment": segment,
                "success": stats["success"],
                "avg_tokens": stats["avg_tokens"],
                "avg_retries": stats["avg_retries"],
                "rank_score": round(stats["success"] - min(30.0, stats["avg_retries"] * 8.0) - min(20.0, stats["avg_tokens"] / 5000.0), 3),
            })
    recommendations.sort(key=lambda row: -float(row["rank_score"]))
    return {
        "object": "agent_hub.routing_memory.learning",
        "model_profiles": profiles["profiles"],
        "ranking": recommendations,
    }
