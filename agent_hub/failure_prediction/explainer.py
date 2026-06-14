from __future__ import annotations


def explain_risk(flags: list[str]) -> str:
    if not flags:
        return "No major pre-routing failure risks detected."
    if "high_context_risk" in flags and "low_model_capability_risk" in flags:
        return "Large refactor across many files; cheap or weak model failed similar tasks before."
    if "missing_file_risk" in flags:
        return "Relevant files appear to be missing from context."
    if "test_failure_risk" in flags:
        return "Tests are unavailable or not detected, so regressions are harder to catch."
    if "cost_overrun_risk" in flags:
        return "Estimated cost is high for the selected route."
    return "; ".join(flag.replace("_", " ") for flag in flags[:3]) + "."
