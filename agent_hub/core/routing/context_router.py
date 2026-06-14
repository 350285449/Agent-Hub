from __future__ import annotations


def context_bucket(tokens: int) -> str:
    if tokens >= 64_000:
        return "xlarge"
    if tokens >= 24_000:
        return "large"
    if tokens >= 8_000:
        return "medium"
    return "small"


def required_context_window(tokens: int, *, output_tokens: int = 0, safety_margin: float = 1.2) -> int:
    total = max(0, int(tokens or 0)) + max(0, int(output_tokens or 0))
    return int(total * max(1.0, float(safety_margin or 1.0)))


def context_fits_model(tokens: int, context_window: int | None, *, output_tokens: int = 0) -> bool:
    if not context_window:
        return True
    return int(context_window) >= required_context_window(tokens, output_tokens=output_tokens)
