from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class TokenBudget:
    context_budget: str = "medium"
    raw_context_tokens: int = 0
    optimized_context_tokens: int = 0
    max_context_tokens: int = 0
    target_context_tokens: int | None = None
    target_context_ratio: float = 0.62
    compression: str = "balanced"

    def with_context_usage(self, usage: dict[str, Any]) -> "TokenBudget":
        return replace(
            self,
            raw_context_tokens=_int(
                usage.get("original_input_tokens"),
                _int(usage.get("original_context_tokens"), self.raw_context_tokens),
            ),
            optimized_context_tokens=_int(
                usage.get("optimized_context_tokens"),
                _int(usage.get("estimated_input_tokens"), self.optimized_context_tokens),
            ),
            max_context_tokens=_int(usage.get("max_context_tokens"), self.max_context_tokens),
            target_context_tokens=(
                _int(usage.get("target_context_tokens"), 0)
                if usage.get("target_context_tokens") is not None
                else self.target_context_tokens
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_budget": self.context_budget,
            "raw_context_tokens": self.raw_context_tokens,
            "optimized_context_tokens": self.optimized_context_tokens,
            "max_context_tokens": self.max_context_tokens,
            "target_context_tokens": self.target_context_tokens,
            "target_context_ratio": self.target_context_ratio,
            "compression": self.compression,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TokenBudget":
        if not isinstance(data, dict):
            return cls()
        return cls(
            context_budget=str(data.get("context_budget") or "medium"),
            raw_context_tokens=_int(data.get("raw_context_tokens"), 0),
            optimized_context_tokens=_int(data.get("optimized_context_tokens"), 0),
            max_context_tokens=_int(data.get("max_context_tokens"), 0),
            target_context_tokens=(
                _int(data.get("target_context_tokens"), 0)
                if data.get("target_context_tokens") is not None
                else None
            ),
            target_context_ratio=_float(data.get("target_context_ratio"), 0.62),
            compression=str(data.get("compression") or "balanced"),
        )


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

