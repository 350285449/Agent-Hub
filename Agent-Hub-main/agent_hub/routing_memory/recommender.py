from __future__ import annotations

from typing import Any

from .scorer import model_memory_score


def recommend_models(pattern: dict[str, Any], rows: list[dict[str, Any]], models: list[str]) -> list[dict[str, Any]]:
    scored = [_with_policy_adjustment(pattern, model_memory_score(pattern, rows, model)) for model in models]
    return sorted(scored, key=lambda row: (-float(row.get("adjustment") or 0.0), str(row.get("model") or "")))


def _with_policy_adjustment(pattern: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    model = str(row.get("model") or "")
    lowered = model.lower()
    task_type = str(pattern.get("task_type") or "").lower()
    framework = str(pattern.get("framework") or "").lower()
    language = str(pattern.get("language") or "").lower()
    adjustment = float(row.get("adjustment") or 0.0)
    reasons: list[str] = []
    if "claude" in lowered and "bug" in task_type and "fastapi" in framework and row.get("success_rate", 0) >= 0.65:
        adjustment += 2.0
        reasons.append("Claude succeeded often on similar FastAPI bug fixes.")
    if "gemini" in lowered and "refactor" in task_type and row.get("failure_rate", 0) >= 0.4:
        adjustment -= 3.0
        reasons.append("Gemini failed often on similar refactors.")
    if any(term in lowered for term in ("local", "ollama", "lm-studio")) and task_type in {"docs", "documentation", "doc_task"}:
        if str(pattern.get("repo_size") or pattern.get("repo_size_bucket") or "").lower() in {"small", "tiny", ""}:
            adjustment += 2.5
            reasons.append("Local model succeeded or is preferred for small documentation tasks.")
    if language == "python" and "fastapi" in framework and row.get("attempts", 0):
        reasons.append("Matched Python/FastAPI routing memory samples.")
    result = dict(row)
    result["adjustment"] = round(adjustment, 4)
    result["reasons"] = reasons
    return result
