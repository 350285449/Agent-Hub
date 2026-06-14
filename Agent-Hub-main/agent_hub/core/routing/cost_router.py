from __future__ import annotations

from typing import Any


def cheapest_priced(scores: list[dict[str, Any]]) -> dict[str, Any] | None:
    priced = [(row, row.get("estimated_cost_usd")) for row in scores if row.get("estimated_cost_usd") is not None]
    if not priced:
        return None
    return min(priced, key=lambda item: (float(item[1] or 0.0), str(item[0].get("agent") or "")))[0]


def cost_aware_rank(scores: list[dict[str, Any]], *, max_cost_usd: float | None = None) -> list[dict[str, Any]]:
    rows = []
    for row in scores:
        cost = row.get("estimated_cost_usd")
        if max_cost_usd is not None and cost is not None and float(cost or 0.0) > max_cost_usd:
            continue
        quality = float(row.get("final_routing_score", row.get("routing_score", 0.0)) or 0.0)
        cost_value = float(cost or 0.0)
        efficiency = quality / max(0.000001, cost_value + 0.000001)
        enriched = dict(row)
        enriched["cost_efficiency"] = round(efficiency, 4)
        rows.append(enriched)
    return sorted(rows, key=lambda item: (-float(item.get("cost_efficiency") or 0.0), str(item.get("agent") or "")))
