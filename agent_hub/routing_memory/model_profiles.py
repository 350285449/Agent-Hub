from __future__ import annotations

from typing import Any

from .statistics import weighted_success_scores


def build_model_profiles(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = weighted_success_scores(rows)
    profiles: dict[str, Any] = {}
    for key, value in scores.items():
        agent, language, framework = (key.split("/") + ["unknown", "unknown"])[:3]
        profiles.setdefault(agent, {})[f"{language}/{framework}"] = {
            "success": value["success_percent"],
            "avg_tokens": value["avg_tokens"],
            "avg_retries": value["avg_retries"],
            "weighted_attempts": value["weighted_attempts"],
        }
    return {
        "object": "agent_hub.routing_memory.model_profiles",
        "profiles": profiles,
    }
