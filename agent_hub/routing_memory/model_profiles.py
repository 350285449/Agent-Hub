from __future__ import annotations

from typing import Any

from .statistics import weighted_success_scores


def build_model_profiles(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = weighted_success_scores(rows)
    profiles: dict[str, Any] = {}
    for key, value in scores.items():
        agent, language, framework = (_split_profile_key(key) + ["unknown", "unknown"])[:3]
        profiles.setdefault(agent, {})[f"{language}/{framework}"] = {
            "success": value["success_percent"],
            "avg_tokens": value["avg_tokens"],
            "avg_retries": value["avg_retries"],
            "avg_outcome_score": value["avg_outcome_score"],
            "avg_latency_ms": value["avg_latency_ms"],
            "bad_rate": value["bad_rate"],
            "feedback_score": value["feedback_score"],
            "freshness_score": value["freshness_score"],
            "weighted_attempts": value["weighted_attempts"],
        }
    return {
        "object": "agent_hub.routing_memory.model_profiles",
        "profiles": profiles,
    }


def _split_profile_key(key: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in key:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "/":
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    if escaped:
        current.append("\\")
    parts.append("".join(current))
    return parts
