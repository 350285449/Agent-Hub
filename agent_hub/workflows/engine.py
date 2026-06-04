from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field, replace
from typing import Any

from ..config import HubConfig
from ..models import FailoverEvent, HubRequest, HubResponse
from ..payloads import request_text
from ..core.router import AgentRouter
from .events import WorkflowEventRecorder, WorkflowEventSink
from .planning import WorkflowPlanner, WorkflowStage, compact_text, truthy
from .workspace_service import SafeWorkspaceService


class WorkflowTimeoutError(TimeoutError):
    error_type = "workflow_stage_timeout"


class WorkflowCancelledError(RuntimeError):
    error_type = "workflow_cancelled"


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
            "text": compact_text(self.text),
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
            lines.append(f"{result.role}: {compact_text(result.text, maximum=1800)}")
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

    WORKFLOWS = WorkflowPlanner.WORKFLOWS

    def __init__(self, config: HubConfig, router: AgentRouter | None = None) -> None:
        self.config = config
        self.router = router or AgentRouter(config)
        self.planner = WorkflowPlanner(config)
        self.event_recorder = WorkflowEventRecorder(config.state_dir)
        self.workspace_service = SafeWorkspaceService(config)

    def execute(
        self,
        kind: str,
        request: HubRequest,
        *,
        event_sink: WorkflowEventSink | None = None,
        cancel_event: Any | None = None,
        stage_timeout_seconds: float | None = None,
        dry_run: bool | None = None,
    ) -> WorkflowResult:
        normalized = self.planner.normalize(kind)
        workflow_id = f"wf_{uuid.uuid4().hex}"
        task = request_text(request)
        state = WorkflowState()
        workflow_pattern = _workflow_pattern(request)
        timeout_seconds = _workflow_stage_timeout(request, stage_timeout_seconds)
        dry_run_enabled = _workflow_dry_run(request, dry_run)
        memory = WorkflowMemory(
            workflow_id=workflow_id,
            kind=normalized,
            task=task,
            context={
                **({"workflow_pattern": workflow_pattern} if workflow_pattern else {}),
                "dry_run": dry_run_enabled,
                "stage_timeout_seconds": timeout_seconds,
            },
            state=state,
        )
        stages = self.planner.stages_for_pattern(normalized, workflow_pattern)
        failover: list[FailoverEvent] = []
        final_response: HubResponse | None = None

        self.event_recorder.emit(
            event_sink,
            "workflow_started",
            workflow_id=workflow_id,
            workflow=normalized,
            workflow_pattern=workflow_pattern,
        )
        self._record_workflow_event(
            "workflow_started",
            workflow_id=workflow_id,
            workflow=normalized,
            workflow_pattern=workflow_pattern,
        )
        for index, stage in enumerate(stages, start=1):
            self._raise_if_cancelled(request, cancel_event, workflow_id, event_sink)
            final_response = self._run_model_stage_with_controls(
                normalized,
                stage,
                request,
                memory,
                workflow_id,
                index,
                len(stages),
                event_sink,
                failover,
                timeout_seconds=timeout_seconds,
            )

        if self.planner.review_blocks(memory) and self.planner.retry_enabled(request):
            state.retries += 1
            retry_stage = WorkflowStage("work_retry", "coder", "coding")
            self._raise_if_cancelled(request, cancel_event, workflow_id, event_sink)
            final_response = self._run_model_stage_with_controls(
                normalized,
                retry_stage,
                request,
                memory,
                workflow_id,
                len(memory.stage_results) + 1,
                len(stages) + 2,
                event_sink,
                failover,
                timeout_seconds=timeout_seconds,
            )
            self._raise_if_cancelled(request, cancel_event, workflow_id, event_sink)
            final_response = self._run_model_stage_with_controls(
                normalized,
                WorkflowStage("review_retry", "reviewer", "reliable"),
                request,
                memory,
                workflow_id,
                len(memory.stage_results) + 1,
                len(stages) + 2,
                event_sink,
                failover,
                timeout_seconds=timeout_seconds,
            )

        if self.config.allow_shell_tools and self.config.validation_commands:
            self._raise_if_cancelled(request, cancel_event, workflow_id, event_sink)
            self._run_validation_commands(memory, workflow_id, request, dry_run=dry_run_enabled)

        if self.planner.validation_requested(request):
            self._raise_if_cancelled(request, cancel_event, workflow_id, event_sink)
            final_response = self._run_model_stage_with_controls(
                normalized,
                WorkflowStage("validate", "validator", "reliable"),
                request,
                memory,
                workflow_id,
                len(memory.stage_results) + 1,
                len(memory.stage_results) + 1,
                event_sink,
                failover,
                timeout_seconds=timeout_seconds,
            )

        patch_summary_needed = self.planner.patch_summary_requested(request) or normalized == "issue-pr"
        if patch_summary_needed:
            self._add_patch_summary(memory)

        if self.planner.final_summary_requested(normalized, request):
            self._raise_if_cancelled(request, cancel_event, workflow_id, event_sink)
            final_response = self._run_model_stage_with_controls(
                normalized,
                WorkflowStage("final", "finalizer", "reliable"),
                request,
                memory,
                workflow_id,
                len(memory.stage_results) + 1,
                len(memory.stage_results) + 1,
                event_sink,
                failover,
                timeout_seconds=timeout_seconds,
            )

        assert final_response is not None
        state.files_touched = self.planner.files_touched(memory)
        if not state.validation_result:
            state.validation_result = {"ok": not self.planner.review_blocks(memory), "source": "review"}
        state.final_status = "blocked" if self.planner.review_blocks(memory) else "completed"
        raw = dict(final_response.raw)
        metadata = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
        raw["agent_hub"] = {
            **metadata,
            "workflow": memory.to_dict(),
            "workflow_pattern": workflow_pattern,
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
            related_questions=final_response.related_questions,
        )
        if request.record_session:
            self.router.session_store.record_turn(request, response)
        self.event_recorder.emit(event_sink, "workflow_finished", workflow_id=workflow_id, workflow=normalized)
        self._record_workflow_event(
            "workflow_finished",
            workflow_id=workflow_id,
            workflow=normalized,
            workflow_pattern=workflow_pattern,
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
        self.event_recorder.emit(
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
                messages=[{"role": "user", "content": self.planner.stage_prompt(normalized, stage, request, memory)}],
                route="coding" if stage.role in {"coder", "reviewer", "validator", "finalizer"} else request.route,
                preferred_agent=self.planner.role_agent(stage.role),
                stream=False,
                use_session_history=False,
                record_session=False,
                raw=self.planner.stage_raw(request, workflow_id, normalized, stage),
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
        self.event_recorder.emit(
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

    def _run_model_stage_with_controls(
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
        *,
        timeout_seconds: float | None,
    ) -> HubResponse:
        if timeout_seconds is None or timeout_seconds <= 0:
            return self._run_model_stage(
                normalized,
                stage,
                request,
                memory,
                workflow_id,
                index,
                total,
                event_sink,
                failover,
            )
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-hub-workflow-stage")
        future = executor.submit(
            self._run_model_stage,
            normalized,
            stage,
            request,
            memory,
            workflow_id,
            index,
            total,
            event_sink,
            failover,
        )
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            self.event_recorder.emit(
                event_sink,
                "workflow_stage_timeout",
                workflow_id=workflow_id,
                stage=stage.name,
                role=stage.role,
                timeout_seconds=timeout_seconds,
            )
            self._record_workflow_event(
                "workflow_stage_timeout",
                workflow_id=workflow_id,
                workflow=normalized,
                stage=stage.name,
                role=stage.role,
                timeout_seconds=timeout_seconds,
            )
            raise WorkflowTimeoutError(
                f"Workflow stage {stage.name!r} timed out after {timeout_seconds:.2f}s"
            ) from exc
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

    def _raise_if_cancelled(
        self,
        request: HubRequest,
        cancel_event: Any | None,
        workflow_id: str,
        event_sink: WorkflowEventSink | None,
    ) -> None:
        cancelled = _workflow_cancelled(request)
        if cancel_event is not None:
            is_set = getattr(cancel_event, "is_set", None)
            cancelled = cancelled or (bool(is_set()) if callable(is_set) else bool(cancel_event))
        if not cancelled:
            return
        self.event_recorder.emit(event_sink, "workflow_cancelled", workflow_id=workflow_id)
        self._record_workflow_event("workflow_cancelled", workflow_id=workflow_id)
        raise WorkflowCancelledError(f"Workflow {workflow_id} was cancelled.")

    def _record_workflow_event(self, event_type: str, **data: Any) -> None:
        self.event_recorder.record(event_type, **data)

    def _run_validation_commands(
        self,
        memory: WorkflowMemory,
        workflow_id: str,
        request: HubRequest,
        *,
        dry_run: bool = False,
    ) -> None:
        state = memory.state or WorkflowState()
        command_results: list[dict[str, Any]] = []
        started = time.time()
        for command in self.config.validation_commands[:5]:
            result = self.workspace_service.run_shell_command(
                request,
                command,
                timeout_seconds=120,
                dry_run=dry_run,
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
                text=compact_text(str(state.validation_result), maximum=2400),
                started_at=started,
                finished_at=finished,
            )
        )

    def _add_patch_summary(self, memory: WorkflowMemory) -> None:
        state = memory.state or WorkflowState()
        started = time.time()
        files = self.planner.files_touched(memory)
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


def _workflow_pattern(request: HubRequest) -> str:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    for value in (hub.get("workflow_pattern"), raw.get("workflow_pattern")):
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _workflow_stage_timeout(request: HubRequest, explicit: float | None) -> float | None:
    if explicit is not None:
        return max(0.0, float(explicit))
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    for value in (
        hub.get("workflow_stage_timeout_seconds"),
        hub.get("stage_timeout_seconds"),
        raw.get("workflow_stage_timeout_seconds"),
        raw.get("stage_timeout_seconds"),
    ):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        return max(0.0, parsed)
    return None


def _workflow_dry_run(request: HubRequest, explicit: bool | None) -> bool:
    if explicit is not None:
        return bool(explicit)
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    return truthy(hub.get("dry_run")) or truthy(raw.get("dry_run"))


def _workflow_cancelled(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    return truthy(hub.get("workflow_cancelled")) or truthy(raw.get("workflow_cancelled"))
