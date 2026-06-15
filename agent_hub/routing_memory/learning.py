from __future__ import annotations

from typing import Any

from .model_profiles import build_model_profiles
from .statistics import profile_key


def learn_from_outcomes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    profiles = build_model_profiles(rows)
    recommendations = []
    for agent, segments in profiles["profiles"].items():
        for segment, stats in segments.items():
            confidence = _profile_confidence(stats)
            success_score = float(stats.get("success") or 0.0)
            outcome_score = float(stats.get("avg_outcome_score") or 0.0) * 100.0
            feedback_score = float(stats.get("feedback_score") or 0.5) * 100.0
            freshness_score = float(stats.get("freshness_score") or 0.5)
            retry_penalty = min(30.0, float(stats.get("avg_retries") or 0.0) * 8.0)
            token_penalty = min(20.0, float(stats.get("avg_tokens") or 0.0) / 5000.0)
            latency_penalty = min(8.0, float(stats.get("avg_latency_ms") or 0.0) / 2500.0)
            bad_penalty = min(35.0, float(stats.get("bad_rate") or 0.0) * 35.0)
            evidence_multiplier = confidence * (0.65 + 0.35 * freshness_score)
            rank_score = (
                (success_score * 0.50)
                + (outcome_score * 0.28)
                + (feedback_score * 0.12)
                + (freshness_score * 10.0)
                - retry_penalty
                - token_penalty
                - latency_penalty
                - bad_penalty
            ) * evidence_multiplier
            recommendations.append({
                "agent": agent,
                "segment": segment,
                "success": stats["success"],
                "avg_tokens": stats["avg_tokens"],
                "avg_retries": stats["avg_retries"],
                "avg_outcome_score": stats.get("avg_outcome_score", 0.0),
                "avg_latency_ms": stats.get("avg_latency_ms", 0.0),
                "bad_rate": stats.get("bad_rate", 0.0),
                "feedback_score": stats.get("feedback_score", 0.5),
                "freshness_score": stats.get("freshness_score", 0.5),
                "confidence": confidence,
                "rank_score": round(rank_score, 3),
                "score_breakdown": {
                    "success": round(success_score * 0.50, 3),
                    "outcome_quality": round(outcome_score * 0.28, 3),
                    "feedback": round(feedback_score * 0.12, 3),
                    "freshness": round(freshness_score * 10.0, 3),
                    "retry_penalty": round(-retry_penalty, 3),
                    "token_penalty": round(-token_penalty, 3),
                    "latency_penalty": round(-latency_penalty, 3),
                    "bad_data_penalty": round(-bad_penalty, 3),
                    "evidence_multiplier": round(evidence_multiplier, 4),
                },
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
    avg_outcome_score = float(stats.get("avg_outcome_score") or 0.0)
    bad_rate = float(stats.get("bad_rate") or 0.0)
    freshness = float(stats.get("freshness_score") or 0.5)
    confidence = _profile_confidence(stats)
    evidence = confidence * (0.65 + 0.35 * freshness)
    adjustment = (
        (success - 0.68) * 16.0
        + (avg_outcome_score - 0.65) * 8.0
        - min(5.0, avg_retries * 3.0)
        - min(3.0, avg_tokens / 40000.0)
        - min(4.0, bad_rate * 8.0)
    ) * evidence
    adjustment = max(-10.0, min(10.0, adjustment))
    return {
        "active": attempts >= 2 and abs(adjustment) >= 0.2,
        "adjustment": round(adjustment, 4),
        "confidence": confidence,
        "freshness_score": round(freshness, 4),
        "evidence": round(evidence, 4),
        "summary": (
            f"Self-adjusting memory profile {target_key}: {success * 100:.0f}% success, "
            f"{avg_retries:.1f} retries, {avg_tokens:.0f} avg tokens, {bad_rate * 100:.0f}% bad data, "
            f"{confidence * 100:.0f}% confidence."
        ),
        "profile_key": target_key,
        "stats": stats,
    }


def _profile_confidence(stats: dict[str, Any]) -> float:
    attempts = max(0.0, float(stats.get("weighted_attempts") or 0.0))
    return round(attempts / (attempts + 8.0), 4) if attempts else 0.0
