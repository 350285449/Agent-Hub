from __future__ import annotations

from collections import defaultdict
from typing import Any


def weighted_success_scores(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, float]] = defaultdict(lambda: {
        "attempts": 0.0,
        "success_weight": 0.0,
        "token_total": 0.0,
        "retry_total": 0.0,
    })
    for row in rows:
        key = profile_key(row)
        weight = similarity_weight(row)
        target = grouped[key]
        target["attempts"] += weight
        target["success_weight"] += weight if row.get("success") is True else 0.0
        target["token_total"] += float(row.get("input_tokens") or 0) + float(row.get("output_tokens") or 0)
        target["retry_total"] += float(row.get("retry_count") or row.get("fallback_count") or 0)
    return {
        key: {
            "success": round(value["success_weight"] / max(1.0, value["attempts"]), 4),
            "success_percent": round((value["success_weight"] / max(1.0, value["attempts"])) * 100, 2),
            "avg_tokens": round(value["token_total"] / max(1.0, value["attempts"]), 2),
            "avg_retries": round(value["retry_total"] / max(1.0, value["attempts"]), 2),
            "weighted_attempts": round(value["attempts"], 2),
        }
        for key, value in grouped.items()
    }


def profile_key(row: dict[str, Any]) -> str:
    return "/".join(
        str(row.get(key) or "unknown")
        for key in ("agent", "language", "framework")
    )


def similarity_weight(row: dict[str, Any]) -> float:
    return max(0.2, min(1.0, float(row.get("similarity") or 1.0)))
