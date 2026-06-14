from __future__ import annotations


def estimate_savings(*, original_tokens: int, optimized_tokens: int, input_price_per_million: float | None = None) -> dict[str, object]:
    saved = max(0, int(original_tokens or 0) - int(optimized_tokens or 0))
    cost = None
    if input_price_per_million is not None:
        cost = round(saved * float(input_price_per_million) / 1_000_000, 8)
    return {
        "tokens_saved": saved,
        "savings_percent": round(saved / max(1, int(original_tokens or 0)), 4),
        "cost_avoided_usd": cost,
    }
