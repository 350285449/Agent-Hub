from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from .agent_tools import (
    AgentToolbox,
    ShellPermissionCallback,
    agent_tool_definitions,
    restore_workspace_checkpoint,
    tool_result_message,
)
from .config import HubConfig
from .models import FailoverEvent, HubRequest, HubResponse
from .reasoning import WorkspaceReasoningState, reasoning_state_message
from .router import AgentRouter


TOOL_ACTIONS = {
    "list_files",
    "read_file",
    "search_files",
    "repo_map",
    "write_file",
    "replace_in_file",
    "apply_patch",
    "run_command",
}
EDIT_TOOLS = {"write_file", "replace_in_file", "apply_patch"}

REQUIRED_TOOL_ARGS = {
    "read_file": ("path",),
    "search_files": ("query",),
    "write_file": ("path", "content"),
    "replace_in_file": ("path", "old", "new"),
    "run_command": ("command",),
}
NON_EMPTY_TOOL_ARGS = {
    "read_file": ("path",),
    "search_files": ("query",),
    "write_file": ("path",),
    "replace_in_file": ("path", "old"),
    "run_command": ("command",),
}

AgentEventSink = Callable[[dict[str, Any]], None]


class AgentRunner:
    def __init__(self, config: HubConfig, router: AgentRouter | None = None) -> None:
        self.config = config
        self.router = router or AgentRouter(config)

    def run(
        self,
        request: HubRequest,
        event_sink: AgentEventSink | None = None,
        shell_permission_callback: ShellPermissionCallback | None = None,
    ) -> HubResponse:
        toolbox = AgentToolbox(
            self.config,
            request,
            shell_permission_callback=shell_permission_callback,
        )
        session_data = self.router.session_store.load(request.session_id)
        reasoning_state = WorkspaceReasoningState.for_request(request, session_data=session_data)
        reasoning_state.add_active_files(_active_files_from_toolbox(toolbox))
        messages = self._initial_messages(
            request,
            toolbox,
            reasoning_state=reasoning_state,
            session_data=session_data,
        )
        max_steps = _request_int(request, "agent_max_steps", self.config.agent_max_steps)
        trace: list[dict[str, Any]] = []
        failover: list[FailoverEvent] = []
        last_response: HubResponse | None = None
        max_invalid_responses = _request_int(request, "agent_max_invalid_responses", 2)
        consecutive_invalid_responses = 0
        repair_attempts_current = _request_nonnegative_int(
            request,
            "validation_repair_attempts_current",
            0,
        )
        repair_attempts_max = _request_nonnegative_int(
            request,
            "validation_repair_attempts_max",
            self.config.validation_repair_attempts,
        )

        _emit(
            event_sink,
            "agent_started",
            message=f"Started workspace agent with up to {max_steps} steps.",
            max_steps=max_steps,
            workspace=str(toolbox.root),
            allow_shell_tools=toolbox.allow_shell,
        )

        for step_number in range(1, max_steps + 1):
            _emit(
                event_sink,
                "model_request",
                message=f"Step {step_number}: planning the next workspace action.",
                step=step_number,
            )
            step_request = replace(
                request,
                messages=messages,
                stream=False,
                use_session_history=False,
                record_session=False,
                raw=_agent_step_raw(
                    request,
                    toolbox,
                    trace=trace,
                    repair_attempts_current=repair_attempts_current,
                    repair_attempts_max=repair_attempts_max,
                    reasoning_state=reasoning_state,
                ),
            )
            response = self.router.route(step_request)
            last_response = response
            failover.extend(response.failover)

            if response.provider == "echo":
                stopped = bool(trace or failover)
                _emit(
                    event_sink,
                    "agent_stopped",
                    message="Agent reached the echo fallback and stopped.",
                    step=step_number,
                    agent=response.agent,
                    provider=response.provider,
                    model=response.model,
                )
                final = self._with_agent_metadata(
                    response,
                    request=request,
                    text=_echo_fallback_text(response, failover=failover, trace=trace)
                    if stopped
                    else response.text,
                    trace=trace,
                    failover=failover,
                    stopped=stopped,
                    reasoning_state=reasoning_state,
                )
                self._record_final(request, final)
                return final

            command = _command_from_response(response)
            _emit(
                event_sink,
                "model_response",
                message=_model_response_message(step_number, response, command),
                step=step_number,
                agent=response.agent,
                provider=response.provider,
                model=response.model,
                action=command.get("action"),
                tool=command.get("tool"),
            )
            if command["action"] == "tool":
                consecutive_invalid_responses = 0
                tool_name = str(command["tool"])
                args = command.get("args") if isinstance(command.get("args"), dict) else {}
                _emit(
                    event_sink,
                    "tool_started",
                    message=_tool_started_message(step_number, tool_name, args),
                    step=step_number,
                    tool=tool_name,
                    args=_progress_tool_args(tool_name, args),
                )
                result = _edit_policy_feedback(
                    toolbox,
                    tool_name,
                    args,
                    request,
                    trace,
                    messages,
                ) or toolbox.run(tool_name, args)
                if result.get("edit_policy_feedback"):
                    reasoning_state.record_tool_result(tool_name, args, result)
                    self.router.record_tool_result(response.agent, False)
                    trace.append(
                        {
                            "step": step_number,
                            "agent": response.agent,
                            "provider": response.provider,
                            "model": response.model,
                            "tool": tool_name,
                            "args": args,
                            "result": result,
                        }
                    )
                    _emit(
                        event_sink,
                        "edit_policy_feedback",
                        message=result.get("message", "Edit policy requested a different tool."),
                        step=step_number,
                        tool=tool_name,
                        recommended_tool=result.get("recommended_tool", "apply_patch"),
                        affected_files=result.get("affected_files", []),
                        reason=result.get("error", ""),
                    )
                    _emit_reasoning_state_updated(event_sink, reasoning_state)
                    _emit(
                        event_sink,
                        "tool_finished",
                        message=_tool_finished_message(step_number, tool_name, result),
                        step=step_number,
                        tool=tool_name,
                        ok=False,
                        result=_progress_tool_result(tool_name, result),
                    )
                    messages.append({"role": "assistant", "content": response.text})
                    messages.append(tool_result_message(tool_name, result))
                    continue
                if result.get("approval_required"):
                    _enrich_approval_with_execution(result, reasoning_state)
                    reasoning_state.record_tool_result(tool_name, args, result)
                    reasoning_state.record_approval(
                        {
                            "tool": tool_name,
                            "affected_files": result.get("affected_files", []),
                            "summary": result.get("summary", ""),
                            "risk_level": result.get("risk_level", ""),
                            "impact": result.get("impact", ""),
                            "execution_node": result.get("execution_node"),
                            "execution_objective": result.get("execution_objective", ""),
                        }
                    )
                    if result.get("patch_preview"):
                        _emit(
                            event_sink,
                            "patch_preview",
                            message="Patch preview is ready for approval.",
                            tool=tool_name,
                            affected_files=result.get("affected_files", []),
                            summary=result.get("summary", ""),
                            impact=result.get("impact", ""),
                            risk_level=result.get("risk_level", ""),
                            execution_objective=result.get("execution_objective", ""),
                            execution_node=result.get("execution_node"),
                            dependency_impact=result.get("dependency_impact", {}),
                            rollback_safety=result.get("rollback_safety", ""),
                            file_groups=result.get("file_groups", []),
                            patch_preview=result.get("patch_preview", ""),
                            commands=result.get("commands", []),
                            validation_plan=result.get("validation_plan", ""),
                        )
                    # Record this in trace
                    trace.append({
                        "step": step_number,
                        "agent": response.agent,
                        "provider": response.provider,
                        "model": response.model,
                        "tool": tool_name,
                        "args": args,
                        "result": result,
                    })
                    _emit(
                        event_sink,
                        "approval_required",
                        tool=tool_name,
                        args=args,
                        affected_files=result.get("affected_files", []),
                        summary=result.get("summary", ""),
                        patch_preview=result.get("patch_preview", ""),
                        commands=result.get("commands", []),
                        validation_plan=result.get("validation_plan", ""),
                        risk=result.get("risk", ""),
                        risk_level=result.get("risk_level", ""),
                        impact=result.get("impact", ""),
                        estimated_impact=result.get("estimated_impact", {}),
                        file_groups=result.get("file_groups", []),
                        execution_objective=result.get("execution_objective", ""),
                        execution_node=result.get("execution_node"),
                        affected_execution_nodes=result.get("affected_execution_nodes", []),
                        dependency_impact=result.get("dependency_impact", {}),
                        repository_impact=result.get("repository_impact", {}),
                        rollback_safety=result.get("rollback_safety", ""),
                        message=result.get("message", "Approval required before applying changes."),
                    )
                    final = self._with_agent_metadata(
                        response,
                        request=request,
                        text=result.get("message", "Approval required before applying changes."),
                        trace=trace,
                        failover=failover,
                        stopped=True,
                        reasoning_state=reasoning_state,
                    )
                    self._record_final(request, final)
                    return final

                if result.get("approval_granted"):
                    _emit(
                        event_sink,
                        "approval_granted",
                        message="Approval granted; applying workspace changes.",
                        tool=tool_name,
                        affected_files=_changed_files_from_result(tool_name, result),
                    )

                changed_files = _changed_files_from_result(tool_name, result)
                if changed_files:
                    if tool_name == "apply_patch":
                        _emit(
                            event_sink,
                            "multi_file_edit_applied",
                            message=f"Applied patch to {len(changed_files)} file(s).",
                            step=step_number,
                            tool=tool_name,
                            affected_files=changed_files,
                        )
                    validation = _validate_after_edit(
                        request,
                        self.config,
                        toolbox.root,
                        changed_files,
                        event_sink,
                    )
                    if validation is not None:
                        _annotate_validation_with_execution(validation, reasoning_state)
                        result["validation"] = validation
                        rollback = _restore_after_failed_validation(
                            request,
                            self.config,
                            toolbox.root,
                            result,
                            event_sink,
                        )
                        if rollback is not None:
                            result["rollback"] = rollback

                repair_decision = _repair_decision_for_result(
                    tool_name,
                    result,
                    repair_attempts_current,
                    repair_attempts_max,
                    reasoning_state=reasoning_state,
                )
                if repair_decision.get("message"):
                    repair_attempts_current += 1
                    result["repair"] = {
                        "kind": repair_decision["kind"],
                        "attempt": repair_attempts_current,
                        "max_attempts": repair_attempts_max,
                    }

                reasoning_state.record_tool_result(tool_name, args, result)
                self.router.record_tool_result(response.agent, result.get("ok") is not False)
                trace.append(
                    {
                        "step": step_number,
                        "agent": response.agent,
                        "provider": response.provider,
                        "model": response.model,
                        "tool": tool_name,
                        "args": args,
                        "result": result,
                    }
                )
                _emit(
                    event_sink,
                    "tool_finished",
                    message=_tool_finished_message(step_number, tool_name, result),
                    step=step_number,
                    tool=tool_name,
                    ok=result.get("ok") is not False,
                    result=_progress_tool_result(tool_name, result),
                )
                edit_event = _workspace_edit_event(step_number, tool_name, result)
                if edit_event:
                    _emit(event_sink, "workspace_edit", **edit_event)
                _emit_reasoning_state_updated(event_sink, reasoning_state)

                repair_message = str(repair_decision.get("message") or "")
                if repair_message:
                    event_type = (
                        "validation_repair_loop"
                        if repair_decision.get("kind") == "validation_failure"
                        else "edit_repair_loop"
                    )
                    _emit(
                        event_sink,
                        event_type,
                        message=repair_decision.get(
                            "event_message",
                            "Edit failed; feeding back to agent for repair attempt.",
                        ),
                        step=step_number,
                        tool=tool_name,
                        attempt=repair_attempts_current,
                        max_attempts=repair_attempts_max,
                    )
                    messages.append({"role": "assistant", "content": response.text})
                    messages.append(tool_result_message(tool_name, result))
                    messages.append({"role": "user", "content": repair_message})
                    continue

                if repair_decision.get("exhausted"):
                    _emit(
                        event_sink,
                        "agent_stopped",
                        message=repair_decision.get(
                            "event_message",
                            "Agent stopped after edit repair attempts were exhausted.",
                        ),
                        step=step_number,
                        tool=tool_name,
                        max_attempts=repair_attempts_max,
                    )
                    final = self._with_agent_metadata(
                        response,
                        request=request,
                        text=_repair_exhausted_text(tool_name, result, repair_attempts_max),
                        trace=trace,
                        failover=failover,
                        stopped=True,
                        reasoning_state=reasoning_state,
                    )
                    self._record_final(request, final)
                    return final

                fast_final_text = _fast_tool_final_text(tool_name, result, request, self.config)
                if fast_final_text:
                    _emit(
                        event_sink,
                        "agent_final",
                        message="Agent completed after the local file edit.",
                        step=step_number,
                    )
                    final = self._with_agent_metadata(
                        response,
                        request=request,
                        text=fast_final_text,
                        trace=trace,
                        failover=failover,
                        stopped=False,
                        reasoning_state=reasoning_state,
                    )
                    self._record_final(request, final)
                    return final
                messages.append({"role": "assistant", "content": response.text})
                messages.append(tool_result_message(tool_name, result))
                continue

            if command["action"] == "final":
                consecutive_invalid_responses = 0
                _emit(
                    event_sink,
                    "agent_final",
                    message="Agent produced a final answer.",
                    step=step_number,
                )
                final = self._with_agent_metadata(
                    response,
                    request=request,
                    text=str(command["answer"]),
                    trace=trace,
                    failover=failover,
                    stopped=False,
                    reasoning_state=reasoning_state,
                )
                self._record_final(request, final)
                return final

            if command["action"] == "invalid":
                consecutive_invalid_responses += 1
                reason = str(command.get("reason") or "response did not match the Agent Hub protocol")
                failover.append(
                    FailoverEvent(
                        agent=response.agent,
                        provider=response.provider,
                        model=response.model,
                        reason=f"Invalid agent message: {reason}",
                    )
                )
                self.router.cooldown_agent(response.agent)
                _emit(
                    event_sink,
                    "invalid_response",
                    message=(
                        f"Step {step_number}: model response did not match the agent protocol; "
                        "retrying with another agent when available."
                    ),
                    step=step_number,
                    reason=reason,
                    agent=response.agent,
                    provider=response.provider,
                    model=response.model,
                )
                if consecutive_invalid_responses >= max_invalid_responses:
                    text = (
                        "Agent stopped because repeated model responses did not match "
                        "the Agent Hub protocol.\n\n"
                        f"Last invalid response from {response.agent}: {reason}"
                    )
                    _emit(
                        event_sink,
                        "agent_stopped",
                        message="Agent stopped after repeated invalid model responses.",
                        step=step_number,
                        agent=response.agent,
                        provider=response.provider,
                        model=response.model,
                    )
                    final = self._with_agent_metadata(
                        response,
                        request=request,
                        text=text,
                        trace=trace,
                        failover=failover,
                        stopped=True,
                        reasoning_state=reasoning_state,
                    )
                    self._record_final(request, final)
                    return final
                messages.append({"role": "assistant", "content": response.text})
                messages.append(_invalid_response_message(command))
                continue

            consecutive_invalid_responses = 0
            _emit(
                event_sink,
                "agent_final",
                message="Agent returned a direct response.",
                step=step_number,
            )
            final = self._with_agent_metadata(
                response,
                request=request,
                text=response.text,
                trace=trace,
                failover=failover,
                stopped=False,
                reasoning_state=reasoning_state,
            )
            self._record_final(request, final)
            return final

        text = "Agent stopped before producing a final answer."
        if last_response and last_response.text:
            text = f"{text}\n\nLast model message:\n{last_response.text}"
        _emit(
            event_sink,
            "agent_stopped",
            message="Agent stopped before producing a final answer.",
            max_steps=max_steps,
        )
        final = self._with_agent_metadata(
            last_response,
            request=request,
            text=text,
            trace=trace,
            failover=failover,
            stopped=True,
            reasoning_state=reasoning_state,
        )
        self._record_final(request, final)
        return final

    def _initial_messages(
        self,
        request: HubRequest,
        toolbox: AgentToolbox,
        *,
        reasoning_state: WorkspaceReasoningState,
        session_data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        request_with_history = self._with_session_history(request, session_data=session_data)
        return [
            {"role": "system", "content": f"{toolbox.instructions()}\n\n{reasoning_state_message(reasoning_state)}"},
            *request_with_history.messages,
        ]

    def _with_session_history(
        self,
        request: HubRequest,
        *,
        session_data: dict[str, Any] | None = None,
    ) -> HubRequest:
        if not request.use_session_history:
            return request
        data = session_data if session_data is not None else self.router.session_store.load(request.session_id)
        history = data.get("messages", [])
        if not history:
            return request
        if _is_prefix(history, request.messages):
            return request
        if _is_prefix(request.messages, history):
            return replace(request, messages=list(history))
        return replace(request, messages=[*history, *request.messages])

    def _with_agent_metadata(
        self,
        response: HubResponse | None,
        *,
        request: HubRequest,
        text: str,
        trace: list[dict[str, Any]],
        failover: list[FailoverEvent],
        stopped: bool,
        reasoning_state: WorkspaceReasoningState | None = None,
    ) -> HubResponse:
        raw = dict(response.raw) if response else {}
        existing_metadata = raw.get("agent_hub")
        base_metadata = existing_metadata if isinstance(existing_metadata, dict) else {}
        raw["agent_hub"] = {
            **base_metadata,
            "mode": "agent",
            "steps": trace,
            "validation_history": _validation_history_from_trace(trace),
            "repair_history": _repair_history_from_trace(trace),
            "reasoning_state": reasoning_state.to_dict() if reasoning_state else None,
            "execution_plan": reasoning_state.execution_plan.to_dict() if reasoning_state else None,
            "stopped": stopped,
        }
        if response:
            return HubResponse(
                request_id=response.request_id,
                session_id=request.session_id,
                agent=response.agent,
                provider=response.provider,
                model=response.model,
                public_model=response.public_model,
                text=text,
                usage=response.usage,
                raw=raw,
                finish_reason=response.finish_reason,
                failover=failover,
                citations=response.citations,
                search_results=response.search_results,
                images=response.images,
                related_questions=response.related_questions,
            )
        return HubResponse(
            request_id=f"hub-{uuid.uuid4().hex}",
            session_id=request.session_id,
            agent="agent-runner",
            provider="agent-hub",
            model="agent-runner",
            public_model=request.route or "agent-hub-local",
            text=text,
            raw=raw,
            failover=failover,
        )

    def _record_final(self, request: HubRequest, response: HubResponse) -> None:
        if request.record_session:
            self.router.session_store.record_turn(request, response)


def _emit(event_sink: AgentEventSink | None, event_type: str, **data: Any) -> None:
    if event_sink is None:
        return
    event = {"type": event_type, **data}
    try:
        event_sink(event)
    except Exception:
        # Progress events are best-effort; the agent loop should still complete.
        return


def _emit_reasoning_state_updated(
    event_sink: AgentEventSink | None,
    state: WorkspaceReasoningState,
) -> None:
    _emit(
        event_sink,
        "reasoning_state_updated",
        message="Workspace reasoning state updated.",
        task_id=state.task_id,
        active_files=state.active_files[-10:],
        inspected_files_count=len(state.inspected_files),
        planned_edits_count=len(state.planned_edits),
        validation_history_count=len(state.validation_history),
        repair_history_count=len(state.repair_history),
        active_execution_node=state.execution_plan.active_node,
    )


def _active_files_from_toolbox(toolbox: AgentToolbox) -> list[str]:
    try:
        return [toolbox._relative(path) for path in toolbox._request_context_paths() if path.exists()]
    except Exception:
        return []


def _active_execution_metadata(state: WorkspaceReasoningState) -> dict[str, Any] | None:
    node = state.execution_plan.active()
    if node is None:
        return None
    return {
        "id": node.id,
        "objective": node.objective,
        "status": node.status,
        "dependencies": node.dependencies,
        "affected_files": node.affected_files,
        "validation_targets": node.validation_targets,
        "estimated_risk": node.estimated_risk,
        "retry_count": node.retry_count,
    }


def _annotate_validation_with_execution(
    validation: dict[str, Any],
    state: WorkspaceReasoningState,
) -> None:
    node = state.execution_plan.active()
    validation["execution_node"] = node.id if node else None
    validation["execution_objective"] = node.objective if node else ""
    validation["validation_targets"] = _validation_targets_from_state(validation, state)
    validation["blocked_execution_nodes"] = list(state.execution_plan.blocked_nodes)


def _validation_targets_from_state(
    validation: dict[str, Any],
    state: WorkspaceReasoningState,
) -> list[str]:
    changed = [str(path) for path in validation.get("changed_files", []) if isinstance(path, str)]
    targets = list(changed)
    for path in changed:
        targets.extend(state.dependency_map.get(path, []))
    summary = state.repository_summary
    reverse = summary.get("reverse_dependency_map") if isinstance(summary, dict) else None
    if isinstance(reverse, dict):
        for path in changed:
            values = reverse.get(path)
            if isinstance(values, list):
                targets.extend(str(value) for value in values if isinstance(value, str))
    validation_targets = summary.get("validation_targets") if isinstance(summary, dict) else None
    if isinstance(validation_targets, list):
        targets.extend(str(value) for value in validation_targets if isinstance(value, str))
    return _dedupe_strings(targets)[:40]


def _enrich_approval_with_execution(
    result: dict[str, Any],
    state: WorkspaceReasoningState,
) -> None:
    node = state.execution_plan.active()
    affected_files = [str(path) for path in result.get("affected_files", []) if isinstance(path, str)]
    dependency_impact = _dependency_impact_for_files(state, affected_files)
    result["execution_objective"] = node.objective if node else ""
    result["execution_node"] = node.id if node else None
    result["affected_execution_nodes"] = [node.id] if node else []
    result["dependency_impact"] = dependency_impact
    result["repository_impact"] = {
        "affected_files": affected_files,
        "dependent_files": dependency_impact.get("dependent_files", []),
        "dependency_files": dependency_impact.get("dependency_files", []),
        "estimated_risk": result.get("risk_level") or (node.estimated_risk if node else "low"),
    }
    result["rollback_safety"] = "pre_edit_checkpoint_required"


def _dependency_impact_for_files(
    state: WorkspaceReasoningState,
    files: list[str],
) -> dict[str, list[str]]:
    dependency_files: list[str] = []
    dependent_files: list[str] = []
    for path in files:
        dependency_files.extend(state.dependency_map.get(path, []))
    summary = state.repository_summary
    reverse = summary.get("reverse_dependency_map") if isinstance(summary, dict) else None
    if isinstance(reverse, dict):
        for path in files:
            values = reverse.get(path)
            if isinstance(values, list):
                dependent_files.extend(str(value) for value in values if isinstance(value, str))
    return {
        "dependency_files": _dedupe_strings(dependency_files)[:30],
        "dependent_files": _dedupe_strings(dependent_files)[:30],
    }


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _validation_history_from_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for step in trace:
        result = step.get("result")
        if not isinstance(result, dict):
            continue
        validation = result.get("validation")
        if isinstance(validation, dict):
            history.append(
                {
                    "step": step.get("step"),
                    "tool": step.get("tool"),
                    "ok": validation.get("ok"),
                    "mode": validation.get("mode"),
                    "execution_node": validation.get("execution_node"),
                    "changed_files": validation.get("changed_files", []),
                    "validation_targets": validation.get("validation_targets", []),
                    "failed_categories": validation.get("failed_categories", []),
                    "checks": validation.get("checks", []),
                }
            )
    return history


def _repair_history_from_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for step in trace:
        result = step.get("result")
        if not isinstance(result, dict):
            continue
        repair = result.get("repair")
        if isinstance(repair, dict):
            history.append({"step": step.get("step"), "tool": step.get("tool"), **repair})
    return history


def _agent_step_raw(
    request: HubRequest,
    toolbox: AgentToolbox,
    *,
    trace: list[dict[str, Any]],
    repair_attempts_current: int,
    repair_attempts_max: int,
    reasoning_state: WorkspaceReasoningState,
) -> dict[str, Any]:
    raw = dict(request.raw or {})
    tools = agent_tool_definitions(toolbox.allow_shell)
    if toolbox.shell_command_policy == "deny":
        tools = [tool for tool in tools if tool.get("name") != "run_command"]
    allowed = toolbox.allowed_tool_names
    if allowed is not None:
        tools = [tool for tool in tools if tool.get("name") in allowed]
    raw["agent_hub_tools"] = tools
    runtime = raw.get("agent_hub_runtime")
    runtime = dict(runtime) if isinstance(runtime, dict) else {}
    runtime.update(
        {
            "repair_attempts_current": repair_attempts_current,
            "repair_attempts_max": repair_attempts_max,
            "recent_steps": _recent_step_context(trace),
            "pending_validation": _last_failed_validation(trace),
            "pending_checkpoint": _last_checkpoint(trace),
            "reasoning_state": reasoning_state.to_dict(),
            "execution_plan": reasoning_state.execution_plan.to_dict(),
            "active_execution_node": _active_execution_metadata(reasoning_state),
        }
    )
    raw["agent_hub_runtime"] = runtime
    return raw


def _recent_step_context(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    for step in trace[-5:]:
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        context.append(
            {
                "step": step.get("step"),
                "tool": step.get("tool"),
                "ok": result.get("ok") is not False,
                "changed_files": _changed_files_from_result(str(step.get("tool", "")), result),
                "repair": result.get("repair") if isinstance(result.get("repair"), dict) else None,
            }
        )
    return context


def _last_failed_validation(trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    for step in reversed(trace):
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        validation = result.get("validation")
        if isinstance(validation, dict) and validation.get("ok") is False:
            return {
                "step": step.get("step"),
                "tool": step.get("tool"),
                "changed_files": validation.get("changed_files", []),
                "failed_categories": validation.get("failed_categories", []),
                "checks": validation.get("checks", []),
            }
    return None


def _last_checkpoint(trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    for step in reversed(trace):
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        checkpoint = result.get("checkpoint")
        if isinstance(checkpoint, dict):
            return {
                "step": step.get("step"),
                "id": checkpoint.get("id"),
                "paths": checkpoint.get("paths", []),
            }
    return None


def _edit_policy_feedback(
    toolbox: AgentToolbox,
    tool_name: str,
    args: dict[str, Any],
    request: HubRequest,
    trace: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if tool_name == "apply_patch":
        return _apply_patch_rewrite_policy_feedback(toolbox, args, request)
    if tool_name not in {"write_file", "replace_in_file"}:
        return None
    if not _request_bool(request, "prefer_multi_file_patches", toolbox.config.prefer_multi_file_patches):
        return None

    affected = _policy_affected_files(toolbox, tool_name, args)
    in_repair = _repair_context_active(trace, messages)
    multi_file_task = _task_mentions_multi_file_work(request)
    if tool_name == "write_file":
        path = affected[0] if affected else _short_value(args.get("path"))
        target = _policy_resolved_path(toolbox, args.get("path"))
        append = bool(args.get("append", False))
        existing_overwrite = bool(target and target.exists() and not append)
        content = args.get("content")
        content_chars = len(content) if isinstance(content, str) else 0
        if existing_overwrite or in_repair or (multi_file_task and content_chars > 0):
            return _edit_policy_result(
                tool_name,
                affected,
                reason=(
                    "write_file is reserved for new generated files or tiny isolated writes. "
                    "For existing files, repairs, or multi-file work, prepare a grouped apply_patch."
                ),
                context={
                    "existing_overwrite": existing_overwrite,
                    "repair_context": in_repair,
                    "multi_file_task": multi_file_task,
                    "content_chars": content_chars,
                    "target": path,
                },
            )
    if tool_name == "replace_in_file":
        old = args.get("old")
        new = args.get("new")
        old_chars = len(old) if isinstance(old, str) else 0
        new_chars = len(new) if isinstance(new, str) else 0
        try:
            expected_replacements = int(args.get("expected_replacements", 1))
        except (TypeError, ValueError):
            expected_replacements = 1
        large_replace = old_chars > 400 or new_chars > 400 or expected_replacements > 1
        if not (in_repair or multi_file_task or large_replace):
            return None
        return _edit_policy_result(
            tool_name,
            affected,
            reason=(
                "replace_in_file is allowed for tiny isolated changes only. Repairs, multi-file work, "
                "large replacements, or repeated replacements should use a grouped apply_patch."
            ),
            context={
                "repair_context": in_repair,
                "multi_file_task": multi_file_task,
                "large_replace": large_replace,
                "old_chars": old_chars,
                "new_chars": new_chars,
                "expected_replacements": expected_replacements,
                "target": affected[0] if affected else _short_value(args.get("path")),
            },
        )
    return None


def _apply_patch_rewrite_policy_feedback(
    toolbox: AgentToolbox,
    args: dict[str, Any],
    request: HubRequest,
) -> dict[str, Any] | None:
    changes = args.get("changes")
    if not isinstance(changes, list):
        return None
    risky_files: list[str] = []
    for item in changes:
        if not isinstance(item, dict) or "content" not in item:
            continue
        path_value = item.get("path")
        target = _policy_resolved_path(toolbox, path_value)
        if target is None or not target.exists() or not target.is_file():
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        try:
            existing_chars = len(target.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            existing_chars = 0
        content_chars = len(content)
        if existing_chars > 500 and content_chars >= int(existing_chars * 0.8):
            risky_files.append(toolbox._relative(target))
    if not risky_files or _request_allows_full_rewrite(request, args):
        return None
    return _edit_policy_result(
        "apply_patch",
        risky_files,
        reason=(
            "Structured apply_patch content would rewrite large existing file(s). Use old/new hunks "
            "for surgical changes, or provide an explicit rewrite_justification/allow_full_file_rewrite."
        ),
        context={
            "rewrite_risk": "high",
            "risky_files": risky_files,
            "change_count": len(changes),
        },
    )


def _request_allows_full_rewrite(request: HubRequest, args: dict[str, Any]) -> bool:
    if _request_bool(request, "allow_full_file_rewrite", False):
        return True
    justification = args.get("rewrite_justification")
    if isinstance(justification, str) and len(justification.strip()) >= 20:
        return True
    text = " ".join(
        str(value or "")
        for value in [
            request.task,
            request.context,
            *[
                message.get("content")
                for message in request.messages
                if isinstance(message.get("content"), str)
            ],
        ]
    ).lower()
    return any(phrase in text for phrase in ("rewrite the entire file", "full rewrite", "replace the whole file"))


def _edit_policy_result(
    tool_name: str,
    affected_files: list[str],
    *,
    reason: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": tool_name,
        "edit_policy_feedback": True,
        "recommended_tool": "apply_patch",
        "affected_files": affected_files,
        "error": reason,
        "message": (
            "Edit policy requested a surgical apply_patch before modifying the workspace."
            if tool_name == "apply_patch"
            else "Edit policy requested apply_patch before modifying the workspace."
        ),
        "policy": {
            "name": "patch_first",
            "reason": reason,
            "context": context,
            "instructions": [
                "Re-read relevant files if needed.",
                "Batch related implementation, tests, docs, and config changes together.",
                "Use apply_patch with a concise summary and validation_plan.",
                "Avoid full-file rewrites unless the file is new or generated.",
            ],
        },
    }


def _policy_affected_files(toolbox: AgentToolbox, tool_name: str, args: dict[str, Any]) -> list[str]:
    value = args.get("path")
    if not isinstance(value, str) or not value.strip():
        return []
    path = _policy_resolved_path(toolbox, value)
    if path is None:
        return [value]
    return [toolbox._relative(path)]


def _policy_resolved_path(toolbox: AgentToolbox, value: Any) -> Path | None:
    try:
        return toolbox._resolve(value)
    except Exception:
        return None


def _repair_context_active(trace: list[dict[str, Any]], messages: list[dict[str, Any]]) -> bool:
    if _last_failed_validation(trace) is not None:
        return True
    for step in reversed(trace[-3:]):
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        if isinstance(result.get("repair"), dict) or isinstance(result.get("rollback"), dict):
            return True
    for message in messages[-4:]:
        content = message.get("content")
        if isinstance(content, str) and "Automatic repair is required" in content:
            return True
    return False


def _task_mentions_multi_file_work(request: HubRequest) -> bool:
    text = " ".join(
        str(value or "")
        for value in [
            request.task,
            request.context,
            *[
                message.get("content")
                for message in request.messages
                if isinstance(message.get("content"), str)
            ],
        ]
    ).lower()
    return any(
        phrase in text
        for phrase in (
            "multiple files",
            "multi-file",
            "several files",
            "implementation and tests",
            "tests and docs",
            "update tests",
            "add tests",
            "refactor",
            "repository-wide",
            "repo-wide",
        )
    )


def _workspace_edit_event(
    step_number: int,
    tool_name: str,
    result: dict[str, Any],
) -> dict[str, Any] | None:
    if result.get("ok") is False or tool_name not in {"write_file", "replace_in_file", "apply_patch"}:
        return None
    payload = result.get("result")
    if not isinstance(payload, dict):
        return None
    if tool_name == "apply_patch":
        paths = payload.get("paths")
        if not isinstance(paths, list):
            return None
        return {
            "message": f"Step {step_number}: applied patch to {len(paths)} file(s).",
            "step": step_number,
            "tool": tool_name,
            "path": ", ".join(str(path) for path in paths[:5]),
            "paths": paths,
            "action": "patched",
        }
    path = _short_value(payload.get("path"))
    if not path:
        return None
    action = "appended" if tool_name == "write_file" and payload.get("append") else "wrote"
    if tool_name == "replace_in_file":
        action = "updated"
    return {
        "message": f"Step {step_number}: workspace file {action}: {path}.",
        "step": step_number,
        "tool": tool_name,
        "path": path,
        "action": action,
    }


def _model_response_message(
    step_number: int,
    response: HubResponse,
    command: dict[str, Any],
) -> str:
    action = command.get("action")
    if action == "tool":
        return f"Step {step_number}: {response.agent} selected {command.get('tool', 'a tool')}."
    if action == "final":
        return f"Step {step_number}: {response.agent} returned a final answer."
    if action == "invalid":
        return f"Step {step_number}: {response.agent} returned an invalid agent message."
    return f"Step {step_number}: {response.agent} returned a response."


def _tool_started_message(step_number: int, tool_name: str, args: dict[str, Any]) -> str:
    target = _tool_target(tool_name, args)
    suffix = f" for {target}" if target else ""
    return f"Step {step_number}: running {tool_name}{suffix}."


def _tool_finished_message(step_number: int, tool_name: str, result: dict[str, Any]) -> str:
    status = "finished" if result.get("ok") is not False else "failed"
    summary = _tool_result_summary(tool_name, result)
    suffix = f": {summary}" if summary else ""
    return f"Step {step_number}: {tool_name} {status}{suffix}."


def _tool_target(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name in {"read_file", "write_file", "replace_in_file"}:
        return _short_value(args.get("path"))
    if tool_name == "apply_patch":
        summary = _short_value(args.get("summary"), maximum=160)
        return summary or "workspace patch"
    if tool_name == "search_files":
        query = _short_value(args.get("query"))
        path = _short_value(args.get("path", "."))
        return f"{query} in {path}" if query else path
    if tool_name == "repo_map":
        return _short_value(args.get("target") or args.get("path") or "workspace")
    if tool_name == "list_files":
        return _short_value(args.get("path", "."))
    if tool_name == "run_command":
        return _short_value(args.get("command"), maximum=160)
    return ""


def _tool_result_summary(tool_name: str, result: dict[str, Any]) -> str:
    if result.get("ok") is False:
        return _short_value(result.get("error"), maximum=180)
    payload = result.get("result")
    if not isinstance(payload, dict):
        return ""
    if tool_name in {"read_file", "write_file", "replace_in_file"}:
        path = _short_value(payload.get("path"))
        if tool_name == "replace_in_file" and payload.get("replacements") is not None:
            return f"{path}, {payload.get('replacements')} replacement(s)"
        return path
    if tool_name == "apply_patch":
        paths = payload.get("paths")
        return f"{len(paths)} file(s)" if isinstance(paths, list) else ""
    if tool_name == "search_files":
        matches = payload.get("matches")
        return f"{len(matches)} match(es)" if isinstance(matches, list) else ""
    if tool_name == "repo_map":
        related = payload.get("related_files")
        return f"{len(related)} related file(s)" if isinstance(related, list) else ""
    if tool_name == "list_files":
        files = payload.get("files")
        return f"{len(files)} item(s)" if isinstance(files, list) else ""
    if tool_name == "run_command":
        return f"exit code {payload.get('returncode')}"
    return ""


def _progress_tool_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "run_command":
        return {
            "command": args.get("command"),
            "cwd": args.get("cwd", "."),
            "timeout_seconds": args.get("timeout_seconds"),
        }
    if tool_name == "write_file":
        content = args.get("content")
        return {
            "path": args.get("path"),
            "append": args.get("append", False),
            "content_chars": len(content) if isinstance(content, str) else None,
        }
    if tool_name == "replace_in_file":
        old = args.get("old")
        new = args.get("new")
        return {
            "path": args.get("path"),
            "old_chars": len(old) if isinstance(old, str) else None,
            "new_chars": len(new) if isinstance(new, str) else None,
            "expected_replacements": args.get("expected_replacements", 1),
        }
    if tool_name == "apply_patch":
        patch = args.get("patch")
        changes = args.get("changes")
        return {
            "summary": args.get("summary"),
            "patch_chars": len(patch) if isinstance(patch, str) else None,
            "change_count": len(changes) if isinstance(changes, list) else None,
            "validation_plan": args.get("validation_plan"),
            "commands": args.get("commands"),
        }
    allowed = {
        "path",
        "pattern",
        "recursive",
        "limit",
        "query",
        "case_sensitive",
        "start_line",
        "line_count",
        "max_chars",
        "target",
    }
    return {key: value for key, value in args.items() if key in allowed}


def _progress_tool_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    if result.get("ok") is False:
        return {"ok": False, "error": result.get("error")}
    payload = result.get("result")
    if not isinstance(payload, dict):
        return {"ok": True}
    if tool_name == "run_command":
        return {
            "ok": True,
            "command": payload.get("command"),
            "cwd": payload.get("cwd"),
            "returncode": payload.get("returncode"),
            "stdout": _short_value(payload.get("stdout"), maximum=2000),
            "stderr": _short_value(payload.get("stderr"), maximum=2000),
            "stdout_truncated": payload.get("stdout_truncated"),
            "stderr_truncated": payload.get("stderr_truncated"),
        }
    summary_keys = {
        "path",
        "paths",
        "replacements",
        "chars",
        "append",
        "truncated",
        "start_line",
        "end_line",
        "total_lines",
        "query",
        "summary",
    }
    summarized = {key: value for key, value in payload.items() if key in summary_keys}
    if isinstance(payload.get("files"), list):
        summarized["file_count"] = len(payload["files"])
    if isinstance(payload.get("matches"), list):
        summarized["match_count"] = len(payload["matches"])
    if isinstance(payload.get("related_files"), list):
        summarized["related_file_count"] = len(payload["related_files"])
    if isinstance(payload.get("test_files"), list):
        summarized["test_file_count"] = len(payload["test_files"])
    if isinstance(payload.get("dependency_files"), list):
        summarized["dependency_file_count"] = len(payload["dependency_files"])
    if isinstance(payload.get("validation_targets"), list):
        summarized["validation_target_count"] = len(payload["validation_targets"])
    return {"ok": True, **summarized}


def _changed_files_from_result(tool_name: str, result: dict[str, Any]) -> list[str]:
    if result.get("ok") is False or tool_name not in {"write_file", "replace_in_file", "apply_patch"}:
        return []
    payload = result.get("result")
    if not isinstance(payload, dict):
        return []
    if tool_name == "apply_patch":
        paths = payload.get("paths")
        return [str(path) for path in paths if isinstance(path, str)] if isinstance(paths, list) else []
    path = payload.get("path")
    return [str(path)] if isinstance(path, str) and path else []


def _validate_after_edit(
    request: HubRequest,
    config: HubConfig,
    root: Path,
    changed_files: list[str],
    event_sink: AgentEventSink | None,
) -> dict[str, Any] | None:
    if not changed_files:
        return None
    if not _request_bool(request, "auto_validate_after_edits", config.auto_validate_after_edits):
        return None
    mode = _request_validation_mode(request, config)
    if mode == "off":
        return None
    commands = _validation_command_plan(request, config, root, changed_files, mode)
    if not commands:
        return {
            "ok": True,
            "mode": mode,
            "changed_files": changed_files,
            "validation_targets": _discover_validation_targets(root, changed_files),
            "checks": [],
            "message": "No validators were available for the changed files.",
        }
    _emit(
        event_sink,
        "validation_started",
        message=f"Running {len(commands)} validation check(s).",
        mode=mode,
        changed_files=changed_files,
        commands=[item["display"] for item in commands],
    )
    checks: list[dict[str, Any]] = []
    for item in commands:
        try:
            completed = subprocess.run(
                item["command"],
                shell=item["shell"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=item["timeout_seconds"],
            )
            checks.append(
                {
                    "name": item["name"],
                    "category": item["category"],
                    "failure_category": _validation_failure_category(
                        item["category"],
                        completed.stdout,
                        completed.stderr,
                    ) if completed.returncode != 0 else None,
                    "command": item["display"],
                    "returncode": completed.returncode,
                    "ok": completed.returncode == 0,
                    "stdout": _short_value(completed.stdout, maximum=4000),
                    "stderr": _short_value(completed.stderr, maximum=4000),
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "name": item["name"],
                    "category": item["category"],
                    "failure_category": "command",
                    "command": item["display"],
                    "returncode": None,
                    "ok": False,
                    "stdout": "",
                    "stderr": str(exc),
                }
            )
    ok = all(check["ok"] for check in checks)
    categories = sorted({str(check["category"]) for check in checks})
    failed_categories = sorted(
        {
            str(check.get("failure_category") or check["category"])
            for check in checks
            if check.get("ok") is False
        }
    )
    result = {
        "ok": ok,
        "mode": mode,
        "changed_files": changed_files,
        "validation_targets": _discover_validation_targets(root, changed_files),
        "checks": checks,
        "categories": categories,
        "failed_categories": failed_categories,
        "message": "Validation passed." if ok else "Validation failed.",
    }
    _emit(
        event_sink,
        "validation_finished",
        message=result["message"],
        ok=ok,
        mode=mode,
        changed_files=changed_files,
        checks=checks,
    )
    if not ok:
        _emit(
            event_sink,
            "validation_failed",
            message="Validation failed after applying workspace edits.",
            mode=mode,
            changed_files=changed_files,
            checks=checks,
        )
    return result


def _validation_command_plan(
    request: HubRequest,
    config: HubConfig,
    root: Path,
    changed_files: list[str],
    mode: str,
) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    py_files = [
        str((root / path).resolve())
        for path in changed_files
        if path.endswith(".py") and (root / path).exists()
    ]
    if py_files:
        commands.append(
            {
                "name": "py_compile",
                "category": "syntax",
                "command": [sys.executable, "-m", "py_compile", *py_files],
                "display": "python -m py_compile " + " ".join(changed_files),
                "shell": False,
                "timeout_seconds": 120,
            }
        )
    if _workspace_has_tests(root):
        commands.append(
            {
                "name": "unittest",
                "category": "tests",
                "command": [sys.executable, "-m", "unittest", "discover", "-v"],
                "display": "python -m unittest discover -v",
                "shell": False,
                "timeout_seconds": 300,
            }
        )
    for command in _request_validation_commands(request, config):
        formatted_command = _format_validation_command(command, root, changed_files)
        commands.append(
            {
                "name": "configured",
                "category": _validation_command_category(command),
                "command": formatted_command,
                "display": formatted_command,
                "shell": True,
                "timeout_seconds": 600 if mode == "strict" else 300,
            }
        )
    return commands


def _format_validation_command(command: str, root: Path, changed_files: list[str]) -> str:
    absolute_files = [
        str((root / path).resolve())
        for path in changed_files
        if (root / path).exists()
    ]
    relative_files = [path for path in changed_files if (root / path).exists()]
    replacements = {
        "{files}": subprocess.list2cmdline(absolute_files),
        "{changed_files}": subprocess.list2cmdline(relative_files),
        "{file}": subprocess.list2cmdline(absolute_files[:1]),
        "{changed_file}": subprocess.list2cmdline(relative_files[:1]),
    }
    formatted = command
    for token, value in replacements.items():
        formatted = formatted.replace(token, value)
    return formatted


def _validation_command_category(command: str) -> str:
    lowered = command.lower()
    if any(name in lowered for name in ("ruff", "flake8", "pylint", "eslint", "lint")):
        return "lint"
    if any(name in lowered for name in ("pytest", "unittest", "npm test", "go test", "cargo test")):
        return "tests"
    if any(name in lowered for name in ("mypy", "pyright", "typecheck", "type-check", "tsc")):
        return "type"
    if any(name in lowered for name in ("py_compile", "compile")):
        return "syntax"
    return "command"


def _validation_failure_category(default: str, stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}".lower()
    if any(token in text for token in ("syntaxerror", "indentationerror", "parse error")):
        return "syntax"
    if any(token in text for token in ("importerror", "modulenotfounderror", "cannot import")):
        return "import"
    if any(token in text for token in ("typeerror", "mypy", "pyright", "tsc", "type error")):
        return "type"
    if any(token in text for token in ("assertionerror", "failed", "failure", "pytest", "unittest")):
        return "tests" if default == "tests" else default
    return default or "command"


def _workspace_has_tests(root: Path) -> bool:
    if (root / "tests").is_dir():
        return True
    try:
        return any(root.glob("test*.py")) or any(root.glob("*_test.py"))
    except OSError:
        return False


def _discover_validation_targets(root: Path, changed_files: list[str]) -> list[str]:
    targets = list(changed_files)
    changed_stems = {Path(path).stem.lower() for path in changed_files}
    test_dirs = [root / "tests", root]
    for directory in test_dirs:
        if not directory.exists() or not directory.is_dir():
            continue
        try:
            candidates = list(directory.rglob("test*.py")) + list(directory.rglob("*_test.py"))
        except OSError:
            continue
        for path in candidates[:200]:
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            stem = path.stem.lower().removeprefix("test_").removesuffix("_test")
            if stem in changed_stems or any(changed in stem for changed in changed_stems):
                targets.append(relative)
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(changed.replace("/", ".").removesuffix(".py") in text for changed in changed_files):
                targets.append(relative)
    return _dedupe_strings(targets)[:40]


def _request_validation_mode(request: HubRequest, config: HubConfig) -> str:
    value = str(_request_option(request, "validation_mode", config.validation_mode) or "basic").lower()
    if value in {"off", "none", "false", "0"}:
        return "off"
    if value == "strict":
        return "strict"
    return "basic"


def _request_validation_commands(request: HubRequest, config: HubConfig) -> list[str]:
    value = _request_option(request, "validation_commands", config.validation_commands)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str) and item.strip()]
    return []


def _restore_after_failed_validation(
    request: HubRequest,
    config: HubConfig,
    root: Path,
    result: dict[str, Any],
    event_sink: AgentEventSink | None,
) -> dict[str, Any] | None:
    validation = result.get("validation")
    if not isinstance(validation, dict) or validation.get("ok") is not False:
        return None
    if not _request_bool(
        request,
        "rollback_on_validation_failure",
        config.rollback_on_validation_failure,
    ):
        return None
    checkpoint = result.get("checkpoint")
    if not isinstance(checkpoint, dict):
        rollback = {
            "ok": False,
            "checkpoint_id": "",
            "restored_files": [],
            "removed_files": [],
            "errors": [{"path": "", "error": "No checkpoint was available for validation rollback."}],
        }
    else:
        rollback = restore_workspace_checkpoint(checkpoint, root=root)
    _emit(
        event_sink,
        "workspace_restored",
        message=(
            "Workspace restored after failed validation."
            if rollback.get("ok")
            else "Workspace rollback after failed validation did not fully complete."
        ),
        ok=rollback.get("ok"),
        checkpoint_id=rollback.get("checkpoint_id", ""),
        restored_files=rollback.get("restored_files", []),
        removed_files=rollback.get("removed_files", []),
        errors=rollback.get("errors", []),
    )
    return rollback


def _repair_decision_for_result(
    tool_name: str,
    result: dict[str, Any],
    repair_attempts: int,
    max_attempts: int,
    *,
    reasoning_state: WorkspaceReasoningState | None = None,
) -> dict[str, Any]:
    if tool_name not in EDIT_TOOLS:
        return {"message": "", "exhausted": False}

    if result.get("ok") is False:
        kind = "tool_failure"
        failure = _edit_tool_failure_summary(tool_name, result)
    else:
        validation = result.get("validation")
        if not isinstance(validation, dict) or validation.get("ok") is not False:
            return {"message": "", "exhausted": False}
        kind = "validation_failure"
        failure = _validation_failure_summary(validation)

    if repair_attempts >= max_attempts:
        return {
            "message": "",
            "exhausted": True,
            "kind": kind,
            "event_message": "Agent stopped after edit repair attempts were exhausted.",
        }

    attempt = repair_attempts + 1
    message = _repair_feedback_message(
        tool_name=tool_name,
        result=result,
        kind=kind,
        failure=failure,
        attempt=attempt,
        max_attempts=max_attempts,
        reasoning_state=reasoning_state,
    )
    return {
        "message": message,
        "exhausted": False,
        "kind": kind,
        "event_message": (
            "Validation failed; feeding back to agent for repair attempt."
            if kind == "validation_failure"
            else "Edit tool failed; feeding back to agent for repair attempt."
        ),
    }


def _repair_feedback_message(
    *,
    tool_name: str,
    result: dict[str, Any],
    kind: str,
    failure: dict[str, Any],
    attempt: int,
    max_attempts: int,
    reasoning_state: WorkspaceReasoningState | None = None,
) -> str:
    rollback = result.get("rollback") if isinstance(result.get("rollback"), dict) else None
    execution_node = _active_execution_metadata(reasoning_state) if reasoning_state is not None else None
    dependency_impact = (
        _dependency_impact_for_files(reasoning_state, _repair_changed_files(result))
        if reasoning_state is not None
        else {"dependency_files": [], "dependent_files": []}
    )
    payload = {
        "failure_type": kind,
        "tool": tool_name,
        "repair_attempt": attempt,
        "max_attempts": max_attempts,
        "failure": failure,
        "execution_node": execution_node,
        "dependency_impact": dependency_impact,
        "prior_patch": _prior_patch_summary(result),
        "rollback": _rollback_summary(rollback),
        "targeted_strategy": _repair_strategy(kind, failure),
        "instructions": [
            "Re-read affected files when context may be stale.",
            "Prefer apply_patch for the repair, especially when more than one file is involved.",
            "Prepare one grouped correction and preserve formatting/style.",
            "Do not repeat a failed edit without changing the patch or replacement target.",
        ],
    }
    if rollback and rollback.get("ok"):
        payload["workspace_state"] = "restored_to_pre_edit_checkpoint"
    elif rollback:
        payload["workspace_state"] = "rollback_failed_or_partial"
    else:
        payload["workspace_state"] = "current_edit_state_preserved"
    return (
        "Automatic repair is required before continuing.\n"
        f"{json.dumps(payload, indent=2, ensure_ascii=False)}\n\n"
        "Continue with exactly one JSON object. Use a tool call to repair the workspace, "
        "or a final answer only if no safe repair is possible."
    )


def _repair_changed_files(result: dict[str, Any]) -> list[str]:
    validation = result.get("validation")
    if isinstance(validation, dict):
        return [str(path) for path in validation.get("changed_files", []) if isinstance(path, str)]
    payload = result.get("result")
    if isinstance(payload, dict) and isinstance(payload.get("paths"), list):
        return [str(path) for path in payload["paths"] if isinstance(path, str)]
    if isinstance(payload, dict) and isinstance(payload.get("path"), str):
        return [payload["path"]]
    return []


def _prior_patch_summary(result: dict[str, Any]) -> dict[str, Any] | None:
    payload = result.get("result")
    if not isinstance(payload, dict):
        return None
    summary = {
        "summary": payload.get("summary", ""),
        "paths": payload.get("paths", []),
        "changes": payload.get("changes", []),
    }
    return summary if any(summary.values()) else None


def _repair_strategy(kind: str, failure: dict[str, Any]) -> list[str]:
    if kind == "tool_failure":
        return [
            "Inspect the target file and exact old text before retrying.",
            "Use apply_patch with a smaller context if exact replacement text was stale.",
        ]
    categories = set(str(item) for item in failure.get("failed_categories", []))
    strategy: list[str] = []
    if "syntax" in categories:
        strategy.append("Fix parser/syntax errors first and keep the correction minimal.")
    if "import" in categories:
        strategy.append("Check module names, package exports, and import paths before editing.")
    if "type" in categories:
        strategy.append("Preserve public interfaces or update all typed call sites together.")
    if "tests" in categories:
        strategy.append("Use the failing assertion/output to target the changed behavior.")
    if "lint" in categories:
        strategy.append("Prefer formatting/style-compatible edits over broad rewrites.")
    if not strategy:
        strategy.append("Use the failed command output to make the smallest safe correction.")
    return strategy


def _edit_tool_failure_summary(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": "edit",
        "tool": tool_name,
        "error": _short_value(result.get("error"), maximum=2000),
        "checkpoint": _checkpoint_summary(result.get("checkpoint")),
        "rollback": _rollback_summary(result.get("rollback")),
    }


def _validation_failure_summary(validation: dict[str, Any]) -> dict[str, Any]:
    checks = validation.get("checks")
    failed_checks = [
        {
            "name": check.get("name", "unknown"),
            "category": check.get("category", "command"),
            "failure_category": check.get("failure_category") or check.get("category", "command"),
            "command": check.get("command", ""),
            "returncode": check.get("returncode"),
            "stdout": _short_value(check.get("stdout", ""), maximum=1200),
            "stderr": _short_value(check.get("stderr", ""), maximum=1200),
        }
        for check in checks
        if isinstance(check, dict) and check.get("ok") is False
    ] if isinstance(checks, list) else []
    return {
        "category": "validation",
        "mode": validation.get("mode"),
        "changed_files": validation.get("changed_files", []),
        "failed_categories": validation.get("failed_categories", []),
        "failed_checks": failed_checks,
    }


def _checkpoint_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "id": value.get("id", ""),
        "paths": value.get("paths", []),
    }


def _rollback_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "ok": value.get("ok"),
        "checkpoint_id": value.get("checkpoint_id", ""),
        "restored_files": value.get("restored_files", []),
        "removed_files": value.get("removed_files", []),
        "errors": value.get("errors", []),
    }


def _repair_exhausted_text(tool_name: str, result: dict[str, Any], max_attempts: int) -> str:
    if isinstance(result.get("validation"), dict) and result["validation"].get("ok") is False:
        summary = _validation_failure_summary(result["validation"])
        categories = ", ".join(str(item) for item in summary.get("failed_categories", [])) or "validation"
        rollback = _rollback_summary(result.get("rollback"))
        rollback_text = ""
        if rollback:
            rollback_text = (
                "\n\nWorkspace rollback: "
                + ("restored to the pre-edit checkpoint." if rollback.get("ok") else "failed or partial.")
            )
        return (
            f"Agent stopped because validation still failed after {max_attempts} repair attempt(s). "
            f"Failed category: {categories}."
            f"{rollback_text}"
        )
    error = _short_value(result.get("error"), maximum=500)
    return (
        f"Agent stopped because {tool_name} failed after {max_attempts} repair attempt(s)."
        + (f"\n\nLast error: {error}" if error else "")
    )


def _fast_tool_final_text(
    tool_name: str,
    result: dict[str, Any],
    request: HubRequest,
    config: HubConfig,
) -> str:
    if not _request_bool(request, "fast_write_finalize", config.fast_write_finalize):
        return ""
    # Never fast-finalize apply_patch; validation failures need feedback loop
    if result.get("ok") is False or tool_name not in {"write_file", "replace_in_file"}:
        return ""
    # If validation ran and failed, don't fast-finalize (validation failures should get feedback)
    validation = result.get("validation")
    if isinstance(validation, dict) and validation.get("ok") is False:
        return ""
    payload = result.get("result")
    if not isinstance(payload, dict):
        return ""
    path = _short_value(payload.get("path")) or "the requested file"
    if tool_name == "write_file":
        action = "Appended to" if payload.get("append") else "Wrote"
        chars = payload.get("chars")
        suffix = f" ({chars} character(s))." if chars is not None else "."
        return f"{action} {path}{suffix}"
    replacements = payload.get("replacements")
    if replacements is not None:
        return f"Updated {path} with {replacements} replacement(s)."
    return f"Updated {path}."


def _short_value(value: Any, maximum: int = 120) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= maximum:
        return text
    return f"{text[: maximum - 1]}..."


def _command_from_response(response: HubResponse) -> dict[str, Any]:
    tool_call = (
        _openai_tool_call(response.raw)
        or _anthropic_tool_call(response.raw)
        or _gemini_tool_call(response.raw)
    )
    if tool_call:
        return _validate_tool_command(tool_call)

    data = _json_from_text(response.text)
    if not isinstance(data, dict):
        recovered = _malformed_tool_command_from_text(response.text)
        return (
            _validate_tool_command(recovered)
            if recovered
            else {"action": "invalid", "reason": "response was not a JSON object"}
        )

    action = str(data.get("action", "")).lower()
    if action == "tool" or "tool" in data:
        tool = data.get("tool") or data.get("name")
        if tool:
            return _validate_tool_command(
                _tool_command(str(tool), data.get("args", data.get("arguments", {})))
            )
        return {"action": "invalid", "reason": "tool action is missing a tool name"}

    if action in TOOL_ACTIONS:
        return _validate_tool_command(
            _tool_command(action, data.get("args", data.get("arguments", {})))
        )

    if action == "final" or "final" in data or "answer" in data:
        return {"action": "final", "answer": data.get("answer", data.get("final", ""))}

    return {"action": "invalid", "reason": _invalid_json_reason(data, action)}


def _invalid_response_message(command: dict[str, Any]) -> dict[str, str]:
    reason = str(command.get("reason") or "response did not match the Agent Hub protocol")
    tools = ", ".join(sorted(TOOL_ACTIONS))
    return {
        "role": "user",
        "content": (
            f"Invalid Agent Hub JSON response: {reason}.\n\n"
            "Continue with exactly one JSON object and no Markdown. "
            'Use {"action":"tool","tool":"read_file","args":{"path":"README.md"}} '
            'to inspect files, or {"action":"final","answer":"..."} for the final answer. '
            f"Valid tool names are: {tools}."
        ),
    }


def _invalid_json_reason(data: dict[str, Any], action: str) -> str:
    if action:
        return f"unknown action {action!r}"
    keys = ", ".join(sorted(str(key) for key in data))
    return f"missing action field; keys present: {keys}" if keys else "empty JSON object"


def _echo_fallback_text(
    response: HubResponse,
    *,
    failover: list[FailoverEvent],
    trace: list[dict[str, Any]],
) -> str:
    lines = [
        "Agent Hub reached the echo fallback, which cannot continue the workspace agent protocol.",
    ]
    if failover:
        lines.append("")
        lines.append("Provider attempts:")
        for event in failover[-5:]:
            lines.append(f"- {event.agent}: {event.reason}")
    if trace:
        last = trace[-1]
        result = last.get("result") if isinstance(last.get("result"), dict) else {}
        status = "failed" if result.get("ok") is False else "ran"
        lines.append("")
        lines.append(f"Last tool step: {last.get('tool', 'unknown')} {status}.")
    if response.text:
        lines.append("")
        lines.append("Echo fallback response:")
        lines.append(response.text)
    return "\n".join(lines)


def _tool_command(tool: str, args: Any) -> dict[str, Any]:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {"input": args}
    return {"action": "tool", "tool": tool, "args": args if isinstance(args, dict) else {}}


def _validate_tool_command(command: dict[str, Any]) -> dict[str, Any]:
    tool = str(command.get("tool", ""))
    args = command.get("args") if isinstance(command.get("args"), dict) else {}
    if tool not in TOOL_ACTIONS:
        return {"action": "invalid", "reason": f"unknown tool {tool!r}"}

    missing = [
        key
        for key in REQUIRED_TOOL_ARGS.get(tool, ())
        if not isinstance(args.get(key), str)
    ]
    blank = [
        key
        for key in NON_EMPTY_TOOL_ARGS.get(tool, ())
        if isinstance(args.get(key), str) and not args.get(key).strip()
    ]
    if missing or blank:
        fields = ", ".join(f"args.{key}" for key in [*missing, *blank])
        return {"action": "invalid", "reason": f"{tool} requires {fields}"}

    if tool == "replace_in_file":
        expected = args.get("expected_replacements")
        if expected is not None:
            try:
                if int(expected) < 1:
                    return {
                        "action": "invalid",
                        "reason": "replace_in_file expected_replacements must be at least 1",
                    }
            except (TypeError, ValueError):
                return {
                    "action": "invalid",
                    "reason": "replace_in_file expected_replacements must be an integer",
                }

    if tool == "apply_patch":
        patch = args.get("patch")
        changes = args.get("changes")
        if not (isinstance(patch, str) and patch.strip()) and not (
            isinstance(changes, list) and changes
        ):
            return {
                "action": "invalid",
                "reason": "apply_patch requires args.patch or args.changes",
            }

    return {"action": "tool", "tool": tool, "args": args}


def _openai_tool_call(raw: dict[str, Any]) -> dict[str, Any] | None:
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return None
    function = tool_calls[0].get("function") if isinstance(tool_calls[0], dict) else None
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    if not isinstance(name, str):
        return None
    args = function.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return {"action": "tool", "tool": name, "args": args if isinstance(args, dict) else {}}


def _anthropic_tool_call(raw: dict[str, Any]) -> dict[str, Any] | None:
    content = raw.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        name = item.get("name")
        args = item.get("input", {})
        if isinstance(name, str):
            return {"action": "tool", "tool": name, "args": args if isinstance(args, dict) else {}}
    return None


def _gemini_tool_call(raw: dict[str, Any]) -> dict[str, Any] | None:
    candidates = raw.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    if not isinstance(content, dict):
        return None
    parts = content.get("parts")
    if not isinstance(parts, list):
        return None
    for part in parts:
        if not isinstance(part, dict):
            continue
        function_call = part.get("functionCall") or part.get("function_call")
        if not isinstance(function_call, dict):
            continue
        name = function_call.get("name")
        args = function_call.get("args", {})
        if isinstance(name, str):
            return {"action": "tool", "tool": name, "args": args if isinstance(args, dict) else {}}
    return None


def _json_from_text(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _malformed_tool_command_from_text(text: str) -> dict[str, Any] | None:
    stripped = _strip_markdown_fence(text)
    action = _string_field(stripped, "action")
    tool = _string_field(stripped, "tool") or (action if action in TOOL_ACTIONS else "")
    if action != "tool" and action not in TOOL_ACTIONS and not tool:
        return None
    if tool not in TOOL_ACTIONS:
        return None

    args_text = _object_field(stripped, "args") or _object_field(stripped, "arguments") or ""
    args: dict[str, Any] = {}
    path = _string_or_bare_field(args_text, "path")
    if path:
        args["path"] = path
    query = _string_or_bare_field(args_text, "query")
    if query:
        args["query"] = query
    target = _string_or_bare_field(args_text, "target")
    if target:
        args["target"] = target
    command = _string_or_bare_field(args_text, "command")
    if command:
        args["command"] = command
    content = _string_field(args_text, "content")
    if content:
        args["content"] = content
    old = _string_field(args_text, "old")
    if old:
        args["old"] = old
    new = _string_field(args_text, "new")
    if new:
        args["new"] = new

    for key in ("start_line", "line_count", "limit", "expected_replacements", "timeout_seconds"):
        value = _int_field(args_text, key)
        if value is not None:
            args[key] = value
    for key in ("recursive", "append", "case_sensitive"):
        value = _bool_field(args_text, key)
        if value is not None:
            args[key] = value

    return {"action": "tool", "tool": tool, "args": args}


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def _string_field(text: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', text)
    return match.group(1) if match else ""


def _string_or_bare_field(text: str, key: str) -> str:
    quoted = _string_field(text, key)
    if quoted:
        return quoted
    match = re.search(rf'"{re.escape(key)}"\s*:\s*([^,\n\r}}]+)', text)
    return match.group(1).strip().strip("\"'") if match else ""


def _object_field(text: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\{{(?P<body>.*?)\}}', text, flags=re.DOTALL)
    return match.group("body") if match else ""


def _int_field(text: str, key: str) -> int | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(-?\d+)', text)
    return int(match.group(1)) if match else None


def _bool_field(text: str, key: str) -> bool | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(true|false)', text, flags=re.IGNORECASE)
    return match.group(1).lower() == "true" if match else None


def _request_int(request: HubRequest, key: str, default: int) -> int:
    raw = request.raw or {}
    hub_options = raw.get("agent_hub")
    value = hub_options.get(key) if isinstance(hub_options, dict) and key in hub_options else raw.get(key)
    try:
        number = int(value if value is not None else default)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, 50))


def _request_nonnegative_int(request: HubRequest, key: str, default: int) -> int:
    raw = request.raw or {}
    hub_options = raw.get("agent_hub")
    value = hub_options.get(key) if isinstance(hub_options, dict) and key in hub_options else raw.get(key)
    try:
        number = int(value if value is not None else default)
    except (TypeError, ValueError):
        number = default
    return max(0, min(number, 50))


def _request_bool(request: HubRequest, key: str, default: bool) -> bool:
    value = _request_option(request, key, default)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _request_option(request: HubRequest, key: str, default: Any) -> Any:
    raw = request.raw or {}
    hub_options = raw.get("agent_hub")
    if isinstance(hub_options, dict) and key in hub_options:
        return hub_options[key]
    return raw.get(key, default)


def _is_prefix(prefix: list[dict], messages: list[dict]) -> bool:
    if len(prefix) > len(messages):
        return False
    return all(
        left.get("role") == right.get("role") and left.get("content") == right.get("content")
        for left, right in zip(prefix, messages, strict=False)
    )
