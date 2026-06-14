from __future__ import annotations

from typing import Any

from .explainer import explain_risk
from .features import extract_risk_features
from .rules import evaluate_risk_rules


def predict_failure_risk(task: dict[str, Any] | None = None, *, candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    features = extract_risk_features(task, candidate=candidate)
    rules = evaluate_risk_rules(features)
    flags = list(rules["flags"])
    if len(flags) >= 3 or ("high_context_risk" in flags and "low_model_capability_risk" in flags):
        risk = "high"
        mode = "big_refactor"
    elif flags:
        risk = "medium"
        mode = "quality_first"
    else:
        risk = "low"
        mode = "balanced"
    return {
        "object": "agent_hub.failure_prediction",
        "risk": risk,
        "reason": explain_risk(flags),
        "recommended_mode": mode,
        "avoid_models": rules["avoid_models"],
        "features": features,
        "risk_flags": flags,
    }
