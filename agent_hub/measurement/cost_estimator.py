from __future__ import annotations

from typing import Any

from . import estimate_cost_for_agent


def estimate_request_cost(agent: Any, *, input_tokens: int, output_tokens: int) -> float | None:
    return estimate_cost_for_agent(agent, input_tokens=input_tokens, output_tokens=output_tokens)


def estimate_cost_from_prices(
    *,
    input_tokens: int,
    output_tokens: int,
    input_per_million: float | None,
    output_per_million: float | None,
) -> float | None:
    if input_per_million is None or output_per_million is None:
        return None
    total = max(0, int(input_tokens or 0)) * float(input_per_million)
    total += max(0, int(output_tokens or 0)) * float(output_per_million)
    return round(total / 1_000_000, 8)
