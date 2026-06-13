from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .optimizer import (
    evaluate_validation_gates,
    required_gate_failed,
    retry_strategy_for_failure as optimizer_retry_strategy_for_failure,
)
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
    task_type: str = "",
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
    workspace_validation = _workspace_patch_validation(
        text,
        root,
        validation_policy=validation_policy,
    )
    if workspace_validation.get("patch_applies") == "no":
        patch_applies = "no"
    token_budget = _token_budget_status(token_usage or {})
    task_alignment = _task_alignment_status(request_text(request), text)
    tests = _tests_status(token_usage or {})
    if workspace_validation.get("tests") in {"passed", "failed"}:
        tests = str(workspace_validation.get("tests"))
    optimizer_task_type = task_type or _optimizer_task_type_from_request(request)
    checks = {
        "answered_task": bool(text.strip()),
        "task_alignment": task_alignment,
        "modified_correct_files": "yes" if not wrong_files else "no",
        "hallucinated_files": "none" if not hallucinated else hallucinated[:12],
        "patch_applies": patch_applies,
        "syntax_valid": workspace_validation.get("syntax", "not_run"),
        "tests": tests,
        "lint_typecheck": workspace_validation.get("lint_typecheck", "not_run"),
        "workspace_patch_validation": workspace_validation,
        "extra_changes": "none" if not wrong_files else wrong_files[:12],
        "token_budget": token_budget,
        "validation_policy": validation_policy,
    }
    quality_gates = evaluate_validation_gates(
        task_type=optimizer_task_type,
        checks=checks,
        response_text=text,
    )
    checks["task_type"] = optimizer_task_type
    checks["quality_gates"] = quality_gates
    issues: list[str] = []
    if not text.strip():
        issues.append("response was empty")
    if hallucinated:
        issues.append("response referenced files not found in the workspace")
    if wrong_files:
        issues.append("response proposed edits outside selected/requested files")
    if patch_applies == "no":
        issues.append("patch structure did not look applicable")
    if workspace_validation.get("syntax") == "failed":
        issues.append("temporary workspace syntax check failed")
    if workspace_validation.get("tests") == "failed":
        issues.append("temporary workspace tests failed")
    if workspace_validation.get("lint_typecheck") == "failed":
        issues.append("temporary workspace lint/typecheck failed")
    if token_budget == "exceeded":
        issues.append("response exceeded the token budget")
    if task_alignment == "weak":
        issues.append("response has weak overlap with the requested task")

    strict_policy = validation_policy in {
        "strict_quality_checks",
        "security_checks",
        "grounding_check",
    }
    failed_hard = (
        not text.strip()
        or patch_applies == "no"
        or token_budget == "exceeded"
        or workspace_validation.get("syntax") == "failed"
        or (strict_policy and required_gate_failed(quality_gates))
    )
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
    return optimizer_retry_strategy_for_failure(reason)


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
    optimization_trace = hub.get("optimization_trace") if isinstance(hub.get("optimization_trace"), dict) else {}
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
        "optimization_trace": dict(optimization_trace),
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


def _workspace_patch_validation(
    text: str,
    root: Path,
    *,
    validation_policy: str,
) -> dict[str, Any]:
    patch = _extract_patch_text(text)
    if not patch:
        return {
            "status": "not_applicable",
            "patch_applies": "not_applicable",
            "syntax": "not_run",
            "tests": "not_run",
            "lint_typecheck": "not_run",
            "commands": [],
        }
    paths = _diff_paths(patch)
    if not paths:
        return {
            "status": "failed",
            "patch_applies": "no",
            "syntax": "not_run",
            "tests": "not_run",
            "lint_typecheck": "not_run",
            "commands": [],
            "error": "patch referenced no changed files",
        }
    try:
        with tempfile.TemporaryDirectory(prefix="agent-hub-patch-") as tmp:
            temp_root = Path(tmp) / "workspace"
            _copy_workspace(root, temp_root)
            check = _run_command(
                ["git", "apply", "--check", "-"],
                cwd=temp_root,
                input_text=patch,
                timeout=12,
            )
            commands = [check]
            if check["status"] != "passed":
                return {
                    "status": "failed",
                    "patch_applies": "no",
                    "syntax": "not_run",
                    "tests": "not_run",
                    "lint_typecheck": "not_run",
                    "commands": commands,
                    "error": check.get("stderr") or check.get("stdout") or "git apply --check failed",
                }
            applied = _run_command(
                ["git", "apply", "-"],
                cwd=temp_root,
                input_text=patch,
                timeout=12,
            )
            commands.append(applied)
            if applied["status"] != "passed":
                return {
                    "status": "failed",
                    "patch_applies": "no",
                    "syntax": "not_run",
                    "tests": "not_run",
                    "lint_typecheck": "not_run",
                    "commands": commands,
                    "error": applied.get("stderr") or applied.get("stdout") or "git apply failed",
                }
            syntax = _run_syntax_checks(temp_root, paths)
            commands.extend(syntax["commands"])
            tests = _run_focused_tests(temp_root, paths, validation_policy=validation_policy)
            commands.extend(tests["commands"])
            lint_typecheck = _run_lint_typecheck(temp_root, paths, validation_policy=validation_policy)
            commands.extend(lint_typecheck["commands"])
            status = "passed"
            if "failed" in {syntax["status"], tests["status"], lint_typecheck["status"]}:
                status = "failed"
            return {
                "status": status,
                "patch_applies": "yes",
                "syntax": syntax["status"],
                "tests": tests["status"],
                "lint_typecheck": lint_typecheck["status"],
                "commands": commands,
            }
    except Exception as exc:
        return {
            "status": "failed",
            "patch_applies": "no",
            "syntax": "not_run",
            "tests": "not_run",
            "lint_typecheck": "not_run",
            "commands": [],
            "error": str(exc),
        }


def _extract_patch_text(text: str) -> str:
    value = text or ""
    fenced = re.search(r"```(?:diff|patch)?\s*\n(.*?diff --git .*?)\n```", value, flags=re.DOTALL)
    if fenced:
        return fenced.group(1).strip() + "\n"
    index = value.find("diff --git ")
    if index >= 0:
        return value[index:].strip() + "\n"
    if re.search(r"^@@\s", value, flags=re.MULTILINE):
        return value.strip() + "\n"
    return ""


def _copy_workspace(root: Path, temp_root: Path) -> None:
    ignored = {
        ".git",
        ".agent-hub",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        ".venv-check",
        "__pycache__",
        "node_modules",
        "build",
        "dist",
        "coverage",
    }

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in ignored or name.endswith(".vsix")}

    shutil.copytree(root, temp_root, ignore=ignore)


def _run_syntax_checks(root: Path, paths: list[str]) -> dict[str, Any]:
    py_files = [
        path
        for path in paths
        if path.endswith(".py") and (root / path).exists()
    ]
    commands: list[dict[str, Any]] = []
    if not py_files:
        return {"status": "not_run", "commands": commands}
    status = "passed"
    for path in py_files[:20]:
        result = _run_command(
            [sys.executable, "-m", "py_compile", path],
            cwd=root,
            timeout=8,
        )
        commands.append(result)
        if result["status"] != "passed":
            status = "failed"
    return {"status": status, "commands": commands}


def _run_focused_tests(root: Path, paths: list[str], *, validation_policy: str) -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    test_paths = [
        path
        for path in paths
        if path.endswith(".py") and _is_test_counterpart(path, set(paths)) and (root / path).exists()
    ]
    if not test_paths:
        return {"status": "not_run", "commands": commands}
    if validation_policy not in {"run_tests", "strict_quality_checks", "run_targeted_tests", "security_checks"}:
        return {"status": "not_run", "commands": commands}
    pytest = _run_command(
        [sys.executable, "-m", "pytest", *test_paths[:8], "-q"],
        cwd=root,
        timeout=25,
    )
    commands.append(pytest)
    return {"status": pytest["status"], "commands": commands}


def _run_lint_typecheck(root: Path, paths: list[str], *, validation_policy: str) -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    if validation_policy not in {"strict_quality_checks", "security_checks"}:
        return {"status": "not_run", "commands": commands}
    py_files = [path for path in paths if path.endswith(".py") and (root / path).exists()]
    if not py_files:
        return {"status": "not_run", "commands": commands}
    status = "not_run"
    if shutil.which("ruff"):
        ruff = _run_command(["ruff", "check", *py_files[:20]], cwd=root, timeout=20)
        commands.append(ruff)
        status = "passed" if ruff["status"] == "passed" else "failed"
    if shutil.which("mypy"):
        mypy = _run_command(["mypy", *py_files[:20]], cwd=root, timeout=20)
        commands.append(mypy)
        if mypy["status"] != "passed":
            status = "failed"
        elif status == "not_run":
            status = "passed"
    return {"status": status, "commands": commands}


def _run_command(
    args: list[str],
    *,
    cwd: Path,
    timeout: int,
    input_text: str | None = None,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": _command_label(args),
            "status": "failed",
            "returncode": None,
            "stdout": str(exc.stdout or "")[:1200],
            "stderr": f"timed out after {timeout}s",
        }
    except OSError as exc:
        return {
            "command": _command_label(args),
            "status": "not_run",
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "command": _command_label(args),
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "")[:1200],
        "stderr": (completed.stderr or "")[:1200],
    }


def _command_label(args: list[str]) -> str:
    return " ".join(str(arg) for arg in args)


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


def _optimizer_task_type_from_request(request: Any) -> str:
    raw = getattr(request, "raw", {}) if request is not None else {}
    hub = raw.get("agent_hub") if isinstance(raw, dict) and isinstance(raw.get("agent_hub"), dict) else {}
    policy = hub.get("task_policy") if isinstance(hub.get("task_policy"), dict) else {}
    plan = hub.get("optimization_plan") if isinstance(hub.get("optimization_plan"), dict) else {}
    for source in (policy, plan):
        value = source.get("task_type") if isinstance(source, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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
