from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import HubConfig
from ..models import HubRequest
from ..payloads import request_text


@dataclass(frozen=True, slots=True)
class WorkflowStage:
    name: str
    role: str
    preference: str


class WorkflowPlanner:
    """Deterministic workflow policy for stages, prompts, and local options."""

    WORKFLOWS = {"code", "review", "debug", "explain", "refactor", "issue-pr"}
    WORKFLOW_ALIASES = {
        "issue-to-pr": "issue-pr",
        "issue_pr": "issue-pr",
        "issue_to_pr": "issue-pr",
        "pull-request": "issue-pr",
        "pull_request": "issue-pr",
        "pr": "issue-pr",
    }

    def __init__(self, config: HubConfig) -> None:
        self.config = config

    def normalize(self, kind: str) -> str:
        normalized = kind.strip().lower().replace("_", "-")
        normalized = self.WORKFLOW_ALIASES.get(normalized, normalized)
        if normalized not in self.WORKFLOWS:
            raise ValueError(f"Unknown workflow {kind!r}")
        return normalized

    def stages(self, kind: str) -> list[WorkflowStage]:
        worker_role = {
            "code": "coder",
            "review": "reviewer",
            "debug": "coder",
            "explain": "explainer",
            "refactor": "coder",
            "issue-pr": "coder",
        }[kind]
        return [
            WorkflowStage("plan", "planner", "reasoning"),
            WorkflowStage("work", worker_role, "coding" if worker_role == "coder" else "reliable"),
            WorkflowStage("review", "reviewer", "reliable"),
        ]

    def stages_for_pattern(self, kind: str, pattern: str) -> list[WorkflowStage]:
        stages = self.stages(kind)
        if pattern == "planned_worker":
            return stages[:2]
        return stages

    def stage_prompt(self, kind: str, stage: WorkflowStage, request: HubRequest, memory: Any) -> str:
        task = request_text(request)
        prior = memory.prompt_context()
        if kind == "issue-pr" and stage.role == "planner":
            instruction = (
                "Plan the issue-to-PR workflow. Identify the issue, files to inspect or edit, validation "
                "commands, likely failure modes, and the next concrete action. Do not edit; produce a concise plan."
            )
        elif stage.role == "planner":
            instruction = (
                f"Plan the {kind} workflow. Identify files, risks, validation, and the next concrete action. "
                "Do not edit; produce a concise plan."
            )
        elif kind == "issue-pr" and stage.role == "coder":
            retry = " Address the blocking review feedback exactly once." if "retry" in stage.name else ""
            instruction = (
                "Execute the issue-to-PR workflow from the plan. Inspect and edit the needed files, keep changes "
                f"scoped, and report exactly which validation should run or was run.{retry}"
            )
        elif stage.role == "coder":
            retry = " Address the blocking review feedback exactly once." if "retry" in stage.name else ""
            instruction = (
                f"Execute the {kind} workflow from the plan. Keep changes scoped, preserve compatibility, "
                f"and report validation steps.{retry}"
            )
        elif stage.role == "explainer":
            instruction = "Explain the relevant code or behavior clearly and cite the reasoning path."
        elif stage.role == "validator":
            instruction = (
                f"Validate the {kind} workflow result. Check tests, changed files, risks, and whether the "
                "review feedback was resolved. Return pass/fail with evidence."
            )
        elif stage.role == "finalizer":
            instruction = (
                "Summarize the pull request. Include the issue addressed, important files changed, validation "
                "evidence, fallback or retry attempts, and unresolved risks. Do not invent tests or file changes."
            )
        else:
            instruction = (
                f"Review the {kind} workflow output for correctness, regressions, missing tests, and safety. "
                "Return blocking issues first, or say no blocking issues."
            )
        return "\n\n".join(part for part in [instruction, "Task:\n" + task, prior] if part)

    def stage_raw(self, request: HubRequest, workflow_id: str, kind: str, stage: WorkflowStage) -> dict[str, Any]:
        raw = dict(request.raw) if isinstance(request.raw, dict) else {}
        raw["workflow_id"] = workflow_id
        raw["workflow"] = kind
        raw["workflow_stage"] = stage.name
        raw["workflow_role"] = stage.role
        raw["prefer"] = stage.preference
        raw.setdefault("agent_hub", {})
        if isinstance(raw["agent_hub"], dict):
            raw["agent_hub"].update(
                {
                    "workflow_id": workflow_id,
                    "workflow": kind,
                    "workflow_stage": stage.name,
                    "workflow_role": stage.role,
                    "prefer": stage.preference,
                }
            )
        return raw

    def role_agent(self, role: str) -> str | None:
        fallback = "coder" if role == "explainer" else "reviewer" if role == "finalizer" else role
        for key in (role, fallback):
            configured = self.config.group_roles.get(key)
            if configured in self.config.agents and self.config.agents[configured].enabled:
                return configured
        return None

    def validation_requested(self, request: HubRequest) -> bool:
        raw = request.raw if isinstance(request.raw, dict) else {}
        value = raw.get("validate") or raw.get("validation")
        hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
        if value is None:
            value = hub.get("validate") or hub.get("validation")
        if value is None:
            return bool(self.config.validation_commands)
        return truthy(value)

    def retry_enabled(self, request: HubRequest) -> bool:
        raw = request.raw if isinstance(request.raw, dict) else {}
        value = raw.get("retry_on_review_failure")
        hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
        if value is None:
            value = hub.get("retry_on_review_failure", True)
        return truthy(value)

    def patch_summary_requested(self, request: HubRequest) -> bool:
        raw = request.raw if isinstance(request.raw, dict) else {}
        hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
        value = raw.get("patch_summary")
        if value is None:
            value = hub.get("patch_summary", False)
        return truthy(value)

    def final_summary_requested(self, kind: str, request: HubRequest) -> bool:
        if self.normalize(kind) == "issue-pr":
            return True
        raw = request.raw if isinstance(request.raw, dict) else {}
        hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
        value = raw.get("final_summary")
        if value is None:
            value = hub.get("final_summary", False)
        return truthy(value)

    def review_blocks(self, memory: Any) -> bool:
        return review_blocks(memory)

    def files_touched(self, memory: Any) -> list[str]:
        return files_touched(memory)


def review_blocks(memory: Any) -> bool:
    if not memory.stage_results:
        return False
    review_texts = [
        result.text.lower()
        for result in memory.stage_results
        if result.role == "reviewer"
    ]
    if not review_texts:
        return False
    latest = review_texts[-1]
    if "no blocking" in latest or "no blockers" in latest:
        return False
    return any(marker in latest for marker in ("blocking", "blocker", "must fix", "regression", "fail"))


def files_touched(memory: Any) -> list[str]:
    seen: set[str] = set()
    files: list[str] = []
    for result in memory.stage_results:
        for match in find_paths(result.text):
            if match not in seen:
                seen.add(match)
                files.append(match)
    return files[:80]


def find_paths(text: str) -> list[str]:
    return [
        match.group(0).strip("./").replace("\\", "/")
        for match in re.finditer(r"\b[\w./-]+\.(?:py|js|ts|tsx|jsx|json|md|toml|yml|yaml|css|html)\b", text)
    ]


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off", "disabled"}
    return bool(value)


def compact_text(text: str, *, maximum: int = 2400) -> str:
    clean = str(text or "").strip()
    if len(clean) <= maximum:
        return clean
    return clean[: maximum - 16].rstrip() + " [truncated]"


__all__ = [
    "WorkflowPlanner",
    "WorkflowStage",
    "compact_text",
    "files_touched",
    "find_paths",
    "review_blocks",
    "truthy",
]
