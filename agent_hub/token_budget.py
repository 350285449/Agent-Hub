from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .context import estimate_message_tokens

CONTEXT_MODES = {"minimal", "balanced", "deep"}
MODE_BUDGET_FRACTION = {
    "minimal": 0.45,
    "balanced": 0.72,
    "deep": 0.92,
}
MODE_FULL_TOOL_HISTORY = {
    "minimal": 1,
    "balanced": 2,
    "deep": 4,
}


@dataclass(slots=True)
class TokenBudget:
    mode: str
    configured_budget: int | None
    provider_budget: int | None
    effective_budget: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "configured_budget": self.configured_budget,
            "provider_budget": self.provider_budget,
            "effective_budget": self.effective_budget,
        }


class TokenBudgetManager:
    """Central token estimation and adaptive context-budget policy."""

    def __init__(self, mode: str = "balanced") -> None:
        self.mode = normalize_context_mode(mode)

    @classmethod
    def from_request(cls, request: Any, default: str = "balanced") -> "TokenBudgetManager":
        raw = getattr(request, "raw", {}) or {}
        hub_options = raw.get("agent_hub") if isinstance(raw, dict) else None
        value = None
        if isinstance(hub_options, dict):
            value = hub_options.get("context_mode") or hub_options.get("agent_context_mode")
        if value is None and isinstance(raw, dict):
            value = raw.get("context_mode") or raw.get("agent_context_mode")
        return cls(normalize_context_mode(value or default))

    def effective_input_budget(
        self,
        *,
        configured_budget: int | None,
        provider_budget: int | None,
    ) -> TokenBudget:
        base = _min_positive(configured_budget, provider_budget)
        if base is None:
            return TokenBudget(
                mode=self.mode,
                configured_budget=configured_budget,
                provider_budget=provider_budget,
                effective_budget=None,
            )
        effective = max(1, int(base * MODE_BUDGET_FRACTION[self.mode]))
        return TokenBudget(
            mode=self.mode,
            configured_budget=configured_budget,
            provider_budget=provider_budget,
            effective_budget=effective,
        )

    def full_tool_history(self, *, repair_active: bool = False) -> int:
        if repair_active:
            return max(2, MODE_FULL_TOOL_HISTORY[self.mode])
        return MODE_FULL_TOOL_HISTORY[self.mode]

    def usage(
        self,
        messages: list[dict[str, Any]],
        *,
        budget_tokens: int | None,
        previous_input_tokens: int | None = None,
        tokens_saved: int = 0,
    ) -> dict[str, Any]:
        input_tokens = estimate_messages_tokens(messages)
        percent_used = (
            round((input_tokens / budget_tokens) * 100, 1)
            if budget_tokens is not None and budget_tokens > 0
            else None
        )
        return {
            "input_tokens": input_tokens,
            "budget_tokens": budget_tokens,
            "context_mode": self.mode,
            "percent_used": percent_used,
            "tokens_added_since_last_step": 0
            if previous_input_tokens is None
            else input_tokens - previous_input_tokens,
            "estimated_tokens_saved": max(0, tokens_saved),
        }


def normalize_context_mode(value: Any) -> str:
    text = str(value or "balanced").strip().lower()
    return text if text in CONTEXT_MODES else "balanced"


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    return estimate_message_tokens(messages)


def content_to_text(content: Any) -> str:
    from .context import content_to_text as _content_to_text

    return _content_to_text(content)


def _min_positive(*values: int | None) -> int | None:
    positives = [int(value) for value in values if value is not None and int(value) > 0]
    return min(positives) if positives else None
