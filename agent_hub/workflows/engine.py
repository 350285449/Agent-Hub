from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from ..config import HubConfig
from ..models import FailoverEvent, HubRequest, HubResponse
from ..observability import record_event
from ..payloads import request_text
from ..core.router import AgentRouter
from ..tools import ToolCall, ToolExecutionContext, ToolExecutionPipeline, create_builtin_registry


WorkflowEventSink = Callable[[dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class WorkflowStage:
    name: str
    role: str
    preference: str


@dataclass(slots=True)
class WorkflowStageResult:
    stage: str
    role: str
    agent: str
    provider: str
    model: str
    text: str
    started_at: float
    finished_at: float
    failover: list[FailoverEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "role": self.role,
            "agent": self.agent,
            "provider": self.provider,
            "model": self.model,
            "text": _compact(self.text),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round((self.finished_at - self.started_at) * 1000, 2),
            "failover": [event.to_dict() for event in self.failover],
        }


@dataclass(slots=True)
class WorkflowMemory:
    workflow_id: str
    kind: str
    task: str
    stage_results: list[WorkflowStageResult] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    state: "WorkflowState | None" = None

    def add(self, result: WorkflowStageResult) -> None:
        self.stage_results.append(result)

    def prompt_context(self) -> str:
        if not self.stage_results:
            return ""
        lines = ["Prior workflow stages:"]
        for result in self.stage_results:
            lines.append(f"{result.role}: {_compact(result.text, maximum=1800)}")
        return "\n\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "kind": self.kind,
            "task": self.task,
            "context": self.context,
            "stages": [result.to_dict() for result in self.stage_results],
            "state": self.state.to_dict() if self.state else {},
        }


@dataclass(slots=True)
class WorkflowState:
    stages: list[str] = field(default_factory=list)
    retries: int = 0
    files_touched: list[str] = field(default_factory=list)
    validation_result: dict[str, Any] = field(default_factory=dict)
    final_status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages": list(self.stages),
            "retries": self.retries,
            "files_touched": list(self.files_touched),
            "validation_result": dict(self.validation_result),
            "final_status": self.final_status,
        }


@dataclass(slots=True)
class WorkflowResult:
    response: HubResponse
    memory: WorkflowMemory

    def to_dict(self, *, include_routing_details: bool = False) -> dict[str, Any]:
        data = self.response.to_native_dict(include_routing_details=include_routing_details)
        data["workflow"] = self.memory.to_dict()
        return data


class WorkflowEngine:
    """Deterministic, non-recursive planner/worker/reviewer orchestration."""

    WORKFLOWS = {"code", "review", "debug", "explain", "refactor"}

    def __init__(self, config: HubConfig, router: AgentRouter | None = None) -> None:
        self.config = config
        self.router = router or AgentRouter(config)

    def execute(
        self,
        kind: str,
        request: HubRequest,
        *,
        event_sink: WorkflowEventSink | None = None,
    ) -> WorkflowResult:
        normalized = kind.strip().lower()
        if normalized not in self.WORKFLOWS:
            raise ValueError(f"Unknown workflow {kind!r}")

        workflow_id = f"wf_{uuid.uuid4().hex}"
        task = request_text(request)
        state = WorkflowState()
        memory = WorkflowMemory(workflow_id=workflow_id, kind=normalized, task=task, state=state)
        stages = _workflow_stages(normalized)
        failover: list[FailoverEvent] = []
        final_response: HubResponse | None = None

        _emit(event_sink, "workflow_started", workflow_id=workflow_id, workflow=normalized)
        self._record_workflow_event("workflow_started", workflow_id=workflow_id, workflow=normalized)
        for index, stage in enumerate(stages, start=1):
            final_response = self._run_model_stage(
                normalized,
                stage,
                request,
                memory,
                workflow_id,
                index,
                len(stages),
                event_sink,
                failover,
            )

        if _review_blocks(memory) and _retry_enabled(request):
            state.retries += 1
            retry_stage = WorkflowStage("work_retry", "coder", "coding")
            final_response = self._run_model_stage(
                normalized,
                retry_stage,
                request,
                memory,
                workflow_id,
                len(memory.stage_results) + 1,
                len(stages) + 2,
                event_sink,
                failover,
            )
            final_response = self._run_model_stage(
                normalized,
                WorkflowStage("review_retry", "reviewer", "reliable"),
                request,
                memory,
                workflow_id,
                len(memory.stage_results) + 1,
                len(stages) + 2,
                event_sink,
                failover,
            )

        if self.config.allow_shell_tools and self.config.validation_commands:
            self._run_validation_commands(memory, workflow_id)

        if _validation_requested(request, self.config):
            final_response = self._run_model_stage(
                normalized,
                WorkflowStage("validate", "validator", "reliable"),
                request,
                memory,
                workflow_id,
                len(memory.stage_results) + 1,
                len(memory.stage_results) + 1,
                event_sink,
                failover,
            )

        if _patch_summary_requested(request):
            self._add_patch_summary(memory)

        assert final_response is not None
        state.files_touched = _files_touched(memory)
        if not state.validation_result:
            state.validation_result = {"ok": not _review_blocks(memory), "source": "review"}
        state.final_status = "blocked" if _review_blocks(memory) else "completed"
        raw = dict(final_response.raw)
        metadata = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
        raw["agent_hub"] = {
            **metadata,
            "workflow": memory.to_dict(),
            "workflow_stages": [stage.to_dict() for stage in memory.stage_results],
        }
        response = HubResponse(
            request_id=final_response.request_id,
            session_id=request.session_id,
            agent=final_response.agent,
            provider=final_response.provider,
            model=final_response.model,
            public_model=final_response.public_model,
            text=final_response.text,
            usage=final_response.usage,
            raw=raw,
            finish_reason=final_response.finish_reason,
            failover=failover,
            citations=final_response.citations,
            search_results=final_response.search_results,
            images=final_response.images,
            related_questions=final_response.related_questions,
        )
        if request.record_session:
            self.router.session_store.record_turn(request, response)
        _emit(event_sink, "workflow_finished", workflow_id=workflow_id, workflow=normalized)
        self._record_workflow_event(
            "workflow_finished",
            workflow_id=workflow_id,
            workflow=normalized,
            final_status=state.final_status,
            stage_count=len(memory.stage_results),
        )
        return WorkflowResult(response=response, memory=memory)

    def _run_model_stage(
        self,
        normalized: str,
        stage: WorkflowStage,
        request: HubRequest,
        memory: WorkflowMemory,
        workflow_id: str,
        index: int,
        total: int,
        event_sink: WorkflowEventSink | None,
        failover: list[FailoverEvent],
    ) -> HubResponse:
        state = memory.state or WorkflowState()
        started = time.time()
        state.stages.append(stage.name)
        _emit(
            event_sink,
            "workflow_stage_started",
            workflow_id=workflow_id,
            stage=stage.name,
            role=stage.role,
            index=index,
            total=total,
        )
        self._record_workflow_event(
            "workflow_stage_started",
            workflow_id=workflow_id,
            workflow=normalized,
            stage=stage.name,
            role=stage.role,
            index=index,
            total=total,
        )
        response = self.router.route(
            replace(
                request,
                messages=[{"role": "user", "content": _stage_prompt(normalized, stage, request, memory)}],
                route="coding" if stage.role in {"coder", "reviewer", "validator"} else request.route,
                preferred_agent=_role_agent(self.config, stage.role),
                stream=False,
                use_session_history=False,
                record_session=False,
                raw=_stage_raw(request, workflow_id, normalized, stage),
            )
        )
        finished = time.time()
        failover.extend(response.failover)
        memory.add(
            WorkflowStageResult(
                stage=stage.name,
                role=stage.role,
                agent=response.agent,
                provider=response.provider,
                model=response.model,
                text=response.text,
                started_at=started,
                finished_at=finished,
                failover=list(response.failover),
            )
        )
        _emit(
            event_sink,
            "workflow_stage_finished",
            workflow_id=workflow_id,
            stage=stage.name,
            role=stage.role,
            agent=response.agent,
            model=response.model,
        )
        self._record_workflow_event(
            "workflow_stage_finished",
            workflow_id=workflow_id,
            workflow=normalized,
            stage=stage.name,
            role=stage.role,
            agent=response.agent,
            provider=response.provider,
            model=response.model,
            duration_ms=round((finished - started) * 1000, 2),
        )
        return response

    def _record_workflow_event(self, event_type: str, **data: Any) -> None:
        try:
            record_event(self.config.state_dir, "workflows", {"type": event_type, **data})
        except Exception:
            return

    def _run_validation_commands(self, memory: WorkflowMemory, workflow_id: str) -> None:
        state = memory.state or WorkflowState()
        registry = create_builtin_registry(self.config)
        pipeline = ToolExecutionPipeline(registry)
        context = ToolExecutionContext(config=self.config)
        command_results: list[dict[str, Any]] = []
        started = time.time()
        for command in self.config.validation_commands[:5]:
            result = pipeline.execute(
                ToolCall(name="shell_execute", arguments={"command": command}),
                context,
            )
            command_results.append(result.to_dict())
        finished = time.time()
        ok = all(item.get("ok") for item in command_results)
        state.validation_result = {"ok": ok, "commands": command_results, "source": "shell"}
        memory.add(
            WorkflowStageResult(
                stage="test",
                role="validator",
                agent="local-tool",
                provider="agent-hub",
                model="shell_execute",
                text=_compact(str(state.validation_result), maximum=2400),
                started_at=started,
                finished_at=finished,
            )
        )

    def _add_patch_summary(self, memory: WorkflowMemory) -> None:
        state = memory.state or WorkflowState()
        started = time.time()
        files = _files_touched(memory)
        state.files_touched = files
        summary = "Patch summary:\n" + ("\n".join(f"- {path}" for path in files) if files else "No concrete files were reported.")
        memory.add(
            WorkflowStageResult(
                stage="patch_summary",
                role="summarizer",
                agent="local-summary",
                provider="agent-hub",
                model="workflow-state",
                text=summary,
                started_at=started,
                finished_at=time.time(),
            )
        )


def _workflow_stages(kind: str) -> list[WorkflowStage]:
    worker_role = {
        "code": "coder",
        "review": "reviewer",
        "debug": "coder",
        "explain": "explainer",
        "refactor": "coder",
    }[kind]
    return [
        WorkflowStage("plan", "planner", "reasoning"),
        WorkflowStage("work", worker_role, "coding" if worker_role == "coder" else "reliable"),
        WorkflowStage("review", "reviewer", "reliable"),
    ]


def _stage_prompt(
    kind: str,
    stage: WorkflowStage,
    request: HubRequest,
    memory: WorkflowMemory,
) -> str:
    task = request_text(request)
    prior = memory.prompt_context()
    if stage.role == "planner":
        instruction = (
            f"Plan the {kind} workflow. Identify files, risks, validation, and the next concrete action. "
            "Do not edit; produce a concise plan."
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
    else:
        instruction = (
            f"Review the {kind} workflow output for correctness, regressions, missing tests, and safety. "
            "Return blocking issues first, or say no blocking issues."
        )
    return "\n\n".join(part for part in [instruction, "Task:\n" + task, prior] if part)


def _stage_raw(
    request: HubRequest,
    workflow_id: str,
    kind: str,
    stage: WorkflowStage,
) -> dict[str, Any]:
    raw = dict(request.raw or {})
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


def _role_agent(config: HubConfig, role: str) -> str | None:
    for key in (role, "coder" if role == "explainer" else role):
        configured = config.group_roles.get(key)
        if configured in config.agents and config.agents[configured].enabled:
            return configured
    return None


def _emit(event_sink: WorkflowEventSink | None, event_type: str, **data: Any) -> None:
    if event_sink is None:
        return
    try:
        event_sink({"type": event_type, **data})
    except Exception:
        return


def _validation_requested(request: HubRequest, config: HubConfig) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    value = raw.get("validate") or raw.get("validation")
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    if value is None:
        value = hub.get("validate") or hub.get("validation")
    if value is None:
        return bool(config.validation_commands)
    return _truthy(value)


def _retry_enabled(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    value = raw.get("retry_on_review_failure")
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    if value is None:
        value = hub.get("retry_on_review_failure", True)
    return _truthy(value)


def _patch_summary_requested(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    value = raw.get("patch_summary")
    if value is None:
        value = hub.get("patch_summary", False)
    return _truthy(value)


def _review_blocks(memory: WorkflowMemory) -> bool:
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


def _files_touched(memory: WorkflowMemory) -> list[str]:
    seen: set[str] = set()
    files: list[str] = []
    for result in memory.stage_results:
        for match in re_find_paths(result.text):
            if match not in seen:
                seen.add(match)
                files.append(match)
    return files[:80]


def re_find_paths(text: str) -> list[str]:
    import re

    return [
        match.group(0).strip("./").replace("\\", "/")
        for match in re.finditer(r"\b[\w./-]+\.(?:py|js|ts|tsx|jsx|json|md|toml|yml|yaml|css|html)\b", text)
    ]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off", "disabled"}
    return bool(value)


def _compact(text: str, *, maximum: int = 2400) -> str:
    clean = str(text or "").strip()
    if len(clean) <= maximum:
        return clean
    return clean[: maximum - 16].rstrip() + " [truncated]"
