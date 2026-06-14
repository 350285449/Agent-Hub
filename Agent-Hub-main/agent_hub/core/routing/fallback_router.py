from __future__ import annotations

from typing import Any


def fallback_chain(scores: list[dict[str, Any]]) -> list[str]:
    return [str(row.get("agent") or "") for row in scores if row.get("agent")]


def fallback_candidates(scores: list[dict[str, Any]], *, selected_agent: str | None = None, limit: int = 5) -> list[str]:
    names = []
    for row in scores:
        name = str(row.get("agent") or "")
        if not name or name == selected_agent or name in names:
            continue
        names.append(name)
        if len(names) >= limit:
            break
    return names
