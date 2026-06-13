from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CoderAgentRole:
    name: str = "coder"
    route: str = "coding"
    instruction: str = "Implement the requested change and keep edits scoped."
