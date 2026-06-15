from __future__ import annotations

from collections import defaultdict
import math
from typing import Any


PRIOR_SUCCESS_RATE = 0.62
PRIOR_WEIGHT = 1.0
CONFIDENCE_HALF_LIFE = 2.0


def train_success_model(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, float]] = defaultdict(
        lambda: {"attempts": 0.0, "successes": 0.0, "failures": 0.0, "weight": 0.0}
    )
    total_weight = 0.0
    total_success_weight = 0.0
    for row in rows:
        row_weight = _row_weight(row)
        provider = _normalize_key_part(row.get("provider") or row.get("agent") or row.get("model") or "unknown")
        agent = _normalize_optional_key_part(row.get("name") or row.get("agent") or "")
        model = _normalize_optional_key_part(row.get("model") or "")
        provider_type = _normalize_optional_key_part(row.get("provider_type") or "")
        identities = {provider}
        if agent:
            identities.add(agent)
        if model:
            identities.add(model)
        if provider_type:
            identities.add(provider_type)
        task = _normalize_key_part(row.get("task_type") or row.get("task") or "general")
        language = _normalize_key_part(row.get("language") or "unknown")
        keys = {
            f"provider:{provider}",
            f"task:{task}",
            f"language:{language}",
        }
        for identity in identities:
            keys.add(f"provider:{identity}")
            keys.add(f"provider_task:{identity}:{task}")
            keys.add(f"provider_language:{identity}:{language}")
        for key in keys:
            buckets[key]["attempts"] += row_weight
            buckets[key]["weight"] += row_weight
            if row.get("success") is True:
                buckets[key]["successes"] += row_weight
            else:
                buckets[key]["failures"] += row_weight
        total_weight += row_weight
        if row.get("success") is True:
            total_success_weight += row_weight
    prior = total_success_weight / total_weight if total_weight > 0 else PRIOR_SUCCESS_RATE
    return {
        "object": "agent_hub.failure_prediction.model",
        "version": 2,
        "sample_count": len(rows),
        "prior_success_rate": round(prior, 4),
        "prior_weight": PRIOR_WEIGHT,
        "buckets": {
            key: _bucket_payload(value, prior)
            for key, value in buckets.items()
        },
    }


def _bucket_payload(value: dict[str, float], prior: float) -> dict[str, Any]:
    attempts = float(value["attempts"])
    successes = float(value["successes"])
    failures = float(value["failures"])
    raw_rate = successes / max(1.0, attempts)
    smoothed = (successes + prior * PRIOR_WEIGHT) / max(1.0, attempts + PRIOR_WEIGHT)
    confidence = attempts / (attempts + CONFIDENCE_HALF_LIFE) if attempts > 0 else 0.0
    return {
        "attempts": round(attempts, 4),
        "successes": round(successes, 4),
        "failures": round(failures, 4),
        "success_rate": round(raw_rate, 4),
        "smoothed_success_rate": round(smoothed, 4),
        "confidence": round(confidence, 4),
        "evidence_strength": round(attempts * confidence, 4),
    }


def _row_weight(row: dict[str, Any]) -> float:
    weight = _safe_float(row.get("weight") or row.get("similarity"), 1.0)
    if row.get("final") is False:
        weight *= 0.5
    feedback = str(row.get("feedback_rating") or "").strip().lower()
    if feedback == "down":
        weight *= 1.25
    if feedback == "up":
        weight *= 1.1
    return max(0.1, min(3.0, weight))


def _normalize_key_part(value: Any) -> str:
    return str(value or "").strip().lower().replace("|", "/") or "unknown"


def _normalize_optional_key_part(value: Any) -> str:
    return str(value or "").strip().lower().replace("|", "/")


def _safe_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default
