from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from ..config import HubConfig
from ..models import FailoverEvent, HubRequest, HubResponse
from ..payloads import request_text
from ..core.router import AgentRouter


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
        memory = WorkflowMemory(workflow_id=workflow_id, kind=normalized, task=task)
        stages = _workflow_stages(normalized)
        failover: list[FailoverEvent] = []
        final_response: HubResponse | None = None

        _emit(event_sink, "workflow_started", workflow_id=workflow_id, workflow=normalized)
        for index, stage in enumerate(stages, start=1):
            started = time.time()
            _emit(
                event_sink,
                "workflow_stage_started",
                workflow_id=workflow_id,
                stage=stage.name,
                role=stage.role,
                index=index,
                total=len(stages),
            )
            response = self.router.route(
                replace(
                    request,
                    messages=[{"role": "user", "content": _stage_prompt(normalized, stage, request, memory)}],
                    route="coding" if stage.role in {"coder", "reviewer"} else request.route,
                    preferred_agent=_role_agent(self.config, stage.role),
                    stream=False,
                    use_session_history=False,
                    record_session=False,
                    raw=_stage_raw(request, workflow_id, normalized, stage),
                )
            )
            finished = time.time()
            failover.extend(response.failover)
            stage_result = WorkflowStageResult(
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
            memory.add(stage_result)
            final_response = response
            _emit(
                event_sink,
                "workflow_stage_finished",
                workflow_id=workflow_id,
                stage=stage.name,
                role=stage.role,
                agent=response.agent,
                model=response.model,
            )

        assert final_response is not None
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
        return WorkflowResult(response=response, memory=memory)


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
        instruction = (
            f"Execute the {kind} workflow from the plan. Keep changes scoped, preserve compatibility, "
            "and report validation steps."
        )
    elif stage.role == "explainer":
        instruction = "Explain the relevant code or behavior clearly and cite the reasoning path."
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


def _compact(text: str, *, maximum: int = 2400) -> str:
    clean = str(text or "").strip()
    if len(clean) <= maximum:
        return clean
    return clean[: maximum - 16].rstrip() + " [truncated]"
