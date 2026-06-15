from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .boost import boost_mode_from_request, boost_policy
from .context import estimate_message_tokens
from .observability import recent_events, record_event

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
        if value is None and _has_explicit_boost_mode(raw, hub_options):
            value = boost_policy(boost_mode_from_request(request, default=default)).context_mode
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
            "estimated_tokens_saved_percent": (
                round((max(0, tokens_saved) / max(1, input_tokens + max(0, tokens_saved))) * 100, 1)
                if tokens_saved
                else 0.0
            ),
        }


class TokenBudgetLedger:
    """Durable per-request and per-workflow token budget stage ledger."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)

    def record_stage(
        self,
        *,
        request_id: str,
        stage: str,
        budget: TokenBudget | dict[str, Any],
        usage: dict[str, Any] | None = None,
        workflow: str = "",
        role: str = "",
        status: str = "planned",
    ) -> dict[str, Any]:
        budget_payload = budget.to_dict() if isinstance(budget, TokenBudget) else dict(budget or {})
        usage_payload = dict(usage or {})
        row = {
            "type": "token_budget_stage",
            "request_id": str(request_id or ""),
            "workflow": str(workflow or ""),
            "role": str(role or ""),
            "stage": str(stage or "request"),
            "status": str(status or "planned"),
            "budget": budget_payload,
            "usage": usage_payload,
            "effective_budget": _optional_int(budget_payload.get("effective_budget")),
            "input_tokens": _optional_int(
                usage_payload.get("input_tokens")
                or usage_payload.get("estimated_input_tokens")
                or usage_payload.get("prompt_tokens")
            ),
            "output_tokens": _optional_int(
                usage_payload.get("output_tokens")
                or usage_payload.get("completion_tokens")
            ),
            "tokens_saved": _optional_int(
                usage_payload.get("estimated_tokens_saved")
                or usage_payload.get("tokens_saved")
            ),
        }
        record_event(self.state_dir, "token_budget", row)
        return row

    def summary(self, *, limit: int = 100) -> dict[str, Any]:
        rows = recent_events(self.state_dir, "token_budget", limit=limit)
        stages = [row for row in rows if row.get("type") == "token_budget_stage"]
        return {
            "object": "agent_hub.token_budget_ledger",
            "count": len(stages),
            "recent": stages[-25:],
            "totals": {
                "input_tokens": sum(_positive_int(row.get("input_tokens")) for row in stages),
                "output_tokens": sum(_positive_int(row.get("output_tokens")) for row in stages),
                "tokens_saved": sum(_positive_int(row.get("tokens_saved")) for row in stages),
            },
            "by_stage": _group_counts(stages, "stage"),
            "by_workflow": _group_counts(stages, "workflow"),
        }


def record_token_budget_stage(
    state_dir: str | Path,
    *,
    request_id: str,
    stage: str,
    budget: TokenBudget | dict[str, Any],
    usage: dict[str, Any] | None = None,
    workflow: str = "",
    role: str = "",
    status: str = "planned",
) -> dict[str, Any]:
    return TokenBudgetLedger(state_dir).record_stage(
        request_id=request_id,
        stage=stage,
        budget=budget,
        usage=usage,
        workflow=workflow,
        role=role,
        status=status,
    )


def token_budget_ledger_summary(state_dir: str | Path, *, limit: int = 100) -> dict[str, Any]:
    return TokenBudgetLedger(state_dir).summary(limit=limit)


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


def _optional_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, number)


def _positive_int(value: Any) -> int:
    parsed = _optional_int(value)
    return int(parsed or 0)


def _group_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "default")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _has_explicit_boost_mode(raw: Any, hub_options: Any) -> bool:
    if isinstance(hub_options, dict) and (
        "boost_mode" in hub_options or "agent_hub_mode" in hub_options
    ):
        return True
    return isinstance(raw, dict) and ("boost_mode" in raw or "agent_hub_mode" in raw)
