from __future__ import annotations

from collections import defaultdict
from typing import Any


def train_success_model(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, float]] = defaultdict(lambda: {"attempts": 0.0, "successes": 0.0})
    for row in rows:
        provider = str(row.get("provider") or row.get("agent") or row.get("model") or "unknown")
        keys = {
            f"provider:{provider}",
            f"task:{row.get('task_type') or row.get('task') or 'general'}",
            f"language:{row.get('language') or 'unknown'}",
            f"provider_task:{provider}:{row.get('task_type') or row.get('task') or 'general'}",
            f"provider_language:{provider}:{row.get('language') or 'unknown'}",
        }
        for key in keys:
            buckets[key]["attempts"] += 1
            buckets[key]["successes"] += 1 if row.get("success") is True else 0
    return {
        "object": "agent_hub.failure_prediction.model",
        "sample_count": len(rows),
        "buckets": {
            key: {
                "attempts": int(value["attempts"]),
                "success_rate": round(value["successes"] / max(1.0, value["attempts"]), 4),
            }
            for key, value in buckets.items()
        },
    }
