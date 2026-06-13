from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReviewerAgentRole:
    name: str = "reviewer"
    route: str = "cloud-agent"
    instruction: str = "Review for bugs, regressions, missing tests, and risky assumptions."
