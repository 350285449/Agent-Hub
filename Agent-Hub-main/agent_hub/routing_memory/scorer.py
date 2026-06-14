from __future__ import annotations

from typing import Any

from . import similarity_score


def model_memory_score(pattern: dict[str, Any], rows: list[dict[str, Any]], model: str) -> dict[str, Any]:
    similar = [row for row in rows if similarity_score(pattern, row) > 0 and str(row.get("model") or "") == model]
    attempts = len(similar)
    if not attempts:
        return {"model": model, "attempts": 0, "adjustment": 0.0}
    successes = sum(1 for row in similar if row.get("success") is True)
    accepted = sum(1 for row in similar if row.get("user_accepted") is True or row.get("final_outcome") == "user_confirmed")
    total_tokens = sum(int(row.get("tokens") or row.get("input_tokens") or 0) + int(row.get("output_tokens") or 0) for row in similar)
    total_retries = sum(int(row.get("retries") or row.get("retry_count") or row.get("fallback_count") or 0) for row in similar)
    failure_rate = (attempts - successes) / attempts
    success_rate = successes / attempts
    adjustment = (success_rate - 0.55) * 12.0 + min(2.0, accepted * 0.4) - failure_rate * 3.0
    adjustment -= min(2.0, total_retries * 0.25)
    average_tokens = round(total_tokens / attempts, 2) if attempts else 0.0
    return {
        "model": model,
        "attempts": attempts,
        "success_rate": round(success_rate, 4),
        "failure_rate": round(failure_rate, 4),
        "average_tokens": average_tokens,
        "average_retries": round(total_retries / attempts, 4),
        "adjustment": round(adjustment, 4),
    }
