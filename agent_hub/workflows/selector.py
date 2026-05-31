from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import HubConfig
from ..core.routing_policy import _request_has_tools, estimate_input_tokens
from ..models import HubRequest
from ..payloads import request_text


WORKFLOW_PATTERNS = {
    "direct_route",
    "single_worker",
    "planned_worker",
    "reviewed_worker",
    "team_reviewed",
}


@dataclass(frozen=True, slots=True)
class WorkflowSelection:
    pattern: str
    workflow_kind: str
    reason: str
    task_type: str
    estimated_input_tokens: int
    file_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "workflow_kind": self.workflow_kind,
            "reason": self.reason,
            "task_type": self.task_type,
            "estimated_input_tokens": self.estimated_input_tokens,
            "file_count": self.file_count,
        }


class WorkflowSelector:
    """Deterministic auto-mode selector for routing/workflow execution shape."""

    def __init__(self, config: HubConfig) -> None:
        self.config = config

    def select(self, request: HubRequest) -> WorkflowSelection:
        override = _workflow_pattern_override(request)
        text = request_text(request).lower()
        tokens = estimate_input_tokens(request)
        file_count = len(_path_like_tokens(request_text(request)))
        has_tools = _request_has_tools(request)
        task_type = _task_type(text, has_tools=has_tools, tokens=tokens)
        workflow_kind = _workflow_kind(text, task_type)
        if override:
            return WorkflowSelection(
                pattern=override,
                workflow_kind=workflow_kind,
                reason="Explicit agent_hub.workflow_pattern override.",
                task_type=task_type,
                estimated_input_tokens=tokens,
                file_count=file_count,
            )
        if _team_reviewed(text, tokens=tokens, file_count=file_count):
            return WorkflowSelection(
                pattern="team_reviewed",
                workflow_kind=workflow_kind,
                reason="Large or high-risk workspace task selected team review.",
                task_type=task_type,
                estimated_input_tokens=tokens,
                file_count=file_count,
            )
        if not has_tools and tokens < 1000 and task_type == "general" and not _critical_markers(text):
            return WorkflowSelection(
                pattern="direct_route",
                workflow_kind=workflow_kind,
                reason="Small general request can use direct routing.",
                task_type=task_type,
                estimated_input_tokens=tokens,
                file_count=file_count,
            )
        if (
            task_type in {"coding", "debug", "tool_use"}
            and tokens < 4000
            and file_count <= 1
            and not _critical_markers(text)
        ):
            return WorkflowSelection(
                pattern="single_worker",
                workflow_kind=workflow_kind,
                reason="Small coding/tool task can use one workspace worker.",
                task_type=task_type,
                estimated_input_tokens=tokens,
                file_count=file_count,
            )
        if _critical_markers(text) or file_count > 1 or task_type == "review":
            return WorkflowSelection(
                pattern="reviewed_worker",
                workflow_kind=workflow_kind,
                reason="Critical, review, or multi-file task selected planner-worker-reviewer.",
                task_type=task_type,
                estimated_input_tokens=tokens,
                file_count=file_count,
            )
        if task_type in {"coding", "debug"}:
            return WorkflowSelection(
                pattern="planned_worker",
                workflow_kind=workflow_kind,
                reason="Coding task needs a plan before worker execution.",
                task_type=task_type,
                estimated_input_tokens=tokens,
                file_count=file_count,
            )
        return WorkflowSelection(
            pattern="direct_route",
            workflow_kind=workflow_kind,
            reason="No workflow escalation markers were detected.",
            task_type=task_type,
            estimated_input_tokens=tokens,
            file_count=file_count,
        )


def with_workflow_selection_raw(request: HubRequest, selection: WorkflowSelection) -> dict[str, Any]:
    raw = dict(request.raw or {})
    raw["workflow_pattern"] = selection.pattern
    raw["workflow_selection"] = selection.pattern
    raw.setdefault("agent_hub", {})
    if isinstance(raw["agent_hub"], dict):
        raw["agent_hub"] = {
            **raw["agent_hub"],
            "workflow_pattern": selection.pattern,
            "workflow_selection": selection.to_dict(),
        }
    return raw


def _workflow_pattern_override(request: HubRequest) -> str:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    for value in (hub.get("workflow_pattern"), raw.get("workflow_pattern")):
        if isinstance(value, str):
            normalized = value.strip().lower().replace("-", "_")
            if normalized in WORKFLOW_PATTERNS:
                return normalized
    return ""


def _task_type(text: str, *, has_tools: bool, tokens: int) -> str:
    if tokens >= 24_000:
        return "long_context"
    if has_tools:
        return "tool_use"
    if any(marker in text for marker in ("debug", "traceback", "failing", "exception", "regression")):
        return "debug"
    if any(marker in text for marker in ("review", "audit", "check correctness", "security")):
        return "review"
    if any(marker in text for marker in ("research", "investigate", "find out", "summarize", "compare")):
        return "research"
    if any(marker in text for marker in ("code", "edit", "fix", "implement", "refactor", "test", "repo", "workspace")):
        return "coding"
    return "general"


def _workflow_kind(text: str, task_type: str) -> str:
    if "review" in text or task_type == "review":
        return "review"
    if "debug" in text or task_type == "debug":
        return "debug"
    if "refactor" in text:
        return "refactor"
    if "explain" in text:
        return "explain"
    return "code" if task_type in {"coding", "tool_use", "long_context"} else "explain"


def _team_reviewed(text: str, *, tokens: int, file_count: int) -> bool:
    if tokens >= 12_000 or file_count >= 5:
        return True
    return any(
        marker in text
        for marker in (
            "large",
            "migration",
            "architecture",
            "many files",
            "entire repo",
            "enterprise",
            "high risk",
            "critical path",
        )
    )


def _critical_markers(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "critical",
            "production",
            "security",
            "permission",
            "auth",
            "payment",
            "data loss",
            "breaking change",
            "must not regress",
            "review",
        )
    )


def _path_like_tokens(text: str) -> set[str]:
    return {
        token.strip("`'\".,;:()[]{}").replace("\\", "/")
        for token in re.findall(
            r"(?<![\w.-])(?:[\w.-]+/)+[\w.-]+|[\w.-]+\.(?:py|js|ts|tsx|jsx|json|md|toml|yml|yaml|css|html)",
            text,
        )
        if token
    }


__all__ = [
    "WORKFLOW_PATTERNS",
    "WorkflowSelection",
    "WorkflowSelector",
    "with_workflow_selection_raw",
]
