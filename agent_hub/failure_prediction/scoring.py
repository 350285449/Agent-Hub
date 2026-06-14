from __future__ import annotations

from typing import Any

from .features import extract_risk_features


def score_success_probability(
    task: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    *,
    model: dict[str, Any] | None = None,
) -> dict[str, float]:
    trained = model or {}
    buckets = trained.get("buckets") if isinstance(trained.get("buckets"), dict) else {}
    scores: dict[str, float] = {}
    for candidate in candidates:
        name = str(candidate.get("name") or candidate.get("agent") or candidate.get("provider") or candidate.get("model") or "unknown")
        features = extract_risk_features(task, candidate=candidate)
        probability = _base_probability(features, candidate)
        task_key = f"provider_task:{name}:{features['task_type']}"
        provider_key = f"provider:{name}"
        language_key = f"provider_language:{name}:{features.get('language', 'unknown')}"
        for key, weight in ((task_key, 0.45), (language_key, 0.25), (provider_key, 0.20)):
            bucket = buckets.get(key)
            if isinstance(bucket, dict) and int(bucket.get("attempts") or 0) > 0:
                probability = probability * (1 - weight) + float(bucket.get("success_rate") or probability) * weight
        scores[name] = round(max(0.01, min(0.99, probability)), 4)
    return scores


def route_by_success_probability(
    task: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    *,
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scores = score_success_probability(task, candidates, model=model)
    selected = max(scores, key=scores.get) if scores else ""
    return {
        "object": "agent_hub.failure_prediction.routing_scores",
        "success_probability": scores,
        "selected": selected,
    }


def _base_probability(features: dict[str, Any], candidate: dict[str, Any]) -> float:
    score = 0.72
    capability = candidate.get("coding_score", candidate.get("reasoning_score"))
    if capability is not None:
        score = 0.50 + min(1.0, max(0.0, float(capability))) * 0.35
    if features.get("context_tokens", 0) > 60000:
        score -= 0.12
    if features.get("retry_count", 0):
        score -= min(0.18, int(features["retry_count"]) * 0.04)
    if features.get("cheap_or_small_model"):
        score -= 0.08
    if features.get("tests_available"):
        score += 0.04
    if features.get("public_api_change"):
        score -= 0.06
    return score
