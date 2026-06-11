from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .payloads import request_text


PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_./-])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\."
    r"(?:py|js|jsx|ts|tsx|json|toml|yml|yaml|md|css|html|go|rs|java|cs|sh|ps1)"
)


@dataclass(slots=True)
class OutputValidationResult:
    passed: bool
    score: int
    total: int
    checks: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    retry_reason: str = ""
    retry_strategy: str = ""

    @property
    def should_retry(self) -> bool:
        return bool(self.retry_reason and self.retry_strategy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.output_validation",
            "status": "passed" if self.passed else "failed",
            "passed": self.passed,
            "score": self.score,
            "total": self.total,
            "summary": f"Quality Check: {'Passed' if self.passed else 'Failed'}",
            "checks": dict(self.checks),
            "issues": list(self.issues),
            "should_retry": self.should_retry,
            "retry_reason": self.retry_reason,
            "retry_strategy": self.retry_strategy,
        }


def validate_output(
    *,
    request: Any,
    response_text: str,
    workspace_dir: str | Path,
    selected_files: list[str] | None = None,
    token_usage: dict[str, Any] | None = None,
    validation_policy: str = "basic_quality_checks",
) -> OutputValidationResult:
    """Run deterministic, local quality checks for a provider response."""

    text = str(response_text or "")
    root = Path(workspace_dir)
    selected = {path.replace("\\", "/") for path in (selected_files or []) if isinstance(path, str)}
    mentioned = _mentioned_paths(text)
    diff_paths = _diff_paths(text)
    request_paths = set(_mentioned_paths(request_text(request)))
    all_paths = sorted({*mentioned, *diff_paths})
    hallucinated = [
        path
        for path in all_paths
        if not _path_exists_or_plausibly_new(root, path, diff_paths=diff_paths)
    ]
    wrong_files = [
        path
        for path in diff_paths
        if selected and path not in selected and path not in request_paths and not _is_test_counterpart(path, selected)
    ]
    patch_applies = _patch_status(text, root)
    token_budget = _token_budget_status(token_usage or {})
    task_alignment = _task_alignment_status(request_text(request), text)
    tests = _tests_status(token_usage or {})
    checks = {
        "answered_task": bool(text.strip()),
        "task_alignment": task_alignment,
        "modified_correct_files": "yes" if not wrong_files else "no",
        "hallucinated_files": "none" if not hallucinated else hallucinated[:12],
        "patch_applies": patch_applies,
        "tests": tests,
        "extra_changes": "none" if not wrong_files else wrong_files[:12],
        "token_budget": token_budget,
        "validation_policy": validation_policy,
    }
    issues: list[str] = []
    if not text.strip():
        issues.append("response was empty")
    if hallucinated:
        issues.append("response referenced files not found in the workspace")
    if wrong_files:
        issues.append("response proposed edits outside selected/requested files")
    if patch_applies == "no":
        issues.append("patch structure did not look applicable")
    if token_budget == "exceeded":
        issues.append("response exceeded the token budget")
    if task_alignment == "weak":
        issues.append("response has weak overlap with the requested task")

    failed_hard = not text.strip() or patch_applies == "no" or token_budget == "exceeded"
    retry_reason = ""
    retry_strategy = ""
    if failed_hard:
        retry_reason = issues[0] if issues else "quality validation failed"
        retry_strategy = retry_strategy_for_failure(retry_reason)
    scoreable = [
        bool(text.strip()),
        task_alignment != "weak",
        not wrong_files,
        not hallucinated,
        patch_applies != "no",
        tests in {"not_run", "passed"},
        not wrong_files,
        token_budget != "exceeded",
    ]
    score = sum(1 for item in scoreable if item)
    return OutputValidationResult(
        passed=not failed_hard,
        score=score,
        total=len(scoreable),
        checks=checks,
        issues=issues,
        retry_reason=retry_reason,
        retry_strategy=retry_strategy,
    )


def retry_strategy_for_failure(reason: str) -> str:
    text = reason.lower()
    if "context" in text or "weak overlap" in text:
        return "add_more_files"
    if "patch" in text:
        return "stronger_model"
    if "test" in text:
        return "include_test_output"
    if "file" in text:
        return "restrict_file_list"
    if "token" in text:
        return "compress_prompt"
    return "stronger_model"


def build_task_explanation(
    *,
    decision: Any,
    agent: Any,
    model: str,
    request: Any,
    quality: OutputValidationResult,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = getattr(request, "raw", {}) if request is not None else {}
    hub = raw.get("agent_hub") if isinstance(raw, dict) and isinstance(raw.get("agent_hub"), dict) else {}
    repo_context = hub.get("repo_context") if isinstance(hub.get("repo_context"), dict) else {}
    selected_files = repo_context.get("selected_files") if isinstance(repo_context.get("selected_files"), list) else []
    total_files = repo_context.get("total_files")
    context_usage = dict(usage or {})
    if not context_usage:
        context_usage = hub.get("context_usage") if isinstance(hub.get("context_usage"), dict) else {}
    tokens_saved = _int(context_usage.get("tokens_saved"), _int(repo_context.get("tokens_saved"), 0))
    original = _int(context_usage.get("original_input_tokens"), _int(repo_context.get("original_context_tokens"), 0))
    saved_percent = context_usage.get("saved_percent")
    if saved_percent is None:
        saved_percent = repo_context.get("saved_percent")
    if saved_percent is None and original > 0:
        saved_percent = round((tokens_saved / max(1, original)) * 100, 1)
    reason = getattr(decision, "reason", "") if decision is not None else ""
    return {
        "object": "agent_hub.task_explanation",
        "headline": "Agent Hub optimized this request",
        "boost_mode": getattr(decision, "boost_mode", None) if decision is not None else hub.get("boost_mode"),
        "files_selected": {
            "selected": len(selected_files),
            "total": total_files,
            "paths": selected_files[:20],
        },
        "tokens_saved": tokens_saved,
        "tokens_saved_percent": saved_percent,
        "model_selected": model or getattr(agent, "model", ""),
        "agent": getattr(agent, "name", ""),
        "provider": getattr(agent, "provider", ""),
        "reason": reason,
        "quality_check": quality.to_dict(),
    }


def _mentioned_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in PATH_PATTERN.finditer(text or ""):
        value = match.group(0).strip("./").replace("\\", "/")
        if value and value not in paths:
            paths.append(value)
    return paths[:80]


def _diff_paths(text: str) -> list[str]:
    paths: list[str] = []
    for line in (text or "").splitlines():
        if line.startswith(("+++ ", "--- ")):
            value = line[4:].strip()
            if value == "/dev/null":
                continue
            if value.startswith(("a/", "b/")):
                value = value[2:]
            value = value.replace("\\", "/")
            if value and value not in paths:
                paths.append(value)
        elif line.startswith("diff --git "):
            parts = line.split()
            for part in parts[-2:]:
                value = part[2:] if part.startswith(("a/", "b/")) else part
                value = value.replace("\\", "/")
                if value and value not in paths:
                    paths.append(value)
    return paths[:80]


def _path_exists_or_plausibly_new(root: Path, path: str, *, diff_paths: list[str]) -> bool:
    if path in diff_paths and not path.startswith(("../", "/")):
        return True
    try:
        resolved = (root / path).resolve()
        root_resolved = root.resolve()
    except OSError:
        return False
    if root_resolved not in resolved.parents and resolved != root_resolved:
        return False
    return resolved.exists()


def _patch_status(text: str, root: Path) -> str:
    if "diff --git " not in text and not re.search(r"^@@\s", text, flags=re.MULTILINE):
        return "not_applicable"
    paths = _diff_paths(text)
    if not paths:
        return "no"
    for path in paths:
        if path.startswith(("../", "/")):
            return "no"
        try:
            resolved = (root / path).resolve()
            root_resolved = root.resolve()
        except OSError:
            return "no"
        if root_resolved not in resolved.parents and resolved != root_resolved:
            return "no"
    return "yes"


def _token_budget_status(usage: dict[str, Any]) -> str:
    budget = _int(usage.get("max_context_tokens") or usage.get("budget_tokens"), 0)
    input_tokens = _int(usage.get("estimated_input_tokens") or usage.get("input_tokens"), 0)
    if budget <= 0 or input_tokens <= 0:
        return "unknown"
    return "within_budget" if input_tokens <= budget else "exceeded"


def _task_alignment_status(prompt: str, response: str) -> str:
    prompt_terms = _keywords(prompt)
    if not prompt_terms:
        return "unknown"
    response_text = response.lower()
    overlap = sum(1 for term in prompt_terms if term in response_text)
    return "ok" if overlap >= min(3, max(1, len(prompt_terms) // 5)) else "weak"


def _tests_status(usage: dict[str, Any]) -> str:
    validation = usage.get("validation") if isinstance(usage.get("validation"), dict) else {}
    if validation.get("passed") is True or validation.get("ok") is True:
        return "passed"
    if validation.get("passed") is False or validation.get("ok") is False:
        return "failed"
    return "not_run"


def _keywords(text: str) -> list[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "please",
        "implement",
        "create",
        "update",
        "change",
        "agent",
        "hub",
    }
    result: list[str] = []
    for word in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", text.lower())[:120]:
        if word not in stop and word not in result:
            result.append(word)
    return result[:40]


def _is_test_counterpart(path: str, selected: set[str]) -> bool:
    name = Path(path).name.lower()
    if "test" not in name and not path.startswith("tests/"):
        return False
    stem = name.replace("test_", "").replace("_test", "").split(".")[0]
    return any(stem and stem in Path(item).name.lower() for item in selected)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "OutputValidationResult",
    "build_task_explanation",
    "retry_strategy_for_failure",
    "validate_output",
]
