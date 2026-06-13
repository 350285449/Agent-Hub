from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    mode: str = "normal"
    max_retries: int = 1
    strategies: dict[str, str] | None = None

    def strategy_for(self, failure: str) -> str:
        mapping = self.strategies or default_retry_strategies()
        return mapping.get(normalize_failure_type(failure), mapping.get("default", "stronger_model"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "max_retries": self.max_retries,
            "strategies": dict(self.strategies or default_retry_strategies()),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RetryPolicy":
        if not isinstance(data, dict):
            return cls(strategies=default_retry_strategies())
        strategies = data.get("strategies") if isinstance(data.get("strategies"), dict) else default_retry_strategies()
        return cls(
            mode=str(data.get("mode") or "normal"),
            max_retries=_int(data.get("max_retries"), 1),
            strategies={str(key): str(value) for key, value in strategies.items()},
        )


def default_retry_strategies() -> dict[str, str]:
    return {
        "missing_context": "expand_context",
        "bad_patch": "stronger_model",
        "test_failure": "include_test_output",
        "hallucinated_file": "restrict_file_list",
        "low_confidence": "add_full_files",
        "token_budget": "compress_prompt",
        "default": "stronger_model",
    }


def retry_policy_for(*, boost_mode: str, task_type: str, retry_budget: int) -> RetryPolicy:
    mode = "normal"
    strategies = default_retry_strategies()
    if boost_mode == "save_tokens":
        mode = "cheap-first"
        strategies["bad_patch"] = "stronger_model"
        strategies["missing_context"] = "expand_context"
    elif boost_mode in {"best_code", "big_refactor"}:
        mode = "stronger-model"
        strategies["low_confidence"] = "add_full_files"
        strategies["bad_patch"] = "stronger_model"
    elif boost_mode == "turbo_boost":
        mode = "adaptive-escalation"
        strategies["missing_context"] = "expand_context"
        strategies["low_confidence"] = "add_full_files"
        strategies["bad_patch"] = "stronger_model"
        strategies["test_failure"] = "include_test_output"
        strategies["token_budget"] = "compress_prompt"
    elif boost_mode == "fast_fix":
        mode = "targeted"
        strategies["missing_context"] = "add_full_files"
    if task_type == "test_generation":
        strategies["test_failure"] = "include_test_output"
    return RetryPolicy(mode=mode, max_retries=max(0, int(retry_budget or 0)), strategies=strategies)


def normalize_failure_type(reason: str) -> str:
    text = str(reason or "").lower()
    if "context" in text or "weak overlap" in text or "missing" in text:
        return "missing_context"
    if "patch" in text or "applicable" in text:
        return "bad_patch"
    if "test" in text:
        return "test_failure"
    if "hallucinated" in text or "not found" in text:
        return "hallucinated_file"
    if "confidence" in text:
        return "low_confidence"
    if "token" in text or "budget" in text:
        return "token_budget"
    if "file" in text:
        return "hallucinated_file"
    return "default"


def retry_strategy_for_failure(reason: str, policy: RetryPolicy | None = None) -> str:
    failure = normalize_failure_type(reason)
    return (policy or RetryPolicy(strategies=default_retry_strategies())).strategy_for(failure)


def apply_retry_to_plan(
    plan: Any,
    *,
    reason: str,
    strategy: str = "",
    attempt: int = 1,
) -> Any:
    chosen = strategy or retry_strategy_for_failure(reason, getattr(plan, "retry_policy", None))
    algorithms = _append_unique(getattr(plan, "algorithms", []), "plan_based_retry")
    reasons = _append_unique(
        getattr(plan, "reasons", []),
        f"Retry {attempt} uses {chosen} because {reason or 'validation requested retry'}.",
    )
    kwargs: dict[str, Any] = {
        "algorithms": algorithms,
        "reasons": reasons,
    }
    if chosen in {"expand_context", "add_more_files"}:
        kwargs.update(
            repo_max_files=max(_int(getattr(plan, "repo_max_files", 0), 0) + 6, 8),
            repo_max_chars=max(_int(getattr(plan, "repo_max_chars", 0), 0) + 8_000, 12_000),
            compressed_files=max(_int(getattr(plan, "compressed_files", 0), 0) + 3, 4),
            map_files=max(_int(getattr(plan, "map_files", 0), 0) + 4, 6),
            target_context_ratio=min(0.94, float(getattr(plan, "target_context_ratio", 0.62) or 0.62) + 0.12),
            compression_aggression=max(0.18, float(getattr(plan, "compression_aggression", 0.55) or 0.55) - 0.08),
            context_policy="expanded_context",
        )
    elif chosen == "add_full_files":
        kwargs.update(
            full_files=max(_int(getattr(plan, "full_files", 0), 0) + 2, 2),
            repo_max_chars=max(_int(getattr(plan, "repo_max_chars", 0), 0) + 6_000, 10_000),
            target_context_ratio=min(0.94, float(getattr(plan, "target_context_ratio", 0.62) or 0.62) + 0.10),
            compression_aggression=max(0.18, float(getattr(plan, "compression_aggression", 0.55) or 0.55) - 0.10),
            context_policy="fuller_target_files",
        )
    elif chosen == "stronger_model":
        kwargs.update(
            model_policy="stronger_model",
            prefer_premium=True,
            quality_weight=min(1.7, float(getattr(plan, "quality_weight", 1.0) or 1.0) + 0.14),
            cost_weight=max(0.45, float(getattr(plan, "cost_weight", 1.0) or 1.0) - 0.08),
        )
    elif chosen == "include_test_output":
        kwargs.update(
            context_policy="tests_and_failure_output",
            validation_policy="run_tests",
            repo_max_chars=max(_int(getattr(plan, "repo_max_chars", 0), 0) + 4_000, 9_000),
        )
    elif chosen == "restrict_file_list":
        kwargs.update(
            context_policy="restricted_file_list",
            repo_max_files=max(1, min(_int(getattr(plan, "repo_max_files", 1), 1), len(getattr(plan, "selected_files", []) or []) or 3)),
            map_files=0,
        )
    elif chosen == "compress_prompt":
        kwargs.update(
            context_policy="aggressive_compression",
            target_context_ratio=max(0.22, float(getattr(plan, "target_context_ratio", 0.62) or 0.62) - 0.14),
            compression_aggression=min(0.92, float(getattr(plan, "compression_aggression", 0.55) or 0.55) + 0.12),
        )
    kwargs = _normalize_retry_limits(plan, kwargs)
    try:
        return replace(plan, **kwargs)
    except TypeError:
        return plan


def _append_unique(values: Any, value: str) -> list[str]:
    result = [str(item) for item in (values or [])]
    if value not in result:
        result.append(value)
    return result


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_retry_limits(plan: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    next_values = dict(kwargs)
    repo_max_files = max(1, _int(next_values.get("repo_max_files", getattr(plan, "repo_max_files", 1)), 1))
    full_files = min(max(0, _int(next_values.get("full_files", getattr(plan, "full_files", 0)), 0)), repo_max_files)
    compressed_files = min(
        max(0, _int(next_values.get("compressed_files", getattr(plan, "compressed_files", 0)), 0)),
        max(0, repo_max_files - full_files),
    )
    map_files = min(
        max(0, _int(next_values.get("map_files", getattr(plan, "map_files", 0)), 0)),
        max(0, repo_max_files - full_files - compressed_files),
    )
    next_values.update(
        repo_max_files=repo_max_files,
        full_files=full_files,
        compressed_files=compressed_files,
        map_files=map_files,
    )
    if "repo_max_chars" in next_values:
        next_values["repo_max_chars"] = max(1_000, _int(next_values["repo_max_chars"], 1_000))
    return next_values
