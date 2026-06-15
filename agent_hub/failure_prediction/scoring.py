from __future__ import annotations

import math
from typing import Any

from .features import extract_risk_features


BUCKET_WEIGHTS = (
    ("provider_task", 1.00),
    ("provider_language", 0.65),
    ("provider", 0.15),
)


def score_success_probability(
    task: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    *,
    model: dict[str, Any] | None = None,
) -> dict[str, float]:
    trained = model or {}
    return {
        row["name"]: row["success_probability"]
        for row in (_score_candidate(task, candidate, model=trained) for candidate in candidates)
    }


def explain_success_probability(
    task: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    *,
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trained = model or {}
    rows = [_score_candidate(task, candidate, model=trained) for candidate in candidates]
    rows.sort(
        key=lambda row: (
            -float(row["success_probability"]),
            -float(row.get("trained_confidence", 0.0)),
            str(row["name"]),
        )
    )
    return {
        "object": "agent_hub.failure_prediction.success_probability_explanation",
        "selected": rows[0]["name"] if rows else "",
        "prior_success_rate": round(_prior_success_rate(trained), 4),
        "candidate_count": len(rows),
        "candidates": rows,
        "summary": _success_probability_summary(rows),
    }


def route_by_success_probability(
    task: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    *,
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    explanation = explain_success_probability(task, candidates, model=model)
    scores = {
        row["name"]: row["success_probability"]
        for row in explanation["candidates"]
    }
    return {
        "object": "agent_hub.failure_prediction.routing_scores",
        "success_probability": scores,
        "selected": explanation["selected"],
        "ranking": [
            {
                "name": row["name"],
                "success_probability": row["success_probability"],
                "trained_confidence": row["trained_confidence"],
                "top_reasons": row["top_reasons"],
            }
            for row in explanation["candidates"]
        ],
    }


def _base_probability(features: dict[str, Any], candidate: dict[str, Any]) -> float:
    return _base_probability_trace(features, candidate)["probability"]


def _score_candidate(
    task: dict[str, Any] | None,
    candidate: dict[str, Any],
    *,
    model: dict[str, Any],
) -> dict[str, Any]:
    buckets = model.get("buckets") if isinstance(model.get("buckets"), dict) else {}
    prior = _prior_success_rate(model)
    name = str(candidate.get("name") or candidate.get("agent") or candidate.get("provider") or candidate.get("model") or "unknown")
    features = extract_risk_features(task, candidate=candidate)
    base = _base_probability_trace(features, candidate)
    probability = float(base["probability"])
    adjustments: list[dict[str, Any]] = list(base["adjustments"])
    identities = _candidate_identities(candidate, primary=name)
    trained_strength = 0.0
    bucket_matches = []
    for kind, weight in BUCKET_WEIGHTS:
        keys = _bucket_keys(kind, identities, features["task_type"], features.get("language", "unknown"))
        match = _best_bucket_match(buckets, keys)
        if match is None:
            continue
        key, bucket = match
        success_rate = bucket.get("smoothed_success_rate", bucket.get("success_rate"))
        if success_rate is None:
            continue
        before = probability
        confidence = _bucket_confidence(bucket)
        trained_strength = max(trained_strength, confidence)
        effective_weight = weight * confidence
        probability = probability * (1 - effective_weight) + _safe_float(success_rate, prior) * effective_weight
        delta = probability - before
        bucket_matches.append(
            {
                "kind": kind,
                "key": key,
                "success_rate": round(float(success_rate), 4),
                "attempts": bucket.get("attempts", 0),
                "confidence": round(confidence, 4),
                "effective_weight": round(effective_weight, 4),
                "delta": round(delta, 4),
            }
        )
        adjustments.append(
            {
                "name": f"trained_{kind}",
                "delta": round(delta, 4),
                "summary": (
                    f"{kind.replace('_', ' ')} history moved probability "
                    f"{delta:+.1%} from {key}."
                ),
                "source": key,
            }
        )
    before_cloud = probability
    probability = _apply_trained_cloud_separation(
        probability,
        candidate,
        trained_strength=trained_strength,
        prior=prior,
    )
    cloud_delta = probability - before_cloud
    if abs(cloud_delta) >= 0.0001:
        adjustments.append(
            {
                "name": "trained_cloud_separation",
                "delta": round(cloud_delta, 4),
                "summary": f"Trained cloud separation moved probability {cloud_delta:+.1%}.",
                "source": "cloud_prior_gap",
            }
        )
    final_probability = round(max(0.01, min(0.99, probability)), 4)
    return {
        "name": name,
        "provider": candidate.get("provider"),
        "provider_type": candidate.get("provider_type"),
        "model": candidate.get("model"),
        "success_probability": final_probability,
        "success_probability_percent": round(final_probability * 100, 1),
        "base_probability": round(float(base["probability"]), 4),
        "trained_confidence": round(trained_strength, 4),
        "evidence_level": _evidence_level(trained_strength),
        "bucket_matches": bucket_matches,
        "adjustments": adjustments,
        "top_reasons": _top_reasons(adjustments),
        "features": _compact_features(features),
    }


def _base_probability_trace(features: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    score = 0.72
    adjustments = [{"name": "default_prior", "delta": 0.72, "summary": "Default task success prior."}]
    capability = candidate.get("coding_score", candidate.get("reasoning_score"))
    if capability is not None:
        previous = score
        score = 0.50 + min(1.0, max(0.0, _safe_float(capability, 0.0))) * 0.35
        adjustments.append(
            {
                "name": "capability_score",
                "delta": round(score - previous, 4),
                "summary": f"Candidate capability score set heuristic baseline to {score:.1%}.",
            }
        )
    if features.get("context_tokens", 0) > 60000:
        score -= 0.12
        adjustments.append({"name": "large_context", "delta": -0.12, "summary": "Large context raises miss risk."})
    if features.get("retry_count", 0):
        delta = -min(0.18, int(features["retry_count"]) * 0.04)
        score += delta
        adjustments.append({"name": "retry_history", "delta": round(delta, 4), "summary": "Prior retries lower confidence."})
    if features.get("cheap_or_small_model"):
        score -= 0.08
        adjustments.append({"name": "small_model", "delta": -0.08, "summary": "Small or cheap model has extra failure risk."})
    if features.get("tests_available"):
        score += 0.04
        adjustments.append({"name": "tests_available", "delta": 0.04, "summary": "Detected tests improve verification confidence."})
    if features.get("public_api_change"):
        score -= 0.06
        adjustments.append({"name": "public_api_change", "delta": -0.06, "summary": "Public API changes increase regression risk."})
    return {"probability": score, "adjustments": adjustments}


def _candidate_identities(candidate: dict[str, Any], *, primary: str) -> list[str]:
    identities = []
    for value in (
        primary,
        candidate.get("name"),
        candidate.get("agent"),
        candidate.get("model"),
        candidate.get("provider_type"),
        candidate.get("provider"),
    ):
        identity = _normalize_optional_key_part(value)
        if identity and identity not in identities:
            identities.append(identity)
    return identities or ["unknown"]


def _bucket_keys(kind: str, identities: list[str], task_type: str, language: str) -> list[str]:
    task_type = _normalize_key_part(task_type)
    language = _normalize_key_part(language)
    if kind == "provider_task":
        return [f"provider_task:{identity}:{task_type}" for identity in identities[:2]]
    if kind == "provider_language":
        return [f"provider_language:{identity}:{language}" for identity in identities[:2]]
    return [f"provider:{identity}" for identity in identities]


def _best_bucket(buckets: dict[str, Any], keys: list[str]) -> dict[str, Any] | None:
    match = _best_bucket_match(buckets, keys)
    return match[1] if match is not None else None


def _best_bucket_match(buckets: dict[str, Any], keys: list[str]) -> tuple[str, dict[str, Any]] | None:
    matches = []
    for index, key in enumerate(keys):
        bucket = buckets.get(key)
        if isinstance(bucket, dict) and _safe_float(bucket.get("attempts"), 0.0) > 0:
            matches.append((index, key, bucket))
    if not matches:
        return None
    matches.sort(
        key=lambda item: (
            -_bucket_confidence(item[2]),
            -_safe_float(item[2].get("attempts"), 0.0),
            item[0],
        )
    )
    _, key, bucket = matches[0]
    return key, bucket


def _bucket_confidence(bucket: dict[str, Any]) -> float:
    if bucket.get("confidence") is not None:
        return max(0.0, min(1.0, _safe_float(bucket.get("confidence"), 0.0)))
    attempts = _safe_float(bucket.get("attempts"), 0.0)
    return attempts / (attempts + 2.0) if attempts > 0 else 0.0


def _apply_trained_cloud_separation(
    probability: float,
    candidate: dict[str, Any],
    *,
    trained_strength: float,
    prior: float,
) -> float:
    if trained_strength <= 0:
        return probability
    if not _is_cloud_candidate(candidate):
        return probability
    gap = probability - prior
    lift = max(0.0, gap) * trained_strength * 0.35
    penalty = max(0.0, -gap) * trained_strength * 0.25
    return probability + lift - penalty


def _is_cloud_candidate(candidate: dict[str, Any]) -> bool:
    values = [
        _normalize_key_part(candidate.get("provider_type")),
        _normalize_key_part(candidate.get("provider")),
        _normalize_key_part(candidate.get("name") or candidate.get("agent")),
        _normalize_key_part(candidate.get("model")),
    ]
    local = {"ollama", "ollama-local", "lm-studio", "localai", "llama-cpp", "vllm", "local-research", "echo"}
    provider = values[0] or values[1]
    if provider in local:
        return False
    return any("cloud" in value for value in values) or provider not in {"", "unknown", "openai-compatible"}


def _normalize_key_part(value: Any) -> str:
    return str(value or "").strip().lower().replace("|", "/") or "unknown"


def _normalize_optional_key_part(value: Any) -> str:
    return str(value or "").strip().lower().replace("|", "/")


def _prior_success_rate(model: dict[str, Any]) -> float:
    return max(0.01, min(0.99, _safe_float(model.get("prior_success_rate"), 0.62)))


def _evidence_level(confidence: float) -> str:
    if confidence >= 0.80:
        return "strong"
    if confidence >= 0.45:
        return "moderate"
    if confidence > 0:
        return "weak"
    return "cold_start"


def _compact_features(features: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "task_type",
        "language",
        "context_tokens",
        "retry_count",
        "tests_available",
        "public_api_change",
        "cheap_or_small_model",
        "risk_level",
    )
    return {key: features.get(key) for key in keep if key in features}


def _top_reasons(adjustments: list[dict[str, Any]]) -> list[str]:
    ranked = [
        item
        for item in adjustments
        if item.get("name") != "default_prior" and abs(_safe_float(item.get("delta"), 0.0)) > 0.0001
    ]
    ranked.sort(key=lambda item: -abs(_safe_float(item.get("delta"), 0.0)))
    return [str(item.get("summary") or item.get("name")) for item in ranked[:4]]


def _success_probability_summary(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No candidates were scored."
    selected = rows[0]
    confidence = selected.get("evidence_level", "cold_start")
    return (
        f"{selected['name']} is predicted to have the highest success probability "
        f"({selected['success_probability_percent']}%) with {confidence} evidence."
    )


def _safe_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default
