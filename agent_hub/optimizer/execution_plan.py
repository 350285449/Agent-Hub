from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

from .context_plan import ContextFile, ContextPlan
from .modes import boost_mode_from_request, boost_policy, normalize_boost_mode
from .retry_policy import RetryPolicy, retry_policy_for
from .task_profile import task_optimization_policy
from .token_budget import TokenBudget
from .validator import validation_gates_for_task


@dataclass(frozen=True, slots=True)
class OptimizationPlan:
    """Concrete per-request plan read by routing, context, retry, and validation."""

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
    boost_mode: str = ""
    selected_files: list[str] = field(default_factory=list)
    omitted_files: list[str] = field(default_factory=list)
    context_levels: dict[str, str] = field(default_factory=dict)
    context_files: list[ContextFile] = field(default_factory=list)
    context_level_counts: dict[str, int] = field(default_factory=dict)
    token_budget: TokenBudget = field(default_factory=TokenBudget)
    preferred_models: list[str] = field(default_factory=list)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    validation_gates: list[dict[str, Any]] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.boost_mode:
            object.__setattr__(self, "boost_mode", self.mode)
        if not self.explanation:
            object.__setattr__(self, "explanation", list(self.reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.optimization_plan",
            "mode": self.mode,
            "boost_mode": self.boost_mode or self.mode,
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
            "selected_files": list(self.selected_files),
            "omitted_files": list(self.omitted_files),
            "context_levels": dict(self.context_levels),
            "context_files": [file.to_dict() for file in self.context_files],
            "context_level_counts": dict(self.context_level_counts),
            "token_budget": self.token_budget.to_dict(),
            "preferred_models": list(self.preferred_models),
            "retry_policy": self.retry_policy.to_dict(),
            "validation_gates": list(self.validation_gates),
            "explanation": list(self.explanation),
        }

    def task_policy_dict(self) -> dict[str, str]:
        return {
            "task_type": self.task_type,
            "context_policy": self.context_policy,
            "model_policy": self.model_policy,
            "validation_policy": self.validation_policy,
        }

    def with_context_plan(self, context_plan: ContextPlan | dict[str, Any]) -> "OptimizationPlan":
        if isinstance(context_plan, ContextPlan):
            selected_files = context_plan.selected_files
            omitted_files = context_plan.omitted_files
            context_levels = context_plan.legacy_levels()
            context_files = list(context_plan.context_files)
            level_counts = context_plan.level_counts()
            token_budget = replace(
                self.token_budget,
                raw_context_tokens=context_plan.raw_context_tokens,
                optimized_context_tokens=context_plan.optimized_context_tokens,
            )
        else:
            selected_files = [str(path) for path in context_plan.get("selected_files", []) if isinstance(path, str)]
            omitted_files = [str(path) for path in context_plan.get("omitted_files", context_plan.get("excluded_files", [])) if isinstance(path, str)]
            context_levels = {
                str(path): str(level)
                for path, level in (context_plan.get("context_levels") or context_plan.get("levels") or {}).items()
            }
            context_files = [
                ContextFile.from_dict(item)
                for item in context_plan.get("context_files", [])
                if isinstance(item, dict)
            ]
            level_counts = dict(context_plan.get("level_counts") or context_plan.get("context_level_counts") or {})
            token_budget = self.token_budget.with_context_usage(
                {
                    "original_context_tokens": context_plan.get("original_context_tokens")
                    or context_plan.get("raw_context_tokens"),
                    "optimized_context_tokens": context_plan.get("optimized_context_tokens"),
                }
            )
        return replace(
            self,
            selected_files=selected_files,
            omitted_files=omitted_files,
            context_levels=context_levels,
            context_files=context_files,
            context_level_counts=level_counts,
            token_budget=token_budget,
        )

    def with_context_usage(self, usage: dict[str, Any]) -> "OptimizationPlan":
        return replace(self, token_budget=self.token_budget.with_context_usage(usage))


BoostOptimizationPlan = OptimizationPlan


def build_optimization_plan(
    *,
    task_type: str,
    task_category: str = "",
    text: str = "",
    boost_mode: str = "balanced",
    estimated_input_tokens: int = 0,
    repo_size_bucket: str = "",
    risk_level: str = "",
    file_count: int = 0,
) -> OptimizationPlan:
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
    token_budget = TokenBudget(
        context_budget=base.context_mode,
        raw_context_tokens=max(0, int(estimated_input_tokens or 0)),
        optimized_context_tokens=0,
        max_context_tokens=repo_max_chars // 4,
        target_context_tokens=max(1_000, int((repo_max_chars // 4) * target_context_ratio)),
        target_context_ratio=target_context_ratio,
        compression=_compression_name(compression),
    )
    return OptimizationPlan(
        mode=mode,
        boost_mode=mode,
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
        token_budget=token_budget,
        preferred_models=_preferred_model_policy(task_policy["model_policy"], mode),
        retry_policy=retry_policy_for(boost_mode=mode, task_type=optimizer_task, retry_budget=retry_budget),
        validation_gates=[gate.to_dict() for gate in validation_gates_for_task(optimizer_task)],
    )


build_boost_plan = build_optimization_plan


def optimization_plan_from_dict(data: dict[str, Any] | None) -> OptimizationPlan | None:
    if not isinstance(data, dict):
        return None
    required = ("task_type", "context_policy", "model_policy", "validation_policy")
    if not all(key in data for key in required):
        return None
    mode = normalize_boost_mode(data.get("boost_mode") or data.get("mode") or "balanced")
    base = boost_policy(mode)
    context_files = [
        ContextFile.from_dict(item)
        for item in data.get("context_files", [])
        if isinstance(item, dict)
    ]
    retry_policy = RetryPolicy.from_dict(data.get("retry_policy") if isinstance(data.get("retry_policy"), dict) else None)
    token_budget = TokenBudget.from_dict(data.get("token_budget") if isinstance(data.get("token_budget"), dict) else None)
    return OptimizationPlan(
        mode=mode,
        boost_mode=mode,
        label=str(data.get("label") or base.label),
        behavior=str(data.get("behavior") or base.behavior),
        task_type=str(data.get("task_type") or "explanation"),
        context_policy=str(data.get("context_policy") or base.context_policy),
        model_policy=str(data.get("model_policy") or base.model_policy),
        validation_policy=str(data.get("validation_policy") or base.validation_policy),
        routing_mode=str(data.get("routing_mode") or base.routing_mode),
        repo_max_files=_int(data.get("repo_max_files"), base.repo_max_files),
        repo_max_chars=_int(data.get("repo_max_chars"), base.repo_max_chars),
        full_files=_int(data.get("full_files"), base.full_files),
        compressed_files=_int(data.get("compressed_files"), base.compressed_files),
        map_files=_int(data.get("map_files"), base.map_files),
        retry_budget=_int(data.get("retry_budget"), retry_policy.max_retries),
        prefer_local=bool(data.get("prefer_local", base.prefer_local)),
        prefer_premium=bool(data.get("prefer_premium", base.prefer_premium)),
        compression_aggression=_float(data.get("compression_aggression"), base.compression_aggression),
        target_context_ratio=_float(data.get("target_context_ratio"), token_budget.target_context_ratio),
        quality_weight=_float(data.get("quality_weight"), 1.0),
        cost_weight=_float(data.get("cost_weight"), 1.0),
        speed_weight=_float(data.get("speed_weight"), 1.0),
        risk_weight=_float(data.get("risk_weight"), 1.0),
        algorithms=[str(item) for item in data.get("algorithms", []) if isinstance(item, str)],
        reasons=[str(item) for item in data.get("reasons", []) if isinstance(item, str)],
        selected_files=[str(item) for item in data.get("selected_files", []) if isinstance(item, str)],
        omitted_files=[str(item) for item in data.get("omitted_files", []) if isinstance(item, str)],
        context_levels={
            str(key): str(value)
            for key, value in (data.get("context_levels") or {}).items()
        }
        if isinstance(data.get("context_levels"), dict)
        else {},
        context_files=context_files,
        context_level_counts=dict(data.get("context_level_counts") or {}),
        token_budget=token_budget,
        preferred_models=[str(item) for item in data.get("preferred_models", []) if isinstance(item, str)],
        retry_policy=retry_policy,
        validation_gates=list(data.get("validation_gates") or []),
        explanation=[str(item) for item in data.get("explanation", data.get("reasons", [])) if isinstance(item, str)],
    )


def optimization_plan_from_request(request: Any) -> OptimizationPlan | None:
    raw = getattr(request, "raw", {}) if request is not None else {}
    hub = raw.get("agent_hub") if isinstance(raw, dict) and isinstance(raw.get("agent_hub"), dict) else {}
    for key in ("optimization_plan", "boost_plan"):
        plan = optimization_plan_from_dict(hub.get(key) if isinstance(hub.get(key), dict) else None)
        if plan is not None:
            return plan
    return None


def build_plan_for_request(
    request: Any,
    classification: Any,
    *,
    default_boost_mode: str = "balanced",
) -> OptimizationPlan:
    existing = optimization_plan_from_request(request)
    if existing is not None:
        return existing
    mode = boost_mode_from_request(request, default=default_boost_mode)
    return build_optimization_plan(
        task_type=getattr(classification, "task_type", "general"),
        task_category=getattr(classification, "task_category", ""),
        text=getattr(classification, "text", "") or _request_text_fallback(request),
        boost_mode=mode,
        estimated_input_tokens=getattr(classification, "estimated_input_tokens", 0),
        repo_size_bucket=getattr(classification, "repo_size_bucket", ""),
        risk_level=getattr(classification, "risk_level", ""),
        file_count=len(getattr(classification, "files_involved", []) or []),
    )


def _request_text_fallback(request: Any) -> str:
    parts = [str(getattr(request, "task", "") or ""), str(getattr(request, "context", "") or "")]
    for message in getattr(request, "messages", []) or []:
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "\n".join(part for part in parts if part)


def _preferred_model_policy(model_policy: str, mode: str) -> list[str]:
    if model_policy in {"premium_first", "premium_review", "stronger_model"} or mode in {"best_code", "big_refactor"}:
        return ["premium", "coding", "reasoning", "long_context"]
    if model_policy in {"cheap_first", "fastest_successful"} or mode == "save_tokens":
        return ["free", "cheap", "fast"]
    if model_policy == "local_first":
        return ["local", "private", "free"]
    if model_policy in {"long_context", "long_context_quality"}:
        return ["long_context", "coding", "premium"]
    return ["best_outcome_per_token", "coding", "free"]


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


def _compression_name(aggression: float) -> str:
    if aggression >= 0.7:
        return "aggressive"
    if aggression <= 0.4:
        return "light"
    return "balanced"


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

