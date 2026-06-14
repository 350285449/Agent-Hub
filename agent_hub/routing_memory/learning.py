from __future__ import annotations

from typing import Any

from .model_profiles import build_model_profiles
from .statistics import profile_key


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


def self_adjusting_signal(store: Any, agent: Any, classification: Any) -> dict[str, Any]:
    data = classification.to_dict() if hasattr(classification, "to_dict") else dict(classification or {})
    pattern = {
        "agent": getattr(agent, "name", ""),
        "language": data.get("language") or "unknown",
        "framework": data.get("framework") or "unknown",
    }
    rows = []
    if hasattr(store, "similar_outcomes"):
        try:
            rows.extend(store.similar_outcomes(data, limit=250))
        except Exception:
            rows = []
    if not rows and hasattr(store, "recent"):
        try:
            rows.extend(store.recent(limit=500))
        except Exception:
            rows = []
    target_key = profile_key(pattern)
    learning = learn_from_outcomes(rows)
    stats = learning.get("model_profiles", {}).get(getattr(agent, "name", ""), {}).get(
        f"{pattern['language']}/{pattern['framework']}"
    )
    if not isinstance(stats, dict):
        return {
            "active": False,
            "adjustment": 0.0,
            "summary": "Self-adjusting memory has no segment profile yet.",
            "profile_key": target_key,
        }
    attempts = float(stats.get("weighted_attempts") or 0.0)
    success = float(stats.get("success") or 0.0) / 100.0
    avg_retries = float(stats.get("avg_retries") or 0.0)
    avg_tokens = float(stats.get("avg_tokens") or 0.0)
    confidence = min(1.0, attempts / 10.0)
    adjustment = ((success - 0.68) * 18.0 - min(5.0, avg_retries * 3.0) - min(3.0, avg_tokens / 40000.0)) * confidence
    adjustment = max(-10.0, min(10.0, adjustment))
    return {
        "active": attempts >= 2 and abs(adjustment) >= 0.2,
        "adjustment": round(adjustment, 4),
        "summary": (
            f"Self-adjusting memory profile {target_key}: {success * 100:.0f}% success, "
            f"{avg_retries:.1f} retries, {avg_tokens:.0f} avg tokens."
        ),
        "profile_key": target_key,
        "stats": stats,
    }
