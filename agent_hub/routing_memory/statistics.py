from __future__ import annotations

from collections import defaultdict
import math
import time
from typing import Any


def weighted_success_scores(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, float]] = defaultdict(lambda: {
        "attempts": 0.0,
        "success_weight": 0.0,
        "token_total": 0.0,
        "retry_total": 0.0,
        "score_total": 0.0,
        "latency_total": 0.0,
        "latency_count": 0.0,
        "bad_weight": 0.0,
        "feedback_weight": 0.0,
        "feedback_total": 0.0,
        "last_seen": 0.0,
    })
    for row in rows:
        key = profile_key(row)
        weight = similarity_weight(row)
        target = grouped[key]
        target["attempts"] += weight
        target["success_weight"] += weight if row.get("success") is True else 0.0
        target["token_total"] += (float(row.get("input_tokens") or 0) + float(row.get("output_tokens") or 0)) * weight
        target["retry_total"] += float(row.get("retry_count") or row.get("fallback_count") or 0) * weight
        target["score_total"] += _safe_float(row.get("outcome_score"), 0.0) * weight
        latency = _safe_float(row.get("latency_ms"), 0.0)
        if latency > 0:
            target["latency_total"] += latency * weight
            target["latency_count"] += weight
        if _bad_signal(row):
            target["bad_weight"] += weight
        feedback = str(row.get("feedback_rating") or "").strip().lower()
        if feedback in {"up", "down"}:
            target["feedback_weight"] += weight
            target["feedback_total"] += (1.0 if feedback == "up" else 0.0) * weight
        target["last_seen"] = max(target["last_seen"], _safe_float(row.get("time"), 0.0))
    return {
        key: {
            "success": round(value["success_weight"] / max(1.0, value["attempts"]), 4),
            "success_percent": round((value["success_weight"] / max(1.0, value["attempts"])) * 100, 2),
            "avg_tokens": round(value["token_total"] / max(1.0, value["attempts"]), 2),
            "avg_retries": round(value["retry_total"] / max(1.0, value["attempts"]), 2),
            "avg_outcome_score": round(value["score_total"] / max(1.0, value["attempts"]), 4),
            "avg_latency_ms": round(value["latency_total"] / max(1.0, value["latency_count"]), 2)
            if value["latency_count"] > 0
            else 0.0,
            "bad_rate": round(value["bad_weight"] / max(1.0, value["attempts"]), 4),
            "feedback_score": round(value["feedback_total"] / max(1.0, value["feedback_weight"]), 4)
            if value["feedback_weight"] > 0
            else 0.5,
            "freshness_score": round(freshness_score(value["last_seen"]), 4),
            "weighted_attempts": round(value["attempts"], 2),
        }
        for key, value in grouped.items()
    }


def profile_key(row: dict[str, Any]) -> str:
    return "/".join(
        _escape_key_part(row.get(key) or "unknown")
        for key in ("agent", "language", "framework")
    )


def similarity_weight(row: dict[str, Any]) -> float:
    return max(0.2, min(1.0, _safe_float(row.get("similarity"), 1.0)))


def freshness_score(last_seen: float) -> float:
    if last_seen <= 0:
        return 0.5
    age_days = max(0.0, (time.time() - last_seen) / 86400.0)
    return 1 / (1 + age_days / 45.0)


def _bad_signal(row: dict[str, Any]) -> bool:
    final = str(row.get("final_outcome") or "").strip().lower()
    feedback = str(row.get("feedback_rating") or "").strip().lower()
    return (
        row.get("success") is not True
        or row.get("timeout") is True
        or row.get("tool_failure") is True
        or row.get("reviewer_failure") is True
        or row.get("user_cancellation") is True
        or feedback == "down"
        or final in {"user_rejected", "failure", "failed_attempt", "timeout", "tool_failure", "reviewer_failure"}
        or _safe_float(row.get("outcome_score"), 1.0) <= 0.45
    )


def _safe_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _escape_key_part(value: Any) -> str:
    return str(value or "unknown").replace("\\", "\\\\").replace("/", "\\/")
