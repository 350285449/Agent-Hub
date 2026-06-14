from __future__ import annotations

from typing import Any


def enabled_candidates(agents: list[Any]) -> list[Any]:
    return [agent for agent in agents if getattr(agent, "enabled", True)]


def filter_candidates(
    agents: list[Any],
    *,
    free_only: bool = False,
    requires_tools: bool = False,
    min_context_window: int = 0,
) -> list[Any]:
    rows = enabled_candidates(agents)
    if free_only:
        rows = [agent for agent in rows if bool(getattr(agent, "free", False))]
    if requires_tools:
        rows = [agent for agent in rows if bool(getattr(agent, "supports_function_calling", False))]
    if min_context_window:
        rows = [agent for agent in rows if int(getattr(agent, "context_window", 0) or 0) >= min_context_window]
    return rows
