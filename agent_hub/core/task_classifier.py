from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import HubRequest
from ..payloads import content_to_text, request_text
from ..permissions import tool_permission_request
from .routing_policy import _request_has_tools, estimate_input_tokens


LONG_CONTEXT_TOKEN_THRESHOLD = 24_000
CODE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".ts",
    ".tsx",
}
DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}
CONFIG_EXTENSIONS = {".env", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".lock"}


@dataclass(frozen=True, slots=True)
class TaskClassification:
    """Workspace-aware task summary used by routing, dashboards, and workflows."""

    task_type: str
    routing_mode: str
    task_category: str = "general"
    language: str = "unknown"
    framework: str = "unknown"
    complexity: str = "low"
    risk_level: str = "low"
    required_capabilities: list[str] = field(default_factory=list)
    file_types: list[str] = field(default_factory=list)
    files_involved: list[str] = field(default_factory=list)
    repo_size_bucket: str = "unknown"
    context_estimate: str = "small"
    repository_context_needed: bool = False
    context_strategy: str = "standard"
    workflow_hint: str = ""
    reviewer_required: bool = False
    expected_cost: str = "low"
    permission_requirements: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    estimated_input_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "task_category": self.task_category,
            "routing_mode": self.routing_mode,
            "language": self.language,
            "framework": self.framework,
            "complexity": self.complexity,
            "risk_level": self.risk_level,
            "required_capabilities": list(self.required_capabilities),
            "file_types": list(self.file_types),
            "files_involved": list(self.files_involved),
            "repo_size_bucket": self.repo_size_bucket,
            "context_estimate": self.context_estimate,
            "repository_context_needed": self.repository_context_needed,
            "context_strategy": self.context_strategy,
            "workflow_hint": self.workflow_hint,
            "reviewer_required": self.reviewer_required,
            "expected_cost": self.expected_cost,
            "permission_requirements": list(self.permission_requirements),
            "reasons": list(self.reasons),
            "estimated_input_tokens": self.estimated_input_tokens,
        }

    def reason_sentence(self) -> str:
        if not self.reasons:
            return f"Classified as {self.task_type}; using {self.routing_mode} routing."
        return " ".join(self.reasons[:4])


class TaskClassifier:
    """Classify a request using task text, repository hints, file types, and risk."""

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        self.workspace_dir = Path(workspace_dir) if workspace_dir is not None else None
        self._workspace_size_cache: tuple[float, str] | None = None

    def classify(self, request: HubRequest) -> TaskClassification:
        raw_text = _classification_text(request)
        text = raw_text.lower()
        estimated_tokens = estimate_input_tokens(request)
        files_involved = _referenced_paths(raw_text, request)
        file_types = _referenced_file_types(raw_text, request, files_involved=files_involved)
        required = _required_capabilities(request, text, file_types)
        risk_level = _risk_level(request, text, file_types)
        repo_needed = _repo_context_needed(request, text, file_types)
        task_type = _task_type(request, text, estimated_tokens, file_types, risk_level)
        task_category = _task_category(task_type, text)
        language = _language(file_types, files_involved, text)
        framework = _framework(file_types, files_involved, text, language)
        repo_size_bucket = _repo_size_bucket(request, text, self.workspace_dir, self._workspace_size)
        context_estimate = _context_estimate(estimated_tokens, repo_size_bucket)
        complexity = _complexity(
            task_type=task_type,
            task_category=task_category,
            risk_level=risk_level,
            estimated_tokens=estimated_tokens,
            file_count=len(files_involved),
            repo_size_bucket=repo_size_bucket,
        )
        routing_mode = _routing_mode(task_type, risk_level, required, estimated_tokens, text)
        context_strategy = _context_strategy(task_type, estimated_tokens, repo_needed)
        workflow_hint = _workflow_hint(task_type, risk_level, text)
        reviewer_required = _reviewer_required(task_type, risk_level, text, files_involved)
        permission_requirements = _permission_requirements(request, text, file_types)
        expected_cost = _expected_cost(estimated_tokens, complexity, repo_size_bucket)
        reasons = _reasons(
            task_type=task_type,
            task_category=task_category,
            routing_mode=routing_mode,
            risk_level=risk_level,
            required=required,
            file_types=file_types,
            language=language,
            framework=framework,
            complexity=complexity,
            context_estimate=context_estimate,
            repo_needed=repo_needed,
            context_strategy=context_strategy,
            reviewer_required=reviewer_required,
        )
        return TaskClassification(
            task_type=task_type,
            task_category=task_category,
            routing_mode=routing_mode,
            language=language,
            framework=framework,
            complexity=complexity,
            risk_level=risk_level,
            required_capabilities=required,
            file_types=file_types,
            files_involved=files_involved,
            repo_size_bucket=repo_size_bucket,
            context_estimate=context_estimate,
            repository_context_needed=repo_needed,
            context_strategy=context_strategy,
            workflow_hint=workflow_hint,
            reviewer_required=reviewer_required,
            expected_cost=expected_cost,
            permission_requirements=permission_requirements,
            reasons=reasons,
            estimated_input_tokens=estimated_tokens,
        )

    def _workspace_size(self) -> str:
        if self.workspace_dir is None:
            return "unknown"
        now = self.workspace_dir.stat().st_mtime if self.workspace_dir.exists() else 0.0
        if self._workspace_size_cache and self._workspace_size_cache[0] == now:
            return self._workspace_size_cache[1]
        bucket = _scan_workspace_size_bucket(self.workspace_dir)
        self._workspace_size_cache = (now, bucket)
        return bucket


def classify_task(request: HubRequest) -> TaskClassification:
    return TaskClassifier().classify(request)


def _classification_text(request: HubRequest) -> str:
    parts = [request.task or "", request.context or ""]
    for message in request.messages:
        if not isinstance(message, dict):
            continue
        if message.get("agent_hub_repo_context"):
            continue
        parts.append(content_to_text(message.get("content")))
    return "\n".join(part for part in parts if part)


def _referenced_file_types(
    text: str,
    request: HubRequest,
    *,
    files_involved: list[str] | None = None,
) -> list[str]:
    values: list[str] = []
    for path in files_involved or _referenced_paths(text, request):
        suffix = Path(path).suffix.lower() or Path(path).name.lower()
        if suffix and suffix not in values:
            values.append(suffix)
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    for source in (raw, hub, request.metadata if isinstance(request.metadata, dict) else {}):
        for key in ("files", "active_files", "paths", "workspace_files"):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        suffix = Path(item).suffix.lower() or Path(item).name.lower()
                        if suffix and suffix not in values:
                            values.append(suffix)
    return values[:20]


def _referenced_paths(text: str, request: HubRequest | None = None) -> list[str]:
    paths: list[str] = []
    for token in re.split(r"\s+", text[:40_000]):
        if "." not in token or len(token) > 260:
            continue
        value = token.strip(".,;:()[]{}<>`'\"")
        suffix = Path(value).suffix.lower() or Path(value).name.lower()
        if suffix not in CODE_EXTENSIONS | DOC_EXTENSIONS | CONFIG_EXTENSIONS:
            continue
        if value and value not in paths:
            paths.append(value)
    for line in text.splitlines():
        label = re.match(r"\s*(?:Current file|File|Reference|Path):\s*(.+?)\s*$", line, re.I)
        if label:
            value = label.group(1).strip().strip("'\"")
            if value and value not in paths:
                paths.append(value)
    if request is not None:
        raw = request.raw if isinstance(request.raw, dict) else {}
        hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
        for source in (raw, hub, request.metadata if isinstance(request.metadata, dict) else {}):
            for key in ("files", "active_files", "paths", "workspace_files"):
                value = source.get(key) if isinstance(source, dict) else None
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item and item not in paths:
                            paths.append(item)
    return paths[:40]


def _required_capabilities(request: HubRequest, text: str, file_types: list[str]) -> list[str]:
    required: list[str] = []
    if _request_has_tools(request) or _tool_task_requested(text):
        required.append("tools")
    if any(ext in CODE_EXTENSIONS for ext in file_types) or _looks_like_coding_task(text):
        required.append("coding")
    if any(ext in CONFIG_EXTENSIONS for ext in file_types):
        required.append("config_awareness")
    if request.stream:
        required.append("streaming")
    if _looks_like_large_repo_task(text) or len(file_types) >= 4:
        required.append("long_context")
    if _looks_like_shell_task(text):
        required.append("shell_safety")
    return _dedupe(required)


def _risk_level(request: HubRequest, text: str, file_types: list[str]) -> str:
    risks = ["low"]
    raw = request.raw if isinstance(request.raw, dict) else {}
    for tool_name, key in (
        ("run_command", "command"),
        ("write_file", "path"),
        ("replace_in_file", "path"),
        ("apply_patch", "changes"),
    ):
        args = raw.get(tool_name)
        if isinstance(args, dict):
            risks.append(tool_permission_request(tool_name, args).risk_level)
        elif key in raw and tool_name == "run_command":
            risks.append(tool_permission_request(tool_name, raw).risk_level)
    if _looks_like_security_task(text):
        risks.append("high")
    if _looks_like_shell_task(text):
        risks.append("medium")
    if _looks_like_mutating_task(text):
        risks.append("medium")
    if any(ext in CONFIG_EXTENSIONS for ext in file_types):
        risks.append("high")
    if any(marker in text for marker in ("rm -rf", "git reset --hard", "delete old files", "drop database")):
        risks.append("critical")
    return _max_risk(risks)


def _repo_context_needed(request: HubRequest, text: str, file_types: list[str]) -> bool:
    if request.raw and isinstance(request.raw, dict):
        hub = request.raw.get("agent_hub")
        if isinstance(hub, dict) and hub.get("repo_context") is False:
            return False
    return (
        bool(file_types)
        or _looks_like_coding_task(text)
        or _tool_task_requested(text)
        or _looks_like_large_repo_task(text)
    )


def _task_type(
    request: HubRequest,
    text: str,
    estimated_tokens: int,
    file_types: list[str],
    risk_level: str,
) -> str:
    if _privacy_requested(request):
        return "local_private"
    if estimated_tokens >= LONG_CONTEXT_TOKEN_THRESHOLD or _looks_like_large_repo_task(text):
        return "long_context"
    if risk_level in {"high", "critical"} and _looks_like_mutating_task(text):
        return "security_sensitive_change"
    if _request_has_tools(request):
        return "tool_use"
    if _looks_like_shell_task(text):
        return "tool_use"
    if _looks_like_debug_task(text):
        return "debug"
    if _looks_like_test_generation_task(text):
        return "test_generation"
    if _looks_like_documentation_task(text):
        return "documentation"
    if _looks_like_review_task(text):
        return "review"
    if _looks_like_research_task(text):
        return "research"
    if _looks_like_coding_task(text) or any(ext in CODE_EXTENSIONS for ext in file_types):
        return "coding"
    if _looks_like_simple_explanation(text, estimated_tokens):
        return "simple_explanation"
    return "general"


def _routing_mode(
    task_type: str,
    risk_level: str,
    required: list[str],
    estimated_tokens: int,
    text: str,
) -> str:
    if task_type == "local_private":
        return "local_private"
    if task_type == "simple_explanation":
        return "cheapest"
    if task_type == "long_context" or "long_context" in required or estimated_tokens >= LONG_CONTEXT_TOKEN_THRESHOLD:
        return "long_context"
    if task_type == "security_sensitive_change" or risk_level in {"high", "critical"}:
        return "coding"
    if task_type in {"coding", "debug", "review", "tool_use", "test_generation"}:
        return "coding"
    if task_type == "documentation":
        return "cheapest" if risk_level == "low" else "best_available"
    if "quick" in text or "brief" in text or "fast" in text:
        return "fastest"
    return "best_available"


def _context_strategy(task_type: str, estimated_tokens: int, repo_needed: bool) -> str:
    if task_type == "long_context" or estimated_tokens >= LONG_CONTEXT_TOKEN_THRESHOLD:
        return "compress_and_inject_repo_map"
    if repo_needed:
        return "repo_map_injection"
    return "standard"


def _workflow_hint(task_type: str, risk_level: str, text: str) -> str:
    if task_type == "security_sensitive_change" or risk_level in {"high", "critical"}:
        return "reviewer_permission_gate"
    if "refactor" in text or "large change" in text:
        return "planner_coder_reviewer"
    if task_type == "debug":
        return "debugger_validator"
    if task_type == "test_generation":
        return "coder_test_validator"
    return ""


def _reasons(
    *,
    task_type: str,
    task_category: str,
    routing_mode: str,
    risk_level: str,
    required: list[str],
    file_types: list[str],
    language: str,
    framework: str,
    complexity: str,
    context_estimate: str,
    repo_needed: bool,
    context_strategy: str,
    reviewer_required: bool,
) -> list[str]:
    reasons = [
        (
            f"Task classified as {task_type} ({task_category}); "
            f"complexity {complexity}; routing mode {routing_mode}."
        )
    ]
    if required:
        reasons.append("Required capabilities: " + ", ".join(required) + ".")
    if language != "unknown":
        detail = language if framework == "unknown" else f"{language}/{framework}"
        reasons.append(f"Detected language/framework: {detail}.")
    if file_types:
        reasons.append("Detected workspace file types: " + ", ".join(file_types[:6]) + ".")
    reasons.append(f"Estimated context size: {context_estimate}.")
    if risk_level != "low":
        reasons.append(f"Risk level {risk_level}; permission and review gates stay active.")
    if repo_needed:
        reasons.append(f"Repository context strategy: {context_strategy}.")
    if reviewer_required:
        reasons.append("Reviewer workflow recommended for this risk and change pattern.")
    return reasons


def _task_category(task_type: str, text: str) -> str:
    if task_type == "simple_explanation":
        return "explanation"
    if task_type == "security_sensitive_change":
        return "security_sensitive_operation"
    if task_type == "tool_use":
        return "shell_tool_operation" if _looks_like_shell_task(text) else "tool_operation"
    if task_type == "long_context":
        return "large_context_repository_task"
    if task_type == "debug":
        return "debugging"
    if task_type == "test_generation":
        return "test_generation"
    if task_type == "documentation":
        return "documentation"
    if "refactor" in text:
        return "refactor"
    if task_type == "coding":
        return "code_generation"
    return task_type


def _language(file_types: list[str], files_involved: list[str], text: str) -> str:
    counts: dict[str, int] = {}
    for ext in file_types:
        language = _LANGUAGE_BY_EXTENSION.get(ext)
        if language:
            counts[language] = counts.get(language, 0) + 1
    lowered_paths = " ".join(files_involved).lower()
    for marker, language in (
        ("pyproject.toml", "python"),
        ("requirements.txt", "python"),
        ("package.json", "typescript"),
        ("tsconfig.json", "typescript"),
        ("go.mod", "go"),
        ("cargo.toml", "rust"),
        ("pom.xml", "java"),
    ):
        if marker in lowered_paths or marker in text:
            counts[language] = counts.get(language, 0) + 2
    if not counts:
        return "unknown"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _framework(file_types: list[str], files_involved: list[str], text: str, language: str) -> str:
    del file_types
    haystack = f"{text} {' '.join(files_involved).lower()}"
    if any(marker in haystack for marker in ("next.config", "nextjs", "next.js")):
        return "nextjs"
    if any(marker in haystack for marker in ("vite.config", "vite ")):
        return "vite"
    if any(marker in haystack for marker in ("react", ".tsx", ".jsx")) and language in {"typescript", "javascript"}:
        return "react"
    if "svelte.config" in haystack:
        return "svelte"
    if "vue.config" in haystack or ".vue" in haystack:
        return "vue"
    if any(marker in haystack for marker in ("fastapi", "uvicorn")):
        return "fastapi"
    if "django" in haystack:
        return "django"
    if "flask" in haystack:
        return "flask"
    if "pytest" in haystack:
        return "pytest"
    if language in {"go", "rust", "java", "csharp"}:
        return language
    return "unknown"


def _repo_size_bucket(
    request: HubRequest,
    text: str,
    workspace_dir: Path | None,
    workspace_size: Callable[[], str],
) -> str:
    del workspace_dir
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    for source in (raw, hub, metadata):
        value = source.get("repo_size_bucket") if isinstance(source, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
        count = source.get("repo_file_count") if isinstance(source, dict) else None
        if count is not None:
            return _repo_file_count_bucket(count)
    if _looks_like_large_repo_task(text):
        return "large"
    return workspace_size()


def _scan_workspace_size_bucket(workspace_dir: Path) -> str:
    if not workspace_dir.exists():
        return "unknown"
    count = 0
    ignored_dirs = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "build", "dist"}
    try:
        for path in workspace_dir.rglob("*"):
            if any(part in ignored_dirs for part in path.parts):
                continue
            if path.is_file():
                count += 1
                if count > 2500:
                    return "large"
    except OSError:
        return "unknown"
    return _repo_file_count_bucket(count)


def _repo_file_count_bucket(value: Any) -> str:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return "unknown"
    if count < 50:
        return "small"
    if count < 500:
        return "medium"
    if count < 2500:
        return "large"
    return "xlarge"


def _context_estimate(estimated_tokens: int, repo_size_bucket: str) -> str:
    if estimated_tokens >= LONG_CONTEXT_TOKEN_THRESHOLD or repo_size_bucket in {"large", "xlarge"}:
        return "large"
    if estimated_tokens >= 6_000 or repo_size_bucket == "medium":
        return "medium"
    return "small"


def _complexity(
    *,
    task_type: str,
    task_category: str,
    risk_level: str,
    estimated_tokens: int,
    file_count: int,
    repo_size_bucket: str,
) -> str:
    if (
        task_type == "long_context"
        or task_category in {"large_context_repository_task", "refactor"}
        or risk_level in {"high", "critical"}
        or estimated_tokens >= LONG_CONTEXT_TOKEN_THRESHOLD
        or repo_size_bucket in {"large", "xlarge"}
        or file_count >= 6
    ):
        return "high"
    if (
        task_type in {"coding", "debug", "review", "tool_use", "test_generation"}
        or file_count >= 2
        or estimated_tokens >= 3_000
        or risk_level == "medium"
    ):
        return "medium"
    return "low"


def _reviewer_required(task_type: str, risk_level: str, text: str, files_involved: list[str]) -> bool:
    if task_type == "security_sensitive_change" or risk_level in {"high", "critical"}:
        return True
    if len(files_involved) >= 4 and any(word in text for word in ("edit", "write", "refactor", "fix")):
        return True
    if _looks_like_shell_task(text) and _looks_like_mutating_task(text):
        return True
    return False


def _expected_cost(estimated_tokens: int, complexity: str, repo_size_bucket: str) -> str:
    if complexity == "high" or estimated_tokens >= LONG_CONTEXT_TOKEN_THRESHOLD or repo_size_bucket in {"large", "xlarge"}:
        return "high"
    if complexity == "medium" or estimated_tokens >= 4_000 or repo_size_bucket == "medium":
        return "medium"
    return "low"


def _permission_requirements(request: HubRequest, text: str, file_types: list[str]) -> list[str]:
    required: list[str] = []
    if _request_has_tools(request) or _tool_task_requested(text):
        required.append("tool_execution")
    if _looks_like_shell_task(text):
        required.append("shell_command")
    if _looks_like_mutating_task(text):
        required.append("file_write")
    if any(ext in CONFIG_EXTENSIONS for ext in file_types):
        required.append("config_write_review")
    if _looks_like_security_task(text):
        required.append("security_review")
    return _dedupe(required)


def _looks_like_simple_explanation(text: str, estimated_tokens: int) -> bool:
    if estimated_tokens > 3000:
        return False
    return bool(
        re.search(r"\b(explain|what is|what are|why|summarize|describe)\b", text)
        and not _looks_like_coding_task(text)
        and not _tool_task_requested(text)
    )


def _looks_like_coding_task(text: str) -> bool:
    return any(
        word in text
        for word in (
            "bug",
            "code",
            "debug",
            "edit",
            "error",
            "fix",
            "implement",
            "refactor",
            "repo",
            "test",
            "workspace",
        )
    )


def _looks_like_test_generation_task(text: str) -> bool:
    return bool(
        re.search(r"\b(add|create|generate|write|update)\b.*\b(test|tests|spec|coverage)\b", text)
        or re.search(r"\b(test generation|unit tests|integration tests)\b", text)
    )


def _looks_like_documentation_task(text: str) -> bool:
    return bool(
        re.search(r"\b(write|update|create|improve)\b.*\b(docs|documentation|readme|changelog)\b", text)
        or re.search(r"\b(document this|api docs|release notes)\b", text)
    )


def _looks_like_debug_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "debug",
            "failing",
            "failure",
            "traceback",
            "exception",
            "regression",
            "not working",
        )
    )


def _looks_like_review_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "review",
            "audit",
            "check my",
            "critique",
            "risk",
            "security",
            "correctness",
        )
    )


def _looks_like_research_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "research",
            "investigate",
            "find out",
            "compare",
            "search the web",
            "evaluate",
        )
    )


def _tool_task_requested(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "read ",
            "search",
            "file",
            "repo",
            "workspace",
            "run ",
            "command",
            "test",
            "edit",
            "write",
            "debug",
            "refactor",
        )
    )


def _looks_like_mutating_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "write",
            "edit",
            "replace",
            "delete",
            "remove",
            "install",
            "run command",
            "shell",
            "apply patch",
            "change config",
        )
    )


def _looks_like_security_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "security",
            "secret",
            "credential",
            "permission",
            "shell command",
            "delete",
            "install",
            "config",
            "workflow",
        )
    )


def _looks_like_shell_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "shell",
            "terminal",
            "run command",
            "execute command",
            "npm install",
            "pip install",
            "poetry add",
            "pnpm ",
            "yarn ",
            "git ",
            "docker ",
        )
    )


def _looks_like_large_repo_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "large repo",
            "entire repo",
            "whole codebase",
            "multi-file",
            "monolith",
            "architecture",
            "refactor large",
        )
    )


def _privacy_requested(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    for value in (
        hub.get("local_private"),
        hub.get("private"),
        hub.get("privacy"),
        hub.get("local_only"),
        raw.get("local_private"),
        raw.get("private"),
        raw.get("privacy"),
        raw.get("local_only"),
    ):
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "local", "private"}:
            return True
    return False


def _max_risk(values: list[str]) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return max(values, key=lambda value: order.get(value, 0))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


_LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".php": "php",
    ".rb": "ruby",
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
}


__all__ = [
    "LONG_CONTEXT_TOKEN_THRESHOLD",
    "TaskClassification",
    "TaskClassifier",
    "classify_task",
]
