from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BoostModePolicy:
    """Product-facing mode that tunes policy before execution starts."""

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
    simple_mode: bool = True

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
            "simple_mode": self.simple_mode,
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
        repo_max_files=12,
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
        repo_max_files=8,
        repo_max_chars=7_000,
        full_files=1,
        compressed_files=2,
        map_files=5,
        retry_budget=1,
        compression_aggression=0.78,
    ),
    "best_code": BoostModePolicy(
        mode="best_code",
        label="Best Result",
        behavior="premium models + validation",
        context_mode="deep",
        context_policy="validated_context",
        model_policy="premium_first",
        validation_policy="strict_quality_checks",
        routing_mode="coding",
        repo_max_files=18,
        repo_max_chars=24_000,
        full_files=4,
        compressed_files=6,
        map_files=8,
        retry_budget=3,
        prefer_premium=True,
        compression_aggression=0.38,
    ),
    "turbo_boost": BoostModePolicy(
        mode="turbo_boost",
        label="Turbo Boost",
        behavior="adaptive max-performance routing",
        context_mode="deep",
        context_policy="adaptive_evidence_graph",
        model_policy="adaptive_quality_speed",
        validation_policy="confidence_gated_checks",
        routing_mode="coding",
        repo_max_files=24,
        repo_max_chars=30_000,
        full_files=4,
        compressed_files=7,
        map_files=10,
        retry_budget=3,
        prefer_premium=True,
        compression_aggression=0.42,
        simple_mode=False,
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
        repo_max_files=8,
        repo_max_chars=8_000,
        full_files=2,
        compressed_files=2,
        map_files=4,
        retry_budget=1,
        compression_aggression=0.65,
        simple_mode=False,
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
        repo_max_files=25,
        repo_max_chars=40_000,
        full_files=5,
        compressed_files=8,
        map_files=12,
        retry_budget=3,
        prefer_premium=True,
        compression_aggression=0.32,
        simple_mode=False,
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
        repo_max_files=12,
        repo_max_chars=12_000,
        full_files=2,
        compressed_files=4,
        map_files=6,
        retry_budget=2,
        prefer_local=True,
        compression_aggression=0.55,
        simple_mode=False,
    ),
}


BOOST_MODE_ALIASES = {
    "balanced": "balanced",
    "balance": "balanced",
    "default": "balanced",
    "auto": "balanced",
    "save": "save_tokens",
    "spend_less": "save_tokens",
    "spend-less": "save_tokens",
    "save_tokens": "save_tokens",
    "save-tokens": "save_tokens",
    "boost_save_tokens": "save_tokens",
    "boost-save-tokens": "save_tokens",
    "boost_and_save_tokens": "save_tokens",
    "boost-and-save-tokens": "save_tokens",
    "token_saver": "save_tokens",
    "token-saver": "save_tokens",
    "best": "best_code",
    "best_result": "best_code",
    "best-result": "best_code",
    "best_code": "best_code",
    "best-code": "best_code",
    "quality": "best_code",
    "boost": "turbo_boost",
    "turbo": "turbo_boost",
    "turbo_boost": "turbo_boost",
    "turbo-boost": "turbo_boost",
    "max_boost": "turbo_boost",
    "max-boost": "turbo_boost",
    "maximum_boost": "turbo_boost",
    "another_level": "turbo_boost",
    "another-level": "turbo_boost",
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
    text = str(value or "balanced").strip().lower()
    key = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    key = re.sub(r"_+", "_", key)
    if key in BOOST_MODE_ALIASES:
        return BOOST_MODE_ALIASES[key]
    words = set(key.split("_"))
    if "save" in words and ("token" in words or "tokens" in words):
        return "save_tokens"
    if "turbo" in words or ("boost" in words and not {"save", "token", "tokens"} & words):
        return "turbo_boost"
    if {"best", "code"} <= words or "quality" in words:
        return "best_code"
    if "local" in words:
        return "local_first"
    if "refactor" in words:
        return "big_refactor"
    if "fast" in words or "bug" in words:
        return "fast_fix"
    return "balanced"


def is_valid_boost_mode_value(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    key = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    key = re.sub(r"_+", "_", key)
    if key in BOOST_MODE_ALIASES:
        return True
    words = set(key.split("_"))
    if "save" in words and ("token" in words or "tokens" in words):
        return True
    if "turbo" in words or ("boost" in words and not {"save", "token", "tokens"} & words):
        return True
    if {"best", "code"} <= words or "quality" in words:
        return True
    if "local" in words:
        return True
    if "refactor" in words:
        return True
    if "fast" in words or "bug" in words:
        return True
    return False


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
