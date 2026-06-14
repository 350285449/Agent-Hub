from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RoutingOutcomeEvent:
    task_type: str
    language: str
    framework: str
    repo_size: str
    model: str
    success: bool
    tokens: int
    cost: float | None
    retries: int = 0
    user_accepted: bool | None = None
    provider: str = ""
    agent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "language": self.language,
            "framework": self.framework,
            "repo_size": self.repo_size,
            "model": self.model,
            "provider": self.provider,
            "agent": self.agent,
            "success": self.success,
            "tokens": self.tokens,
            "cost": self.cost,
            "retries": self.retries,
            "user_accepted": self.user_accepted,
        }

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "RoutingOutcomeEvent":
        return cls(
            task_type=str(value.get("task_type") or "general"),
            language=str(value.get("language") or "unknown"),
            framework=str(value.get("framework") or "unknown"),
            repo_size=str(value.get("repo_size") or value.get("repo_size_bucket") or "unknown"),
            model=str(value.get("model") or ""),
            provider=str(value.get("provider") or ""),
            agent=str(value.get("agent") or ""),
            success=bool(value.get("success")),
            tokens=max(0, int(value.get("tokens") or value.get("total_tokens") or 0)),
            cost=_optional_float(value.get("cost", value.get("estimated_cost_usd"))),
            retries=max(0, int(value.get("retries") or value.get("retry_count") or value.get("fallback_count") or 0)),
            user_accepted=value.get("user_accepted") if isinstance(value.get("user_accepted"), bool) else None,
        )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
