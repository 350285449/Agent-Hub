from __future__ import annotations

import re
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


@dataclass(frozen=True, slots=True)
class BoostOptimizationPlan:
    """Concrete per-request plan derived from mode, task shape, and token pressure."""

    mode: str
    label: str
    behavior: str
    task_type: str
    context_policy: str
    model_policy: str
    validation_policy: str
    routing_mode: str
    repo_max_files: int
    repo_max_chars: int
    full_files: int
    compressed_files: int
    map_files: int
    retry_budget: int
    prefer_local: bool
    prefer_premium: bool
    compression_aggression: float
    target_context_ratio: float
    quality_weight: float
    cost_weight: float
    speed_weight: float
    risk_weight: float
    algorithms: list[str]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "label": self.label,
            "behavior": self.behavior,
            "task_type": self.task_type,
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
            "target_context_ratio": self.target_context_ratio,
            "quality_weight": self.quality_weight,
            "cost_weight": self.cost_weight,
            "speed_weight": self.speed_weight,
            "risk_weight": self.risk_weight,
            "algorithms": list(self.algorithms),
            "reasons": list(self.reasons),
        }

    def task_policy_dict(self) -> dict[str, str]:
        return {
            "task_type": self.task_type,
            "context_policy": self.context_policy,
            "model_policy": self.model_policy,
            "validation_policy": self.validation_policy,
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


def build_boost_plan(
    *,
    task_type: str,
    task_category: str = "",
    text: str = "",
    boost_mode: str = "balanced",
    estimated_input_tokens: int = 0,
    repo_size_bucket: str = "",
    risk_level: str = "",
    file_count: int = 0,
) -> BoostOptimizationPlan:
    """Build an adaptive request plan instead of relying on mode-wide constants.

    The plan intentionally stays deterministic and local-only: it uses task shape,
    token pressure, repository size, and risk to tune context breadth, compression,
    validation, and route efficiency weights.
    """

    mode = normalize_boost_mode(boost_mode)
    base = boost_policy(mode)
    task_policy = task_optimization_policy(
        task_type=task_type,
        task_category=task_category,
        text=text,
        boost_mode=mode,
    )
    optimizer_task = task_policy["task_type"]
    repo_max_files = base.repo_max_files
    repo_max_chars = base.repo_max_chars
    full_files = base.full_files
    compressed_files = base.compressed_files
    map_files = base.map_files
    retry_budget = base.retry_budget
    compression = base.compression_aggression
    target_context_ratio = {
        "save_tokens": 0.36,
        "fast_fix": 0.46,
        "balanced": 0.62,
        "local_first": 0.58,
        "best_code": 0.78,
        "big_refactor": 0.88,
    }.get(mode, 0.62)
    quality_weight = {
        "save_tokens": 0.86,
        "fast_fix": 0.92,
        "balanced": 1.0,
        "local_first": 0.96,
        "best_code": 1.26,
        "big_refactor": 1.2,
    }.get(mode, 1.0)
    cost_weight = {
        "save_tokens": 1.38,
        "fast_fix": 1.08,
        "balanced": 1.0,
        "local_first": 1.16,
        "best_code": 0.78,
        "big_refactor": 0.86,
    }.get(mode, 1.0)
    speed_weight = 1.22 if mode == "fast_fix" else 1.0
    risk_weight = 1.0
    algorithms = [
        "task_policy_matrix",
        "adaptive_context_budgeting",
        "evidence_pyramid",
        "semantic_delta_compaction",
        "query_focused_extraction",
        "budgeted_mmr_context_selection",
        "budgeted_context_knapsack",
        "cached_context_replay",
        "success_per_token_routing",
    ]
    reasons: list[str] = [f"Started from {base.label} mode."]

    if optimizer_task in {"explanation", "docs"}:
        repo_max_files = min(repo_max_files, 2 if mode == "save_tokens" else 3)
        repo_max_chars = min(repo_max_chars, 3_200 if mode == "save_tokens" else 5_000)
        full_files = 0
        compressed_files = min(compressed_files, 1)
        map_files = min(map_files, 2)
        compression += 0.12
        target_context_ratio = min(target_context_ratio, 0.42)
        cost_weight += 0.14
        algorithms.append("lightweight_intent_gate")
        algorithms.append("proactive_token_targeting")
        reasons.append("Explanation/docs tasks use compressed summaries instead of broad repo context.")
    elif optimizer_task == "bug_fix":
        repo_max_files = min(repo_max_files, max(4, file_count + 2 if file_count else 6))
        repo_max_chars = min(repo_max_chars, 10_000 if mode != "save_tokens" else 6_000)
        full_files = min(max(2, full_files), repo_max_files)
        compressed_files = min(max(2, compressed_files), max(0, repo_max_files - full_files))
        map_files = min(map_files, 4)
        compression += 0.06
        speed_weight += 0.08
        algorithms.append("anchored_bug_context")
        reasons.append("Bug-fix tasks prioritize mentioned files, stack traces, and nearest tests.")
    elif optimizer_task in {"refactor", "repo_analysis"}:
        repo_max_files = max(repo_max_files, 10 if optimizer_task == "refactor" else 8)
        repo_max_chars = max(repo_max_chars, 22_000 if mode != "save_tokens" else 12_000)
        full_files = max(full_files, 2)
        compressed_files = max(compressed_files, 5)
        map_files = max(map_files, 8)
        compression = max(0.3, compression - 0.06)
        target_context_ratio = max(target_context_ratio, 0.72)
        quality_weight += 0.08
        algorithms.append("broad_map_with_evidence_caps")
        reasons.append("Large repository tasks keep a broad map while capping full-file evidence.")
    elif optimizer_task == "test_generation":
        repo_max_files = min(max(repo_max_files, 7), 10)
        full_files = min(max(2, full_files), repo_max_files)
        compressed_files = min(max(3, compressed_files), max(0, repo_max_files - full_files))
        algorithms.append("source_test_pairing")
        reasons.append("Test generation pairs source files with nearby tests and validation targets.")
    elif optimizer_task in {"security", "performance"}:
        repo_max_files = max(repo_max_files, 8)
        repo_max_chars = max(repo_max_chars, 14_000)
        full_files = max(full_files, 2)
        compression = max(0.28, compression - 0.04)
        quality_weight += 0.12
        risk_weight += 0.16 if optimizer_task == "security" else 0.06
        algorithms.append("risk_weighted_validation")
        reasons.append("High-risk or performance tasks preserve more evidence and favor stronger validation.")

    pressure = _token_pressure(estimated_input_tokens)
    if pressure > 0:
        reduction = 1.0 - min(0.34, pressure * (0.12 + compression * 0.18))
        repo_max_chars = max(2_400, int(repo_max_chars * reduction))
        if optimizer_task not in {"refactor", "repo_analysis", "security"}:
            repo_max_files = max(2, int(round(repo_max_files * (1.0 - min(0.25, pressure * 0.18)))))
        compression += 0.08 * pressure
        target_context_ratio = max(0.26, target_context_ratio - 0.16 * pressure)
        cost_weight += 0.08 * pressure
        algorithms.append("token_pressure_scaling")
        algorithms.append("entropy_ranked_context_trim")
        reasons.append("High prompt token pressure tightened context and raised compression.")

    repo_size = str(repo_size_bucket or "").lower()
    if repo_size in {"large", "xlarge"}:
        repo_max_files = max(repo_max_files, 10 if mode != "save_tokens" else 6)
        repo_max_chars = min(repo_max_chars, 18_000 if mode == "save_tokens" else repo_max_chars)
        map_files = max(map_files, min(10, repo_max_files))
        compression += 0.04
        algorithms.append("large_repo_map_first")
        reasons.append("Large repositories emphasize map-level context before full-file expansion.")

    risk = str(risk_level or "").lower()
    if risk in {"high", "critical"}:
        quality_weight += 0.1
        risk_weight += 0.22 if risk == "critical" else 0.14
        cost_weight = max(0.72, cost_weight - 0.08)
        retry_budget = max(retry_budget, 2)
        algorithms.append("risk_guarded_escalation")
        reasons.append("Risk level keeps quality and retry safeguards above pure cost savings.")

    if file_count and file_count <= 3 and optimizer_task not in {"refactor", "repo_analysis"}:
        repo_max_files = min(repo_max_files, max(3, file_count + 2))
        map_files = min(map_files, 3)
        algorithms.append("explicit_file_focus")
        reasons.append("Explicit file references narrow context to nearby evidence.")

    repo_max_files = max(1, int(repo_max_files))
    repo_max_chars = max(1_000, int(repo_max_chars))
    full_files = min(max(0, int(full_files)), repo_max_files)
    compressed_files = min(max(0, int(compressed_files)), max(0, repo_max_files - full_files))
    map_files = min(max(0, int(map_files)), max(0, repo_max_files - full_files - compressed_files))
    compression = round(_clamp(compression, 0.18, 0.92), 3)
    target_context_ratio = round(_clamp(target_context_ratio, 0.22, 0.94), 3)
    return BoostOptimizationPlan(
        mode=mode,
        label=base.label,
        behavior=base.behavior,
        task_type=optimizer_task,
        context_policy=task_policy["context_policy"],
        model_policy=task_policy["model_policy"],
        validation_policy=task_policy["validation_policy"],
        routing_mode=base.routing_mode,
        repo_max_files=repo_max_files,
        repo_max_chars=repo_max_chars,
        full_files=full_files,
        compressed_files=compressed_files,
        map_files=map_files,
        retry_budget=retry_budget,
        prefer_local=base.prefer_local,
        prefer_premium=base.prefer_premium,
        compression_aggression=compression,
        target_context_ratio=target_context_ratio,
        quality_weight=round(_clamp(quality_weight, 0.5, 1.7), 3),
        cost_weight=round(_clamp(cost_weight, 0.45, 1.8), 3),
        speed_weight=round(_clamp(speed_weight, 0.5, 1.6), 3),
        risk_weight=round(_clamp(risk_weight, 0.7, 1.8), 3),
        algorithms=_dedupe_strings(algorithms),
        reasons=_dedupe_strings(reasons)[:8],
    )


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


def _token_pressure(estimated_input_tokens: int) -> float:
    try:
        tokens = max(0, int(estimated_input_tokens or 0))
    except (TypeError, ValueError):
        return 0.0
    if tokens <= 4_000:
        return 0.0
    if tokens >= 32_000:
        return 1.0
    return (tokens - 4_000) / 28_000


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = re.sub(r"\s+", " ", str(value or "")).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


__all__ = [
    "BOOST_MODE_ALIASES",
    "BOOST_MODES",
    "BoostOptimizationPlan",
    "BoostModePolicy",
    "build_boost_plan",
    "boost_mode_from_request",
    "boost_policy",
    "normalize_boost_mode",
    "optimizer_task_type_for",
    "task_optimization_policy",
]
