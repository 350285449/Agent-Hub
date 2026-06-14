from __future__ import annotations

from typing import Any


def evaluate_risk_rules(features: dict[str, Any]) -> dict[str, Any]:
    flags: list[str] = []
    avoid_models: list[str] = []
    file_count = int(features.get("file_count") or 0)
    if int(features.get("context_tokens") or 0) > 24_000 or file_count >= 12:
        flags.append("high_context_risk")
    success_rate = features.get("model_success_rate")
    failure_rate = features.get("model_failure_rate")
    weak_history = False
    if success_rate is not None:
        weak_history = float(success_rate or 0.0) < 0.45
    if failure_rate is not None:
        weak_history = weak_history or float(failure_rate or 0.0) > 0.55
    similar_failures = int(features.get("similar_failures") or 0)
    if weak_history or similar_failures >= 2 or (features.get("cheap_or_small_model") and (file_count >= 6 or features.get("is_refactor"))):
        flags.append("low_model_capability_risk")
    if features.get("missing_files"):
        flags.append("missing_file_risk")
    if not features.get("tests_available", True):
        flags.append("test_failure_risk")
    if (
        str(features.get("risk_level") or "").lower() in {"high", "critical"}
        or (features.get("is_refactor") and file_count >= 6)
        or features.get("public_api_change")
    ):
        flags.append("hallucination_risk")
    if float(features.get("estimated_cost_usd") or 0.0) > 1.0 or int(features.get("context_tokens") or 0) > 80_000:
        flags.append("cost_overrun_risk")
    model = str(features.get("model") or "")
    if flags and any(term in model.lower() for term in ("flash", "small", "mini", "local")):
        avoid_models.append(model)
    return {"flags": flags, "avoid_models": avoid_models}
