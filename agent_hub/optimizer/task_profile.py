from __future__ import annotations

from dataclasses import dataclass

from .modes import normalize_boost_mode


@dataclass(frozen=True, slots=True)
class TaskProfile:
    task_type: str
    context_policy: str
    model_policy: str
    validation_policy: str

    def to_dict(self) -> dict[str, str]:
        return {
            "task_type": self.task_type,
            "context_policy": self.context_policy,
            "model_policy": self.model_policy,
            "validation_policy": self.validation_policy,
        }


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
    return TaskProfile(
        task_type=optimizer_task_type,
        context_policy=context_policy,
        model_policy=model_policy,
        validation_policy=validation_policy,
    ).to_dict()


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

