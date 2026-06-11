from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class OptimizationTrace:
    task_type: str
    mode: str
    raw_context_tokens: int
    optimized_context_tokens: int
    selected_files: int
    omitted_files: int
    route: str = ""
    validation: str = "pending"
    retry_count: int = 0
    tokens_saved_percent: float = 0.0
    estimated_tokens_saved: int = 0
    estimated_tokens_saved_percent: float = 0.0
    actual_provider_input_tokens: int | None = None
    actual_input_tokens_saved: int | None = None
    actual_input_tokens_saved_percent: float | None = None
    estimated_cost_saved_usd: float | None = None
    actual_cost_saved_usd: float | None = None
    token_accounting_source: str = "estimated"
    plan_diff: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "object": "agent_hub.optimization_trace",
            "task_type": self.task_type,
            "mode": self.mode,
            "raw_context_tokens": self.raw_context_tokens,
            "optimized_context_tokens": self.optimized_context_tokens,
            "selected_files": self.selected_files,
            "omitted_files": self.omitted_files,
            "route": self.route,
            "validation": self.validation,
            "retry_count": self.retry_count,
            "tokens_saved_percent": self.tokens_saved_percent,
            "estimated_tokens_saved": self.estimated_tokens_saved,
            "estimated_tokens_saved_percent": self.estimated_tokens_saved_percent,
            "actual_provider_input_tokens": self.actual_provider_input_tokens,
            "actual_input_tokens_saved": self.actual_input_tokens_saved,
            "actual_input_tokens_saved_percent": self.actual_input_tokens_saved_percent,
            "estimated_cost_saved_usd": self.estimated_cost_saved_usd,
            "actual_cost_saved_usd": self.actual_cost_saved_usd,
            "token_accounting_source": self.token_accounting_source,
        }
        if self.plan_diff:
            data["plan_diff"] = dict(self.plan_diff)
        return data


@dataclass(frozen=True, slots=True)
class BoostReport:
    plan: dict[str, Any]
    trace: OptimizationTrace
    validation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.boost_report",
            "plan": dict(self.plan),
            "trace": self.trace.to_dict(),
            "validation": dict(self.validation or {}),
        }


def trace_from_plan(
    plan: Any,
    *,
    route: str = "",
    validation: str = "pending",
    retry_count: int = 0,
    context_usage: dict[str, Any] | None = None,
    actual_usage: dict[str, Any] | None = None,
    estimated_cost_saved_usd: float | None = None,
    actual_cost_saved_usd: float | None = None,
    plan_diff: dict[str, Any] | None = None,
) -> OptimizationTrace:
    if isinstance(plan, dict):
        return trace_from_mapping(
            plan,
            route=route,
            validation=validation,
            retry_count=retry_count,
            context_usage=context_usage,
            actual_usage=actual_usage,
            estimated_cost_saved_usd=estimated_cost_saved_usd,
            actual_cost_saved_usd=actual_cost_saved_usd,
            plan_diff=plan_diff,
        )
    usage = context_usage or {}
    raw = _first_int(
        usage.get("original_input_tokens"),
        usage.get("original_context_tokens"),
        getattr(getattr(plan, "token_budget", None), "raw_context_tokens", None),
    )
    optimized = _first_int(
        usage.get("optimized_context_tokens"),
        usage.get("estimated_input_tokens"),
        getattr(getattr(plan, "token_budget", None), "optimized_context_tokens", None),
    )
    percent = _saved_percent(raw, optimized, usage.get("saved_percent"))
    actual_input = _usage_input_tokens(actual_usage or {})
    actual_saved = _actual_saved(raw, actual_input)
    return OptimizationTrace(
        task_type=str(getattr(plan, "task_type", "")),
        mode=str(getattr(plan, "boost_mode", getattr(plan, "mode", ""))),
        raw_context_tokens=raw,
        optimized_context_tokens=optimized,
        selected_files=len(getattr(plan, "selected_files", []) or []),
        omitted_files=_omitted_count(plan),
        route=route,
        validation=validation,
        retry_count=retry_count,
        tokens_saved_percent=percent,
        estimated_tokens_saved=max(0, raw - optimized),
        estimated_tokens_saved_percent=percent,
        actual_provider_input_tokens=actual_input,
        actual_input_tokens_saved=actual_saved,
        actual_input_tokens_saved_percent=_optional_saved_percent(raw, actual_input),
        estimated_cost_saved_usd=_optional_float(estimated_cost_saved_usd),
        actual_cost_saved_usd=_optional_float(actual_cost_saved_usd),
        token_accounting_source="actual_provider_usage" if actual_input is not None else "estimated",
        plan_diff=plan_diff,
    )


def trace_from_mapping(
    plan: dict[str, Any] | None,
    *,
    route: str = "",
    validation: str = "pending",
    retry_count: int = 0,
    context_usage: dict[str, Any] | None = None,
    actual_usage: dict[str, Any] | None = None,
    estimated_cost_saved_usd: float | None = None,
    actual_cost_saved_usd: float | None = None,
    plan_diff: dict[str, Any] | None = None,
) -> OptimizationTrace:
    data = plan if isinstance(plan, dict) else {}
    usage = context_usage or {}
    budget = data.get("token_budget") if isinstance(data.get("token_budget"), dict) else {}
    raw = _first_int(
        usage.get("original_input_tokens"),
        usage.get("original_context_tokens"),
        budget.get("raw_context_tokens"),
        data.get("raw_context_tokens"),
    )
    optimized = _first_int(
        usage.get("optimized_context_tokens"),
        usage.get("estimated_input_tokens"),
        budget.get("optimized_context_tokens"),
        data.get("optimized_context_tokens"),
    )
    selected = data.get("selected_files") if isinstance(data.get("selected_files"), list) else []
    omitted = data.get("omitted_files") if isinstance(data.get("omitted_files"), list) else []
    level_counts = data.get("context_level_counts") if isinstance(data.get("context_level_counts"), dict) else {}
    omitted_count = _first_int(level_counts.get("OMITTED"), len(omitted))
    estimated_saved = max(0, raw - optimized)
    estimated_percent = _saved_percent(raw, optimized, usage.get("saved_percent"))
    actual_input = _usage_input_tokens(actual_usage or {})
    actual_saved = _actual_saved(raw, actual_input)
    if plan_diff is None and isinstance(data.get("plan_diff"), dict):
        plan_diff = data.get("plan_diff")
    return OptimizationTrace(
        task_type=str(data.get("task_type") or ""),
        mode=str(data.get("boost_mode") or data.get("mode") or ""),
        raw_context_tokens=raw,
        optimized_context_tokens=optimized,
        selected_files=len(selected),
        omitted_files=omitted_count,
        route=route,
        validation=validation,
        retry_count=retry_count,
        tokens_saved_percent=estimated_percent,
        estimated_tokens_saved=estimated_saved,
        estimated_tokens_saved_percent=estimated_percent,
        actual_provider_input_tokens=actual_input,
        actual_input_tokens_saved=actual_saved,
        actual_input_tokens_saved_percent=_optional_saved_percent(raw, actual_input),
        estimated_cost_saved_usd=_optional_float(estimated_cost_saved_usd),
        actual_cost_saved_usd=_optional_float(actual_cost_saved_usd),
        token_accounting_source="actual_provider_usage" if actual_input is not None else "estimated",
        plan_diff=plan_diff,
    )


def _omitted_count(plan: Any) -> int:
    counts = getattr(plan, "context_level_counts", {}) or {}
    if isinstance(counts, dict) and counts.get("OMITTED") is not None:
        return _first_int(counts.get("OMITTED"))
    return len(getattr(plan, "omitted_files", []) or [])


def _saved_percent(raw: int, optimized: int, explicit: Any = None) -> float:
    try:
        if explicit is not None:
            return round(float(explicit), 1)
    except (TypeError, ValueError):
        pass
    if raw <= 0:
        return 0.0
    return round((max(0, raw - optimized) / max(1, raw)) * 100, 1)


def _optional_saved_percent(raw: int, actual: int | None) -> float | None:
    if actual is None or raw <= 0:
        return None
    return round((max(0, raw - actual) / max(1, raw)) * 100, 1)


def _actual_saved(raw: int, actual: int | None) -> int | None:
    if actual is None:
        return None
    return max(0, raw - actual)


def _usage_input_tokens(usage: dict[str, Any]) -> int | None:
    for key in ("prompt_tokens", "input_tokens", "provider_input_tokens"):
        value = usage.get(key)
        try:
            if value is not None:
                return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return None


def _optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return round(float(value), 8)
    except (TypeError, ValueError):
        return None


def _first_int(*values: Any) -> int:
    for value in values:
        try:
            if value is not None:
                return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0
