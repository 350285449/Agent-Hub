from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BoostModePolicy:
    """Product-facing mode that tunes context, routing, validation, and retry shape."""

    mode: str
    label: str
    behavior: str
    context_mode: str
    context_policy: str
    model_policy: str
    validation_policy: str
    routing_mode: str = "auto"
    repo_max_files: int = 8
    repo_max_chars: int = 12_000
    full_files: int = 2
    compressed_files: int = 4
    map_files: int = 6
    retry_budget: int = 2
    prefer_local: bool = False
    prefer_premium: bool = False
    compression_aggression: float = 0.55

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "label": self.label,
            "behavior": self.behavior,
            "context_mode": self.context_mode,
            "context_policy": self.context_policy,
            "model_policy": self.model_policy,
            "validation_policy": self.validation_policy,
            "routing_mode": self.routing_mode,
            "repo_max_files": self.repo_max_files,
            "repo_max_chars": self.repo_max_chars,
            "full_files": self.full_files,
            "compressed_files": self.compressed_files,
            "map_files": self.map_files,
            "retry_budget": self.retry_budget,
            "prefer_local": self.prefer_local,
            "prefer_premium": self.prefer_premium,
            "compression_aggression": self.compression_aggression,
        }


BOOST_MODES: dict[str, BoostModePolicy] = {
    "balanced": BoostModePolicy(
        mode="balanced",
        label="Balanced",
        behavior="better code + fewer tokens",
        context_mode="balanced",
        context_policy="focused_files",
        model_policy="best_outcome_per_token",
        validation_policy="basic_quality_checks",
    ),
    "save_tokens": BoostModePolicy(
        mode="save_tokens",
        label="Save Tokens",
        behavior="aggressive context compression",
        context_mode="minimal",
        context_policy="aggressive_compression",
        model_policy="cheap_first",
        validation_policy="basic_quality_checks",
        routing_mode="cheapest",
        repo_max_files=5,
        repo_max_chars=7_000,
        full_files=1,
        compressed_files=2,
        map_files=5,
        retry_budget=1,
        compression_aggression=0.78,
    ),
    "best_code": BoostModePolicy(
        mode="best_code",
        label="Best Code",
        behavior="premium models + validation",
        context_mode="deep",
        context_policy="validated_context",
        model_policy="premium_first",
        validation_policy="strict_quality_checks",
        routing_mode="coding",
        repo_max_files=12,
        repo_max_chars=24_000,
        full_files=4,
        compressed_files=6,
        map_files=8,
        retry_budget=3,
        prefer_premium=True,
        compression_aggression=0.38,
    ),
    "fast_fix": BoostModePolicy(
        mode="fast_fix",
        label="Fast Fix",
        behavior="fastest route for small bugs",
        context_mode="minimal",
        context_policy="bug_fix_focus",
        model_policy="fastest_successful",
        validation_policy="run_targeted_tests",
        routing_mode="fastest",
        repo_max_files=6,
        repo_max_chars=8_000,
        full_files=2,
        compressed_files=2,
        map_files=4,
        retry_budget=1,
        compression_aggression=0.65,
    ),
    "big_refactor": BoostModePolicy(
        mode="big_refactor",
        label="Big Refactor",
        behavior="larger context + safer retry",
        context_mode="deep",
        context_policy="broad_repo_map",
        model_policy="long_context_quality",
        validation_policy="run_tests",
        routing_mode="long_context",
        repo_max_files=18,
        repo_max_chars=40_000,
        full_files=5,
        compressed_files=8,
        map_files=12,
        retry_budget=3,
        prefer_premium=True,
        compression_aggression=0.32,
    ),
    "local_first": BoostModePolicy(
        mode="local_first",
        label="Local First",
        behavior="Ollama/LM Studio before cloud",
        context_mode="balanced",
        context_policy="local_safe_context",
        model_policy="local_first",
        validation_policy="basic_quality_checks",
        routing_mode="local_private",
        repo_max_files=8,
        repo_max_chars=12_000,
        full_files=2,
        compressed_files=4,
        map_files=6,
        retry_budget=2,
        prefer_local=True,
        compression_aggression=0.55,
    ),
}

BOOST_MODE_ALIASES = {
    "balanced": "balanced",
    "balance": "balanced",
    "default": "balanced",
    "save": "save_tokens",
    "save_tokens": "save_tokens",
    "save-tokens": "save_tokens",
    "token_saver": "save_tokens",
    "token-saver": "save_tokens",
    "best": "best_code",
    "best_code": "best_code",
    "best-code": "best_code",
    "quality": "best_code",
    "fast": "fast_fix",
    "fast_fix": "fast_fix",
    "fast-fix": "fast_fix",
    "bug_fix": "fast_fix",
    "bug-fix": "fast_fix",
    "big": "big_refactor",
    "big_refactor": "big_refactor",
    "big-refactor": "big_refactor",
    "refactor": "big_refactor",
    "local": "local_first",
    "local_first": "local_first",
    "local-first": "local_first",
}


def normalize_boost_mode(value: Any) -> str:
    text = str(value or "balanced").strip().lower().replace(" ", "_")
    return BOOST_MODE_ALIASES.get(text, "balanced")


def boost_policy(mode: Any) -> BoostModePolicy:
    return BOOST_MODES[normalize_boost_mode(mode)]


def boost_mode_from_request(request: Any, default: str = "balanced") -> str:
    raw = getattr(request, "raw", {}) if request is not None else {}
    metadata = getattr(request, "metadata", {}) if request is not None else {}
    hub = raw.get("agent_hub") if isinstance(raw, dict) and isinstance(raw.get("agent_hub"), dict) else {}
    for source in (hub, raw if isinstance(raw, dict) else {}, metadata if isinstance(metadata, dict) else {}):
        for key in ("boost_mode", "agent_hub_mode", "mode"):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, str) and value.strip():
                return normalize_boost_mode(value)
    return normalize_boost_mode(default)


def task_optimization_policy(
    *,
    task_type: str,
    task_category: str = "",
    text: str = "",
    boost_mode: str = "balanced",
) -> dict[str, str]:
    optimizer_task_type = optimizer_task_type_for(
        task_type=task_type,
        task_category=task_category,
        text=text,
    )
    context_policy = {
        "bug_fix": "focused_files",
        "feature": "focused_files",
        "refactor": "broad_repo_map",
        "test_generation": "tests_and_sources",
        "explanation": "minimal_context",
        "repo_analysis": "repo_map",
        "ui_change": "ui_files_and_styles",
        "performance": "hot_paths_and_tests",
        "security": "focused_files_with_review",
        "docs": "docs_only",
    }.get(optimizer_task_type, "focused_files")
    model_policy = {
        "bug_fix": "cheap_first",
        "feature": "balanced_quality",
        "refactor": "quality_first",
        "test_generation": "cheap_first",
        "explanation": "cheap_first",
        "repo_analysis": "long_context",
        "ui_change": "ui_capable",
        "performance": "quality_first",
        "security": "premium_review",
        "docs": "cheap_first",
    }.get(optimizer_task_type, "balanced_quality")
    validation_policy = {
        "bug_fix": "run_tests",
        "feature": "basic_quality_checks",
        "refactor": "run_tests",
        "test_generation": "run_tests",
        "explanation": "answer_check",
        "repo_analysis": "grounding_check",
        "ui_change": "visual_or_snapshot_check",
        "performance": "run_benchmarks",
        "security": "security_checks",
        "docs": "docs_check",
    }.get(optimizer_task_type, "basic_quality_checks")
    mode = normalize_boost_mode(boost_mode)
    if mode == "save_tokens":
        model_policy = "cheap_first"
        context_policy = "aggressive_compression"
    elif mode == "best_code":
        model_policy = "premium_first"
        validation_policy = "strict_quality_checks"
    elif mode == "fast_fix":
        context_policy = "bug_fix_focus"
        model_policy = "fastest_successful"
    elif mode == "big_refactor":
        context_policy = "broad_repo_map"
        model_policy = "long_context_quality"
        validation_policy = "run_tests"
    elif mode == "local_first":
        model_policy = "local_first"
    return {
        "task_type": optimizer_task_type,
        "context_policy": context_policy,
        "model_policy": model_policy,
        "validation_policy": validation_policy,
    }


def optimizer_task_type_for(*, task_type: str, task_category: str = "", text: str = "") -> str:
    task = str(task_type or "general").lower()
    category = str(task_category or "").lower()
    haystack = f"{task} {category} {text.lower()}"
    if "security" in haystack or "secret" in haystack or task == "security_sensitive_change":
        return "security"
    if "performance" in haystack or "latency" in haystack or "slow" in haystack:
        return "performance"
    if "ui" in haystack or "react" in haystack or "css" in haystack or "frontend" in haystack:
        return "ui_change"
    if task in {"debug", "tool_use"} or "bug" in haystack or "fix" in haystack or "failing" in haystack:
        return "bug_fix"
    if task == "test_generation" or "test_generation" in haystack:
        return "test_generation"
    if task in {"documentation"} or "documentation" in haystack or "docs" in haystack:
        return "docs"
    if "refactor" in haystack:
        return "refactor"
    if task in {"simple_explanation"}:
        return "explanation"
    if task in {"long_context", "research"} or "repo_analysis" in haystack or "architecture" in haystack:
        return "repo_analysis"
    if task in {"coding"}:
        return "feature"
    return "repo_analysis" if "repo" in haystack else "explanation"


__all__ = [
    "BOOST_MODE_ALIASES",
    "BOOST_MODES",
    "BoostModePolicy",
    "boost_mode_from_request",
    "boost_policy",
    "normalize_boost_mode",
    "optimizer_task_type_for",
    "task_optimization_policy",
]
