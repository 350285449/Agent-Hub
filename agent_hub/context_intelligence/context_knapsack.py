from __future__ import annotations

from typing import Any


def pack_context(items: list[dict[str, Any]], *, token_budget: int) -> list[dict[str, Any]]:
    budget = max(1, int(token_budget))
    ranked = sorted(items, key=lambda item: (-float(item.get("score") or 0), int(item.get("tokens") or 0)))
    selected = []
    used = 0
    for item in ranked:
        tokens = max(1, int(item.get("tokens") or _estimate_tokens(str(item.get("content") or ""))))
        if used + tokens > budget and selected:
            continue
        selected.append({**item, "tokens": tokens})
        used += tokens
        if used >= budget:
            break
    return selected


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
