from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlannerAgentRole:
    name: str = "planner"
    route: str = "cloud-agent"
    instruction: str = "Break the task into a short, executable plan."
