from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CompressionPolicy:
    name: str
    aggression: float
    preserve_full_files: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "aggression": self.aggression,
            "preserve_full_files": self.preserve_full_files,
        }


def compression_policy_for_plan(plan: Any) -> CompressionPolicy:
    aggression = float(getattr(plan, "compression_aggression", 0.55) or 0.55)
    if aggression >= 0.7:
        name = "aggressive"
    elif aggression <= 0.4:
        name = "light"
    else:
        name = "balanced"
    return CompressionPolicy(
        name=name,
        aggression=round(aggression, 3),
        preserve_full_files=int(getattr(plan, "full_files", 0) or 0),
    )

