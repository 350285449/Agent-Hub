from __future__ import annotations

from typing import Any


def extract_risk_features(task: dict[str, Any] | None = None, *, candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    task = task or {}
    candidate = candidate or {}
    files_value = task.get("files_changed", task.get("files", task.get("target_files")))
    files = files_value if isinstance(files_value, list) else []
    file_count = len(files)
    if not file_count:
        try:
            file_count = int(files_value or task.get("file_count") or 0)
        except (TypeError, ValueError):
            file_count = 0
    context_tokens = int(task.get("context_tokens") or task.get("estimated_input_tokens") or candidate.get("estimated_input_tokens") or 0)
    model = str(candidate.get("model") or candidate.get("name") or "")
    task_text = str(task.get("description") or task.get("prompt") or task.get("task") or "")
    missing_files = bool(task.get("missing_files") or task.get("missing_file_risk"))
    if not missing_files and files:
        missing_files = any(str(value).strip().endswith("?") for value in files)
    return {
        "task_type": str(task.get("task_type") or "general"),
        "file_count": file_count,
        "files": [str(value) for value in files[:50]],
        "context_tokens": context_tokens,
        "risk_level": str(task.get("risk") or task.get("risk_level") or "low"),
        "model": model,
        "model_success_rate": candidate.get("success_rate"),
        "model_failure_rate": candidate.get("failure_rate"),
        "similar_failures": candidate.get("similar_failures", candidate.get("failed_similar_tasks")),
        "estimated_cost_usd": candidate.get("estimated_cost_usd"),
        "missing_files": missing_files,
        "tests_available": bool(task.get("tests_available", task.get("has_tests", True))),
        "public_api_change": bool(task.get("public_api_change") or "public api" in task_text.lower()),
        "is_refactor": "refactor" in str(task.get("task_type") or task_text).lower(),
        "is_docs_task": any(term in str(task.get("task_type") or task_text).lower() for term in ("doc", "readme", "comment")),
        "cheap_or_small_model": any(term in model.lower() for term in ("flash", "small", "mini", "local")),
        "repo_size": int(task.get("repo_size") or task.get("file_count") or file_count or 0),
        "language": str(task.get("language") or candidate.get("language") or "unknown"),
        "provider": str(candidate.get("provider") or candidate.get("name") or "unknown"),
        "retry_count": int(task.get("retry_count") or candidate.get("retry_count") or 0),
    }
