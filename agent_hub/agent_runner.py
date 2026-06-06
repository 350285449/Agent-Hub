from __future__ import annotations

import json
import hashlib
import re
import subprocess
import sys
import uuid
from collections.abc import Callable
from copy import deepcopy
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
from .context import (
    context_state_messages,
    is_protected_context_message,
    message_signature,
    request_context_diagnostics,
)
from .models import FailoverEvent, HubRequest, HubResponse
from .reasoning import WorkspaceReasoningState
from .security.command_runner import CommandExecutionRequest, run_workspace_command
from .core.router import AgentRouter
from .token_budget import TokenBudget, TokenBudgetManager, estimate_messages_tokens


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
CONTEXT_TOOLS = {"list_files", "read_file", "search_files", "repo_map"}
BROAD_CONTEXT_TOOLS = {"list_files", "search_files", "repo_map"}
DEDUPE_CONTEXT_TOOLS = {"read_file", "repo_map"}
FULL_TOOL_RESULT_HISTORY = 2
FULL_REPAIR_TOOL_RESULT_HISTORY = 2
CONTEXT_BUDGET_MARGIN_TOKENS = 128
MAX_FULL_TOOL_RESULT_CHARS = 16_000
LARGE_READ_FILE_FULL_ONCE_CHARS = 8_000
MAX_MEMORY_SUMMARY_TOOL_RESULTS = 10
MAX_COMPACT_SESSION_MESSAGES = 4
REPOSITORY_ROOT_FILE_NAMES = {
    ".dockerignore",
    ".editorconfig",
    ".env",
    ".gitattributes",
    ".gitignore",
    ".npmrc",
    "dockerfile",
    "license",
    "makefile",
    "readme",
}
REPOSITORY_FILE_EXTENSIONS = {
    ".astro",
    ".bat",
    ".c",
    ".cfg",
    ".cjs",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".cts",
    ".csv",
    ".env",
    ".fs",
    ".fsx",
    ".go",
    ".gradle",
    ".graphql",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".ipynb",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".less",
    ".lock",
    ".md",
    ".mjs",
    ".mts",
    ".php",
    ".properties",
    ".proto",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".rst",
    ".sass",
    ".scss",
    ".sh",
    ".sln",
    ".sql",
    ".svelte",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}

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


class ExecutionMemory:
    """Ephemeral per-run memory used to build bounded model prompt views."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self._full_send_counts: dict[int, int] = {}

    def record_tool_result(
        self,
        *,
        step: int,
        agent: str,
        provider: str,
        model: str,
        tool: str,
        args: dict[str, Any],
        result: dict[str, Any],
        repair_message: str = "",
    ) -> None:
        self.entries.append(
            {
                "kind": "tool",
                "step": step,
                "agent": agent,
                "provider": provider,
                "model": model,
                "tool": tool,
                "args": dict(args),
                "result": deepcopy(result),
                "repair_message": repair_message,
            }
        )

    def record_invalid_response(
        self,
        *,
        step: int,
        agent: str,
        provider: str,
        model: str,
        response_text: str,
        command: dict[str, Any],
    ) -> None:
        self.entries.append(
            {
                "kind": "invalid",
                "step": step,
                "agent": agent,
                "provider": provider,
                "model": model,
                "response_text": _short_value(response_text, maximum=800),
                "message": _invalid_response_message(command),
            }
        )

    def build_prompt_messages(
        self,
        base_messages: list[dict[str, Any]],
        request: HubRequest,
        router: AgentRouter,
        trace: list[dict[str, Any]],
        reasoning_state: WorkspaceReasoningState,
        *,
        previous_input_tokens: int | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        prompt_messages = [dict(message) for message in base_messages]
        memory_messages, memory_stats = self._memory_messages(trace, reasoning_state)
        prompt_messages.extend(memory_messages)
        context_usage = _prepare_agent_messages_for_step(
            prompt_messages,
            request,
            router,
            trace,
            previous_input_tokens=previous_input_tokens,
            pre_compacted_count=int(memory_stats.get("compacted_messages_count") or 0),
            pre_compacted_tool_results_count=int(
                memory_stats.get("compacted_tool_results_count") or 0
            ),
            pre_estimated_tokens_saved=int(memory_stats.get("estimated_tokens_saved") or 0),
        )
        return prompt_messages, context_usage

    def _memory_messages(
        self,
        trace: list[dict[str, Any]],
        reasoning_state: WorkspaceReasoningState,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        tool_indexes = [
            index
            for index, entry in enumerate(self.entries)
            if entry.get("kind") == "tool"
        ]
        if not self.entries:
            return [], {
                "compacted_messages_count": 0,
                "compacted_tool_results_count": 0,
                "estimated_tokens_saved": 0,
            }
        repair_active = _repair_context_active(trace, [])
        keep_full = FULL_REPAIR_TOOL_RESULT_HISTORY if repair_active else 2
        full_tool_indexes = self._select_full_tool_indexes(tool_indexes, keep_full)
        summarized_tool_indexes = [
            index for index in tool_indexes if index not in full_tool_indexes
        ]
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": _execution_memory_summary(
                    self.entries,
                    summarized_tool_indexes=summarized_tool_indexes,
                    reasoning_state=reasoning_state,
                    trace=trace,
                ),
            }
        ]
        for index, entry in enumerate(self.entries):
            kind = entry.get("kind")
            if kind == "tool" and index in full_tool_indexes:
                tool_name = str(entry.get("tool") or "")
                result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
                if tool_name and result:
                    messages.append(tool_result_message(tool_name, result))
                repair_message = str(entry.get("repair_message") or "")
                if repair_message:
                    messages.append({"role": "user", "content": repair_message})
            elif kind == "invalid" and index == len(self.entries) - 1:
                message = entry.get("message")
                if isinstance(message, dict):
                    messages.append(message)
        for index in full_tool_indexes:
            self._full_send_counts[index] = self._full_send_counts.get(index, 0) + 1
        full_memory_messages = self._full_memory_messages()
        estimated_saved = max(
            0,
            _estimated_message_tokens(full_memory_messages) - _estimated_message_tokens(messages),
        )
        return messages, {
            "compacted_messages_count": len(summarized_tool_indexes),
            "compacted_tool_results_count": len(summarized_tool_indexes),
            "estimated_tokens_saved": estimated_saved,
        }

    def _select_full_tool_indexes(self, tool_indexes: list[int], keep_full: int) -> set[int]:
        selected: list[int] = []
        selected_refs: set[str] = set()
        for index in reversed(tool_indexes):
            if len(selected) >= keep_full:
                break
            entry = self.entries[index]
            ref = _tool_entry_reference(entry)
            if ref and ref in selected_refs:
                continue
            if not self._should_send_full_tool_result(index, entry):
                continue
            selected.append(index)
            if ref:
                selected_refs.add(ref)
        return set(reversed(selected))

    def _should_send_full_tool_result(self, index: int, entry: dict[str, Any]) -> bool:
        tool_name = str(entry.get("tool") or "")
        result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
        if not tool_name or not result:
            return False
        if result.get("compacted") or result.get("duplicate_context_result") or result.get("duplicate_policy_feedback"):
            return False

        validation = result.get("validation")
        repair_message = str(entry.get("repair_message") or "")
        immediate_failure = (
            result.get("ok") is False
            or result.get("edit_policy_feedback")
            or repair_message
            or (isinstance(validation, dict) and validation.get("ok") is False)
        )
        if immediate_failure:
            return True

        sent_count = self._full_send_counts.get(index, 0)
        full_chars = _tool_result_full_chars(tool_name, result)
        if tool_name == "repo_map":
            if sent_count >= 1:
                return False
            return not any(
                previous.get("kind") == "tool" and previous.get("tool") == "repo_map"
                for previous in self.entries[:index]
            ) and full_chars <= MAX_FULL_TOOL_RESULT_CHARS
        if tool_name == "read_file":
            if sent_count >= 1 and full_chars >= LARGE_READ_FILE_FULL_ONCE_CHARS:
                return False
            path = _tool_entry_path(entry)
            content_hash = _tool_entry_content_hash(entry)
            if path and any(
                _tool_entry_path(previous) == path
                and _tool_entry_content_hash(previous) == content_hash
                and previous.get("kind") == "tool"
                and previous.get("tool") == "read_file"
                for previous in self.entries[:index]
            ):
                return False
            return full_chars <= MAX_FULL_TOOL_RESULT_CHARS or sent_count == 0
        if tool_name == "search_files":
            if full_chars > MAX_FULL_TOOL_RESULT_CHARS:
                return False
            return sent_count < 1 or full_chars < LARGE_READ_FILE_FULL_ONCE_CHARS
        if tool_name == "apply_patch" and full_chars > MAX_FULL_TOOL_RESULT_CHARS:
            return False
        return full_chars <= MAX_FULL_TOOL_RESULT_CHARS or sent_count == 0

    def _full_memory_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for index, entry in enumerate(self.entries):
            kind = entry.get("kind")
            if kind == "tool":
                tool_name = str(entry.get("tool") or "")
                result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
                if tool_name and result:
                    messages.append(tool_result_message(tool_name, result))
                repair_message = str(entry.get("repair_message") or "")
                if repair_message:
                    messages.append({"role": "user", "content": repair_message})
            elif kind == "invalid" and index == len(self.entries) - 1:
                message = entry.get("message")
                if isinstance(message, dict):
                    messages.append(message)
        return messages


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
        context_tool_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        file_revisions: dict[str, int] = {}
        workspace_revision = 0
        policy_feedback_signatures: set[str] = set()
        previous_input_tokens: int | None = None
        execution_memory = ExecutionMemory()

        _emit(
            event_sink,
            "agent_started",
            message=f"Started workspace agent with up to {max_steps} steps.",
            max_steps=max_steps,
            workspace=str(toolbox.root),
            allow_shell_tools=toolbox.allow_shell,
        )

        for step_number in range(1, max_steps + 1):
            step_messages, context_usage = execution_memory.build_prompt_messages(
                messages,
                request,
                self.router,
                trace,
                reasoning_state,
                previous_input_tokens=previous_input_tokens,
            )
            self._latest_context_usage = context_usage
            previous_input_tokens = context_usage["input_tokens"]
            _emit(
                event_sink,
                "context_usage_updated",
                message=_context_usage_message(context_usage),
                step=step_number,
                **context_usage,
            )
            if context_usage.get("hard_budget_exceeded"):
                budget_tokens = context_usage.get("budget_tokens")
                input_tokens = context_usage.get("input_tokens")
                text = (
                    "Agent stopped before the next model call because the compacted prompt "
                    f"still exceeded the configured context budget ({input_tokens}/{budget_tokens} "
                    "estimated input tokens). Narrow the request, increase "
                    "agent_context_budget_tokens, or re-run with a more specific file range."
                )
                _emit(
                    event_sink,
                    "agent_stopped",
                    message="Agent stopped because the compacted prompt exceeded the context budget.",
                    step=step_number,
                    input_tokens=input_tokens,
                    budget_tokens=budget_tokens,
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
            _emit(
                event_sink,
                "model_request",
                message=f"Step {step_number}: planning the next workspace action.",
                step=step_number,
            )
            step_request = replace(
                request,
                messages=step_messages,
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
                    failover=[event.to_dict() for event in response.failover],
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
                failover=[event.to_dict() for event in response.failover],
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
                    step_messages,
                    reasoning_state,
                )
                if result is None:
                    cache_key = _context_tool_cache_key(
                        toolbox,
                        tool_name,
                        args,
                        workspace_revision=workspace_revision,
                        file_revisions=file_revisions,
                    )
                    cached_result = context_tool_cache.get(cache_key) if cache_key is not None else None
                    if cached_result is not None and not _context_tool_cache_bypass(args):
                        result = _duplicate_context_tool_result(tool_name, cached_result)
                    else:
                        result = toolbox.run(tool_name, args)
                        if cache_key is not None and result.get("ok") is not False:
                            context_tool_cache[cache_key] = deepcopy(result)
                else:
                    signature = _policy_feedback_signature(tool_name, result)
                    if signature in policy_feedback_signatures:
                        result = _duplicate_policy_feedback_result(tool_name, result)
                    else:
                        policy_feedback_signatures.add(signature)
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
                    _emit_context_telemetry(
                        event_sink,
                        request,
                        self.config,
                        result,
                        reasoning_state,
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
                    execution_memory.record_tool_result(
                        step=step_number,
                        agent=response.agent,
                        provider=response.provider,
                        model=response.model,
                        tool=tool_name,
                        args=args,
                        result=result,
                    )
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
                    workspace_revision += 1
                    for changed_file in changed_files:
                        clean_changed_file = _normalize_policy_path(changed_file)
                        if clean_changed_file:
                            file_revisions[clean_changed_file] = file_revisions.get(clean_changed_file, 0) + 1
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
                _emit_context_telemetry(
                    event_sink,
                    request,
                    self.config,
                    result,
                    reasoning_state,
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
                    execution_memory.record_tool_result(
                        step=step_number,
                        agent=response.agent,
                        provider=response.provider,
                        model=response.model,
                        tool=tool_name,
                        args=args,
                        result=result,
                        repair_message=repair_message,
                    )
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
                execution_memory.record_tool_result(
                    step=step_number,
                    agent=response.agent,
                    provider=response.provider,
                    model=response.model,
                    tool=tool_name,
                    args=args,
                    result=result,
                )
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
                execution_memory.record_invalid_response(
                    step=step_number,
                    agent=response.agent,
                    provider=response.provider,
                    model=response.model,
                    response_text=response.text,
                    command=command,
                )
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
        context_state = request.metadata.get("context_state") if isinstance(request.metadata, dict) else None
        protected_context = context_state_messages(context_state if isinstance(context_state, dict) else {})
        return [
            {"role": "system", "content": f"{toolbox.instructions()}\n\n{_compact_reasoning_state_prompt(reasoning_state)}"},
            *protected_context,
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
        compact_history = _compact_session_history_messages(history, request.messages)
        if not compact_history:
            return request
        if _is_prefix(compact_history, request.messages):
            return request
        if _is_prefix(request.messages, compact_history):
            return replace(request, messages=list(compact_history))
        return replace(request, messages=[*compact_history, *request.messages])

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
        raw = dict(response.raw) if response and isinstance(response.raw, dict) else {}
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
            "context_usage": getattr(self, "_latest_context_usage", {}),
            "token_budget": getattr(self, "_latest_context_usage", {}).get("token_budget", {}),
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
        context_score=state.context_score,
        grouped_patch_required=state.grouped_patch_required,
        repository_inspection_complete=state.repository_inspection_complete,
        repository_graph_nodes=len(_repository_graph_nodes(state)),
        repository_graph_edges=len(state.dependency_edges),
        planned_edits_count=len(state.planned_edits),
        validation_history_count=len(state.validation_history),
        repair_history_count=len(state.repair_history),
        active_execution_node=state.execution_plan.active_node,
    )


def _emit_context_telemetry(
    event_sink: AgentEventSink | None,
    request: HubRequest,
    config: HubConfig,
    result: dict[str, Any],
    state: WorkspaceReasoningState,
) -> None:
    policy = result.get("policy") if isinstance(result.get("policy"), dict) else {}
    affected_files = _string_list_like(result.get("affected_files"))
    if not affected_files:
        affected_files = _changed_files_from_result(str(result.get("tool") or ""), result)
    recommended_tools = _string_list_like(policy.get("recommended_tools"))
    threshold = policy.get("threshold")
    if not isinstance(threshold, int):
        threshold = _context_score_threshold(_request_context_change_bar_mode(request, config))
    score = _context_score(state)
    _emit(
        event_sink,
        "context_score_updated",
        message=f"Repository context score is {score}.",
        score=score,
        threshold=threshold,
        affected_files=affected_files,
        recommended_tools=recommended_tools,
    )
    if result.get("context_change_bar_feedback"):
        _emit(
            event_sink,
            "context_bar_blocked",
            message="Context change bar blocked an edit before sufficient repository inspection.",
            score=score,
            threshold=threshold,
            affected_files=affected_files,
            recommended_tools=recommended_tools or ["repo_map", "search_files", "read_file"],
        )
        _emit(
            event_sink,
            "repository_inspection_required",
            message="Repository inspection is required before editing.",
            score=score,
            threshold=threshold,
            affected_files=affected_files,
            recommended_tools=recommended_tools or ["repo_map", "search_files", "read_file"],
        )
    if result.get("grouped_patch_required"):
        _emit(
            event_sink,
            "grouped_patch_required",
            message="Grouped apply_patch is required for this workspace change.",
            score=score,
            threshold=threshold,
            affected_files=affected_files,
            recommended_tools=["apply_patch"],
        )
    if result.get("reviewer_rejected_unread_edit"):
        _emit(
            event_sink,
            "reviewer_rejected_unread_edit",
            message="Reviewer rejected an edit against unread file(s).",
            score=score,
            threshold=threshold,
            affected_files=affected_files,
            recommended_tools=recommended_tools or ["read_file"],
        )
    graph_nodes = _repository_graph_nodes(state)
    if graph_nodes or state.dependency_edges:
        _emit(
            event_sink,
            "repository_graph_updated",
            message="Repository graph updated.",
            graph_node_count=len(graph_nodes),
            graph_edge_count=len(state.dependency_edges),
            impacted_files=_dedupe_strings(
                [path for files in state.impacted_files.values() for path in files]
            )[:30],
            context_score=score,
        )
    for edge in state.dependency_edges[-5:]:
        _emit(
            event_sink,
            "related_file_detected",
            message="Related file relationship detected.",
            source_file=edge.get("source", ""),
            related_file=edge.get("target", ""),
            relation_type=edge.get("relation", ""),
            impacted_files=state.impacted_files_for(str(edge.get("source") or ""))[:20],
            context_score=score,
        )
    policy_missing = " ".join(_string_list_like(policy.get("missing_context")))
    if "unread_dependency" in policy_missing or "unread_related_test" in policy_missing:
        _emit(
            event_sink,
            "unread_dependency_blocked",
            message="Repository graph blocked an edit with unread related files.",
            score=score,
            threshold=threshold,
            affected_files=affected_files,
            impacted_files=_string_list_like(policy.get("impacted_files")),
            recommended_tools=recommended_tools or ["read_file"],
        )
    if result.get("reviewer_rejection_reasons"):
        _emit(
            event_sink,
            "reviewer_rejected_patch",
            message="Reviewer rejected patch strategy or repository coverage.",
            score=score,
            threshold=threshold,
            affected_files=affected_files,
            impacted_files=_string_list_like(policy.get("impacted_files")),
            rejection_reasons=_string_list_like(result.get("reviewer_rejection_reasons")),
            recommended_tools=recommended_tools or ["read_file", "apply_patch"],
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
        "related_files": node.related_files,
        "impacted_files": node.impacted_files,
        "repository_dependencies": node.repository_dependencies,
        "inspection_requirements": node.inspection_requirements,
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
        targets.extend(state.related_tests.get(path, []))
        targets.extend(state.impacted_files_for(path))
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
    known = _known_repository_files(state)
    sources = {_normalize_policy_path(path) for path in files}
    for path in files:
        dependency_files.extend(state.dependency_map.get(path, []))
        dependency_files.extend(_graph_related_repository_files(state, path))
        dependent_files.extend(state.impacted_files_for(path))
    summary = state.repository_summary
    reverse = summary.get("reverse_dependency_map") if isinstance(summary, dict) else None
    if isinstance(reverse, dict):
        for path in files:
            values = reverse.get(path)
            if isinstance(values, list):
                dependent_files.extend(str(value) for value in values if isinstance(value, str))
    return {
        "dependency_files": [
            path
            for path in _repository_file_paths(dependency_files, known_files=known)
            if path not in sources
        ][:30],
        "dependent_files": [
            path
            for path in _repository_file_paths(dependent_files, known_files=known)
            if path not in sources
        ][:30],
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


def _string_list_like(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _context_tools_used(
    trace: list[dict[str, Any]],
    reasoning_state: WorkspaceReasoningState | None,
) -> list[str]:
    tools: list[str] = []
    if reasoning_state is not None:
        summary = reasoning_state.repository_summary
        if isinstance(summary, dict):
            tools.extend(_string_list_like(summary.get("context_tools")))
    for step in trace:
        tool = str(step.get("tool") or "")
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        if tool in CONTEXT_TOOLS and result.get("ok") is not False:
            tools.append(tool)
    return _dedupe_strings(tools)


def _read_files_used(
    trace: list[dict[str, Any]],
    reasoning_state: WorkspaceReasoningState | None,
) -> list[str]:
    files: list[str] = []
    if reasoning_state is not None:
        summary = reasoning_state.repository_summary
        if isinstance(summary, dict):
            files.extend(_string_list_like(summary.get("read_files")))
    for step in trace:
        if str(step.get("tool") or "") != "read_file":
            continue
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        if result.get("ok") is not False and isinstance(payload.get("path"), str):
            files.append(payload["path"])
    return _dedupe_strings([_normalize_policy_path(path) for path in files if path])


def _existing_affected_files(toolbox: AgentToolbox, affected_files: list[str]) -> list[str]:
    existing: list[str] = []
    for path in affected_files:
        target = _policy_resolved_path(toolbox, path)
        if target is None or not target.exists() or not target.is_file():
            continue
        existing.append(toolbox._relative(target))
    return _dedupe_strings(existing)


def _repository_graph_nodes(reasoning_state: WorkspaceReasoningState) -> list[str]:
    known = _strong_known_repository_files(reasoning_state)
    return _repository_file_paths(_raw_repository_graph_nodes(reasoning_state), known_files=known)[:200]


def _known_repository_files(reasoning_state: WorkspaceReasoningState) -> set[str]:
    known = _strong_known_repository_files(reasoning_state)
    graph_files = _repository_file_paths(_raw_repository_graph_nodes(reasoning_state), known_files=known)
    return set(graph_files) | known


def _raw_repository_graph_nodes(reasoning_state: WorkspaceReasoningState) -> list[str]:
    nodes: list[str] = []
    nodes.extend(reasoning_state.inspected_files)
    nodes.extend(reasoning_state.active_files)
    nodes.extend(reasoning_state.repository_summary_files())
    for edge in reasoning_state.dependency_edges:
        nodes.append(str(edge.get("source") or ""))
        nodes.append(str(edge.get("target") or ""))
    for mapping in (
        reasoning_state.related_files,
        reasoning_state.related_tests,
        reasoning_state.related_configs,
        reasoning_state.related_docs,
        reasoning_state.impacted_files,
        reasoning_state.dependency_map,
    ):
        for source, targets in mapping.items():
            nodes.append(source)
            nodes.extend(targets)
    return nodes


def _strong_known_repository_files(reasoning_state: WorkspaceReasoningState) -> set[str]:
    candidates: list[str] = []
    candidates.extend(reasoning_state.inspected_files)
    candidates.extend(reasoning_state.active_files)
    candidates.extend(reasoning_state.repository_summary_files())
    candidates.extend(_read_files_used([], reasoning_state))
    candidates.extend(reasoning_state.dependency_map.keys())
    for dependencies in reasoning_state.dependency_map.values():
        candidates.extend(dependencies)
    summary = reasoning_state.repository_summary
    if isinstance(summary, dict):
        for key in ("symbol_index", "reverse_dependency_map"):
            value = summary.get(key)
            if isinstance(value, dict):
                candidates.extend(str(path) for path in value.keys())
                for targets in value.values():
                    if isinstance(targets, list):
                        candidates.extend(str(path) for path in targets if isinstance(path, str))
    for node in reasoning_state.execution_plan.nodes:
        candidates.extend(node.affected_files)
        candidates.extend(node.related_files)
        candidates.extend(node.impacted_files)
        candidates.extend(node.repository_dependencies)
        candidates.extend(node.validation_targets)
    return {
        clean
        for clean in (_normalize_policy_path(path) for path in candidates if path)
        if clean and not _is_internal_runtime_policy_path(clean)
    }


def _repository_file_paths(paths: list[str], *, known_files: set[str]) -> list[str]:
    return _dedupe_strings(
        [
            clean
            for path in paths
            if (clean := _normalize_policy_path(path))
            and _is_repository_file_path(clean, known_files=known_files)
        ]
    )


def _is_repository_file_path(path: str, *, known_files: set[str]) -> bool:
    clean = _normalize_policy_path(path)
    if not clean or clean in {".", ".."} or _is_internal_runtime_policy_path(clean):
        return False
    if clean in known_files:
        return True
    name = clean.rsplit("/", 1)[-1]
    if _has_repository_file_extension(name):
        return True
    return "/" not in clean and name.lower() in REPOSITORY_ROOT_FILE_NAMES


def _has_repository_file_extension(name: str) -> bool:
    lowered = name.lower()
    if "." not in lowered.strip("."):
        return False
    suffixes = Path(lowered).suffixes
    return any(suffix in REPOSITORY_FILE_EXTENSIONS for suffix in suffixes)


def _is_internal_runtime_policy_path(path: str) -> bool:
    clean = _normalize_policy_path(path).lower()
    if clean.startswith(".agent-hub/") or clean == ".agent-hub":
        return True
    if clean in {"state", "state/provider_health.json"}:
        return True
    return clean.startswith(("state/sessions/", "state/workspace-checkpoints/"))


def _graph_related_repository_files(
    reasoning_state: WorkspaceReasoningState,
    path: str,
) -> list[str]:
    clean = _normalize_policy_path(path)
    if not clean:
        return []
    known = _known_repository_files(reasoning_state)
    related = [
        *reasoning_state.related_files_for(clean),
        *reasoning_state.impacted_files_for(clean),
    ]
    return [
        related_path
        for related_path in _repository_file_paths(related, known_files=known)
        if related_path != clean
    ]


def _related_tests_for_files(reasoning_state: WorkspaceReasoningState, files: list[str]) -> list[str]:
    related: list[str] = []
    for path in files:
        clean = _normalize_policy_path(path)
        related.extend(reasoning_state.related_tests.get(clean, []))
        related.extend(
            target
            for target in reasoning_state.related_files_for(clean)
            if _is_test_context_file(target)
        )
    return _dedupe_strings([_normalize_policy_path(path) for path in related if path])


def _related_configs_for_files(reasoning_state: WorkspaceReasoningState, files: list[str]) -> list[str]:
    related: list[str] = []
    for path in files:
        clean = _normalize_policy_path(path)
        related.extend(reasoning_state.related_configs.get(clean, []))
        related.extend(
            target
            for target in reasoning_state.related_files_for(clean)
            if _is_config_context_file(target)
        )
    return _dedupe_strings([_normalize_policy_path(path) for path in related if path])


def _related_dependencies_for_files(reasoning_state: WorkspaceReasoningState, files: list[str]) -> list[str]:
    related: list[str] = []
    known = _known_repository_files(reasoning_state)
    for path in files:
        clean = _normalize_policy_path(path)
        related.extend(reasoning_state.dependency_map.get(clean, []))
        for edge in reasoning_state.dependency_edges:
            if edge.get("relation") != "imports":
                continue
            source = _normalize_policy_path(str(edge.get("source") or ""))
            target = _normalize_policy_path(str(edge.get("target") or ""))
            if source == clean:
                related.append(target)
            elif target == clean:
                related.append(source)
    sources = {_normalize_policy_path(path) for path in files}
    return [
        path
        for path in _repository_file_paths(related, known_files=known)
        if path not in sources
    ]


def _impacted_files_for_files(reasoning_state: WorkspaceReasoningState, files: list[str]) -> list[str]:
    impacted: list[str] = []
    known = _known_repository_files(reasoning_state)
    for path in files:
        impacted.extend(reasoning_state.impacted_files_for(path))
    sources = {_normalize_policy_path(path) for path in files}
    return [
        path
        for path in _repository_file_paths(impacted, known_files=known)
        if path not in sources
    ]


def _hallucinated_edit_files(
    toolbox: AgentToolbox,
    tool_name: str,
    args: dict[str, Any],
    affected_files: list[str],
    reasoning_state: WorkspaceReasoningState,
) -> list[str]:
    known = _known_repository_files(reasoning_state)
    hallucinated: list[str] = []
    for path in affected_files:
        clean = _normalize_policy_path(path)
        target = _policy_resolved_path(toolbox, clean)
        exists = bool(target and target.exists())
        if exists:
            if known and clean not in known:
                hallucinated.append(clean)
            continue
        if _is_intentional_new_file(tool_name, args, clean):
            continue
        hallucinated.append(clean)
    return _dedupe_strings(hallucinated)


def _is_intentional_new_file(tool_name: str, args: dict[str, Any], path: str) -> bool:
    if tool_name == "write_file":
        return bool(args.get("content")) and not bool(args.get("append", False))
    if tool_name != "apply_patch":
        return False
    changes = args.get("changes")
    if isinstance(changes, list):
        for item in changes:
            if not isinstance(item, dict) or _normalize_policy_path(str(item.get("path") or "")) != path:
                continue
            return isinstance(item.get("content"), str) and "old" not in item
    patch = args.get("patch")
    return isinstance(patch, str) and f"+++ b/{path}" in patch and "--- /dev/null" in patch


def _is_test_context_file(path: str) -> bool:
    lowered = _normalize_policy_path(path).lower()
    name = lowered.rsplit("/", 1)[-1]
    return "/test" in lowered or name.startswith("test_") or name.endswith("_test.py")


def _is_config_context_file(path: str) -> bool:
    lowered = _normalize_policy_path(path).lower()
    name = lowered.rsplit("/", 1)[-1]
    return name in {
        "package.json",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "tox.ini",
        "tsconfig.json",
        "agent-hub.config.json",
    } or lowered.endswith((".json", ".toml", ".yaml", ".yml", ".ini", ".cfg"))


def _has_graph_related_files(reasoning_state: WorkspaceReasoningState, files: list[str]) -> bool:
    return any(_graph_related_repository_files(reasoning_state, path) for path in files)


def _fragmented_write_chain_active(
    trace: list[dict[str, Any]],
    affected_files: list[str],
    reasoning_state: WorkspaceReasoningState,
) -> bool:
    prior_write_files: list[str] = []
    for step in trace:
        if str(step.get("tool") or "") != "write_file":
            continue
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        prior_write_files.extend(_changed_files_from_result("write_file", result))
        prior_write_files.extend(_string_list_like(result.get("affected_files")))
    if not prior_write_files:
        return False
    for path in affected_files:
        related = set(_graph_related_repository_files(reasoning_state, path))
        if related & set(prior_write_files):
            return True
    return False


def _has_related_context_read(
    read_files: list[str],
    existing_targets: list[str],
    reasoning_state: WorkspaceReasoningState,
) -> bool:
    read_set = {_normalize_policy_path(path) for path in read_files}
    target_set = {_normalize_policy_path(path) for path in existing_targets}
    if len(target_set) > 1 and target_set.issubset(read_set):
        return True
    if any(_is_context_support_file(path) and path not in target_set for path in read_set):
        return True
    related: set[str] = set()
    for files in reasoning_state.related_files.values():
        related.update(_normalize_policy_path(path) for path in _string_list_like(files))
    summary = reasoning_state.repository_summary
    if isinstance(summary, dict):
        for key in ("key_files", "validation_targets", "searched_files"):
            related.update(_normalize_policy_path(path) for path in _string_list_like(summary.get(key)))
    return bool((read_set & related) - target_set)


def _has_impl_and_support_files(files: list[str]) -> bool:
    clean = [_normalize_policy_path(path) for path in files if path]
    return any(_is_context_support_file(path) for path in clean) and any(
        not _is_context_support_file(path) for path in clean
    )


def _reviewer_requested_fixes(request: HubRequest, messages: list[dict[str, Any]]) -> bool:
    if _team_role(request) == "fixer":
        return True
    text = " ".join(_message_texts(messages[-6:])).lower()
    return any(
        phrase in text
        for phrase in (
            "review feedback",
            "required fixes",
            "blocking issue",
            "reviewer requested",
            "fix the review",
        )
    )


def _message_texts(messages: list[dict[str, Any]]) -> list[str]:
    return [
        str(message.get("content"))
        for message in messages
        if isinstance(message, dict) and isinstance(message.get("content"), str)
    ]


def _recent_policy_message_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "system":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        if content.startswith("Tool result for "):
            continue
        if content.startswith("EXECUTION MEMORY SUMMARY"):
            continue
        parts.append(_message_task_section(content))
    return " ".join(parts)


def _execution_plan_files(reasoning_state: WorkspaceReasoningState) -> list[str]:
    files: list[str] = []
    for node in reasoning_state.execution_plan.nodes:
        if node.id.endswith("-inspect"):
            continue
        files.extend(node.affected_files)
    for edit in reasoning_state.planned_edits:
        value = edit.get("files")
        if isinstance(value, list):
            files.extend(str(path) for path in value if isinstance(path, str))
    return _dedupe_strings([_normalize_policy_path(path) for path in files if path])


def _execution_plan_validation_targets(reasoning_state: WorkspaceReasoningState) -> list[str]:
    files: list[str] = []
    for node in reasoning_state.execution_plan.nodes:
        if node.id.endswith("-inspect"):
            continue
        files.extend(node.validation_targets)
    for validation in reasoning_state.validation_history:
        value = validation.get("validation_targets")
        if isinstance(value, list):
            files.extend(str(path) for path in value if isinstance(path, str))
    return _dedupe_strings([_normalize_policy_path(path) for path in files if path])


def _team_role(request: HubRequest) -> str:
    raw = request.raw if isinstance(request.raw, dict) else {}
    role = raw.get("team_agent_role")
    if not role and isinstance(raw.get("agent_hub"), dict):
        role = raw["agent_hub"].get("role")
    return str(role or "").strip().lower()


def _path_like_tokens(text: str) -> list[str]:
    tokens = re.findall(
        r"(?<![\w.-])(?:[\w.-]+[\\/])*[\w.-]+\.[A-Za-z0-9]{1,10}(?![\w.-])",
        text,
    )
    return _dedupe_strings([_normalize_policy_path(token) for token in tokens])


def _normalize_policy_path(path: str) -> str:
    value = str(path or "").replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    return value


def _is_context_support_file(path: str) -> bool:
    lowered = _normalize_policy_path(path).lower()
    name = lowered.rsplit("/", 1)[-1]
    if "/test" in lowered or name.startswith("test_") or name.endswith("_test.py"):
        return True
    if name in {
        "package.json",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "tox.ini",
        "tsconfig.json",
        "agent-hub.config.json",
        "readme.md",
    }:
        return True
    return lowered.endswith((".md", ".rst", ".txt", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg"))


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
    raw = dict(request.raw) if isinstance(request.raw, dict) else {}
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
            "reasoning_state": _compact_reasoning_state_payload(reasoning_state),
            "reasoning_state_compacted": True,
            "execution_plan": _compact_execution_plan(reasoning_state.execution_plan.to_dict()),
            "active_execution_node": _active_execution_metadata(reasoning_state),
            "context_change_bar": _context_change_bar_state(
                request,
                toolbox.config,
                trace,
                reasoning_state,
            ),
        }
    )
    raw["agent_hub_runtime"] = runtime
    return raw


def _execution_memory_summary(
    entries: list[dict[str, Any]],
    *,
    summarized_tool_indexes: list[int],
    reasoning_state: WorkspaceReasoningState,
    trace: list[dict[str, Any]],
) -> str:
    state = reasoning_state.to_dict()
    repository_summary = (
        state.get("repository_summary")
        if isinstance(state.get("repository_summary"), dict)
        else {}
    )
    older_tool_summaries = [
        _tool_memory_summary(entries[index])
        for index in summarized_tool_indexes[-MAX_MEMORY_SUMMARY_TOOL_RESULTS:]
        if 0 <= index < len(entries)
    ]
    omitted = max(0, len(summarized_tool_indexes) - len(older_tool_summaries))
    summary: dict[str, Any] = {
        "purpose": "compact execution memory; use with the latest full tool results below",
        "tool_result_count": sum(1 for entry in entries if entry.get("kind") == "tool"),
        "summarized_tool_result_count": len(summarized_tool_indexes),
        "omitted_older_tool_result_count": omitted,
        "current_objective": _active_execution_objective(reasoning_state),
        "changed_files": _changed_files_from_trace(trace)[-20:],
        "inspected_files": _string_list_like(state.get("inspected_files"))[-30:],
        "read_files": _string_list_like(repository_summary.get("read_files"))[-30:],
        "context_tools": _string_list_like(repository_summary.get("context_tools"))[-20:],
        "reasoning_state_counts": _reasoning_state_counts(state),
        "older_tool_results": older_tool_summaries,
    }
    latest_failure = _latest_memory_failure(entries, trace)
    if latest_failure:
        summary["latest_failure"] = latest_failure
    latest_invalid = _latest_invalid_summary(entries)
    if latest_invalid:
        summary["latest_invalid_response"] = latest_invalid
    return (
        "EXECUTION MEMORY SUMMARY (ephemeral, compacted):\n"
        f"{json.dumps(summary, indent=2, ensure_ascii=False)}\n\n"
        "Recent full tool results and immediate repair instructions follow when needed. "
        "Do not rely on omitted file contents; re-read with a specific range if fresh details are required."
    )


def _tool_memory_summary(entry: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(entry.get("tool") or "")
    args = entry.get("args") if isinstance(entry.get("args"), dict) else {}
    result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    reference = _tool_result_reference(tool_name, result, args)
    if result.get("edit_policy_feedback"):
        return {
            "step": entry.get("step"),
            "tool": tool_name,
            "ok": False,
            "args": _progress_tool_args(tool_name, args),
            "reference": reference,
            "policy_feedback": True,
            "duplicate_policy_feedback": bool(result.get("duplicate_policy_feedback")),
            "message": result.get("message"),
            "affected_files": result.get("affected_files", []),
            "recommended_tool": result.get("recommended_tool"),
        }
    compact_result = _compact_tool_result_for_history(
        tool_name,
        result,
        reason="execution_memory_summary",
    )
    summary: dict[str, Any] = {
        "step": entry.get("step"),
        "tool": tool_name,
        "ok": result.get("ok") is not False,
        "args": _progress_tool_args(tool_name, args),
        "reference": reference,
        "summary": compact_result.get("result", compact_result),
    }
    for key in (
        "error",
        "changed_files",
        "affected_files",
        "validation",
        "repair",
        "rollback",
        "edit_policy_feedback",
        "duplicate_policy_feedback",
        "duplicate_context_result",
    ):
        if key in compact_result:
            summary[key] = compact_result[key]
    repair_message = str(entry.get("repair_message") or "")
    if repair_message:
        summary["repair_note"] = _short_value(repair_message, maximum=1000)
    return summary


def _tool_result_reference(
    tool_name: str,
    result: dict[str, Any],
    args: dict[str, Any] | None = None,
) -> str:
    args = args if isinstance(args, dict) else {}
    payload = result.get("result") if isinstance(result.get("result"), dict) else {}
    if tool_name == "read_file":
        path = str(payload.get("path") or args.get("path") or "")
        start_line = payload.get("start_line") or args.get("start_line")
        end_line = payload.get("end_line")
        if end_line is None and start_line is not None and args.get("line_count") is not None:
            try:
                end_line = int(start_line) + int(args.get("line_count")) - 1
            except (TypeError, ValueError):
                end_line = None
        content = payload.get("content")
        digest = _content_hash(content) if isinstance(content, str) else ""
        line_text = f" lines {start_line}-{end_line}" if start_line and end_line else ""
        hash_text = f" hash {digest}" if digest else ""
        return f"read_file {path}{line_text}{hash_text} already inspected".strip()
    if tool_name == "repo_map":
        focus = str(payload.get("focus") or args.get("target") or args.get("path") or ".")
        related = _string_list_like(payload.get("related_files"))
        tests = _string_list_like(payload.get("test_files"))
        return f"repo_map {focus} related={len(related)} tests={len(tests)}"
    if tool_name == "search_files":
        query = str(payload.get("query") or args.get("query") or "")
        matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
        return f"search_files query={query!r} matches={len(matches)}"
    changed = _changed_files_from_result(tool_name, result)
    if changed:
        return f"{tool_name} changed {', '.join(changed[:8])}"
    return tool_name


def _tool_entry_reference(entry: dict[str, Any]) -> str:
    tool_name = str(entry.get("tool") or "")
    args = entry.get("args") if isinstance(entry.get("args"), dict) else {}
    result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    return _tool_result_reference(tool_name, result, args)


def _tool_entry_path(entry: dict[str, Any]) -> str:
    args = entry.get("args") if isinstance(entry.get("args"), dict) else {}
    result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    payload = result.get("result") if isinstance(result.get("result"), dict) else {}
    return _normalize_policy_path(str(payload.get("path") or args.get("path") or ""))


def _tool_entry_content_hash(entry: dict[str, Any]) -> str:
    result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    payload = result.get("result") if isinstance(result.get("result"), dict) else {}
    content = payload.get("content")
    if isinstance(content, str):
        return _content_hash(content)
    compact_hash = payload.get("content_hash")
    return str(compact_hash or "")


def _tool_result_full_chars(tool_name: str, result: dict[str, Any]) -> int:
    try:
        return len(tool_result_message(tool_name, result).get("content", ""))
    except Exception:
        return len(json.dumps(result, ensure_ascii=False, default=str))


def _latest_memory_failure(entries: list[dict[str, Any]], trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(entries):
        if entry.get("kind") != "tool":
            continue
        tool_name = str(entry.get("tool") or "")
        result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
        if result.get("edit_policy_feedback"):
            return {
                "step": entry.get("step"),
                "tool": tool_name,
                "type": "policy_feedback",
                "message": result.get("message"),
                "error": _short_value(result.get("error"), maximum=1000),
                "affected_files": result.get("affected_files", []),
                "recommended_tool": result.get("recommended_tool"),
            }
        if result.get("ok") is False:
            return {
                "step": entry.get("step"),
                "tool": tool_name,
                "type": "tool_failure",
                "error": _short_value(result.get("error"), maximum=1000),
                "affected_files": result.get("affected_files", []),
            }
        validation = result.get("validation")
        if isinstance(validation, dict) and validation.get("ok") is False:
            return {
                "step": entry.get("step"),
                "tool": tool_name,
                "type": "validation_failure",
                "validation": _compact_validation_result(validation),
                "repair": result.get("repair") if isinstance(result.get("repair"), dict) else None,
                "rollback": _rollback_summary(result.get("rollback")),
            }
    failed = _last_failed_validation(trace)
    if failed:
        return {"type": "validation_failure", **failed}
    return None


def _latest_invalid_summary(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(entries):
        if entry.get("kind") == "invalid":
            return {
                "step": entry.get("step"),
                "agent": entry.get("agent"),
                "response_text": entry.get("response_text", ""),
            }
    return None


def _reasoning_state_counts(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_score": state.get("context_score"),
        "dependency_edges": len(state.get("dependency_edges") or []),
        "dependency_map_entries": len(state.get("dependency_map") or {}),
        "related_files_entries": len(state.get("related_files") or {}),
        "validation_history": len(state.get("validation_history") or []),
        "repair_history": len(state.get("repair_history") or []),
        "approval_history": len(state.get("approval_history") or []),
    }


def _compact_reasoning_state_prompt(reasoning_state: WorkspaceReasoningState) -> str:
    return (
        "PERSISTENT WORKSPACE REASONING STATE (compact):\n"
        f"{json.dumps(_compact_reasoning_state_payload(reasoning_state), indent=2, ensure_ascii=False)}"
    )


def _compact_reasoning_state_payload(reasoning_state: WorkspaceReasoningState) -> dict[str, Any]:
    state = reasoning_state.to_dict()
    repository_summary = (
        state.get("repository_summary")
        if isinstance(state.get("repository_summary"), dict)
        else {}
    )
    plan = (
        state.get("execution_plan")
        if isinstance(state.get("execution_plan"), dict)
        else reasoning_state.execution_plan.to_dict()
    )
    compact_plan = _compact_execution_plan(plan)
    return {
        "task_id": state.get("task_id"),
        "objectives": _string_list_like(state.get("objectives"))[-5:],
        "context_score": state.get("context_score"),
        "active_files": _string_list_like(state.get("active_files"))[-20:],
        "inspected_files": _string_list_like(state.get("inspected_files"))[-30:],
        "grouped_patch_required": bool(state.get("grouped_patch_required")),
        "repository_inspection_complete": bool(state.get("repository_inspection_complete")),
        "repository_summary": _compact_repository_summary(repository_summary),
        "dependency_edges_count": len(state.get("dependency_edges") or []),
        "dependency_map_count": len(state.get("dependency_map") or {}),
        "related_files_count": len(state.get("related_files") or {}),
        "planned_edits": _compact_dict_list(state.get("planned_edits"), limit=5, maximum=500),
        "planned_validations": _string_list_like(state.get("planned_validations"))[-10:],
        "validation_history": _compact_dict_list(state.get("validation_history"), limit=5, maximum=1200),
        "repair_history": _compact_dict_list(state.get("repair_history"), limit=5, maximum=1000),
        "approval_history": _compact_dict_list(state.get("approval_history"), limit=5, maximum=1000),
        "execution_plan": compact_plan,
    }


def _compact_execution_plan(plan: dict[str, Any]) -> dict[str, Any]:
    nodes = plan.get("nodes") if isinstance(plan.get("nodes"), list) else []
    compact_nodes: list[dict[str, Any]] = []
    for node in nodes[-8:]:
        if not isinstance(node, dict):
            continue
        compact_nodes.append(
            {
                "id": node.get("id"),
                "objective": _short_value(node.get("objective"), maximum=240),
                "status": node.get("status"),
                "affected_files": _string_list_like(node.get("affected_files"))[-10:],
                "related_files_count": len(_string_list_like(node.get("related_files"))),
                "impacted_files_count": len(_string_list_like(node.get("impacted_files"))),
                "validation_targets": _string_list_like(node.get("validation_targets"))[-10:],
                "estimated_risk": node.get("estimated_risk"),
                "repair_strategy": _short_value(node.get("repair_strategy"), maximum=240)
                if node.get("repair_strategy")
                else None,
                "retry_count": node.get("retry_count"),
            }
        )
    return {
        "active_node": plan.get("active_node"),
        "nodes": compact_nodes,
        "node_count": len(nodes),
        "completed_nodes": _string_list_like(plan.get("completed_nodes"))[-20:],
        "failed_nodes": _string_list_like(plan.get("failed_nodes"))[-20:],
        "blocked_nodes": _string_list_like(plan.get("blocked_nodes"))[-20:],
    }


def _compact_repository_summary(summary: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (
        "known_files",
        "read_files",
        "searched_files",
        "context_tools",
        "validation_targets",
        "key_files",
        "test_files",
        "dependency_files",
        "related_files",
    ):
        values = _string_list_like(summary.get(key))
        if values:
            compact[key] = values[-30:]
            compact[f"{key}_count"] = len(values)
    for key in ("symbol_index", "dependency_map", "reverse_dependency_map"):
        value = summary.get(key)
        if isinstance(value, dict):
            compact[f"{key}_count"] = len(value)
    return compact


def _compact_dict_list(value: Any, *, limit: int, maximum: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in value[-limit:]:
        if not isinstance(item, dict):
            continue
        compact.append(_compact_dict_value(item, maximum=maximum))
    return compact


def _compact_dict_value(value: dict[str, Any], *, maximum: int) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, str):
            compact[key] = _short_value(item, maximum=maximum)
        elif isinstance(item, list):
            compact[key] = [
                _short_value(element, maximum=maximum // 2)
                if isinstance(element, str)
                else _compact_dict_value(element, maximum=max(120, maximum // 2))
                if isinstance(element, dict)
                else element
                for element in item[-10:]
            ]
            if len(item) > 10:
                compact[f"{key}_count"] = len(item)
        elif isinstance(item, dict):
            compact[key] = {
                str(inner_key): (
                    _short_value(inner_value, maximum=maximum // 2)
                    if isinstance(inner_value, str)
                    else inner_value
                )
                for inner_key, inner_value in list(item.items())[-10:]
            }
            if len(item) > 10:
                compact[f"{key}_count"] = len(item)
        else:
            compact[key] = item
    return compact


def _active_execution_objective(reasoning_state: WorkspaceReasoningState) -> str:
    try:
        active = reasoning_state.execution_plan.active()
    except Exception:
        active = None
    if active is not None:
        return _short_value(active.objective, maximum=300)
    objectives = list(reasoning_state.objectives or [])
    return _short_value(objectives[-1], maximum=300) if objectives else ""


def _prepare_agent_messages_for_step(
    messages: list[dict[str, Any]],
    request: HubRequest,
    router: AgentRouter,
    trace: list[dict[str, Any]],
    *,
    previous_input_tokens: int | None,
    pre_compacted_count: int = 0,
    pre_compacted_tool_results_count: int = 0,
    pre_estimated_tokens_saved: int = 0,
) -> dict[str, Any]:
    budget_info = _agent_context_input_budget_info(request, router, messages)
    budget_tokens = budget_info.effective_budget
    before_tokens = _estimated_message_tokens(messages)
    before_messages = deepcopy(messages)
    compaction_enabled = _agent_context_compaction_enabled(request, router.config)
    compacted_messages_count = pre_compacted_count
    compacted_tool_results_count = pre_compacted_tool_results_count
    budget_exceeded_before = budget_tokens is not None and before_tokens > budget_tokens
    if compaction_enabled:
        history_compacted_count = _compact_agent_message_history(
            messages,
            repair_active=_repair_context_active(trace, messages),
            budget_tokens=budget_tokens,
            context_mode=budget_info.mode,
        )
        compacted_messages_count += history_compacted_count
        compacted_tool_results_count += history_compacted_count
    input_tokens = _estimated_message_tokens(messages)
    diagnostics = request_context_diagnostics(
        request,
        messages=before_messages,
        compacted_messages=messages,
    )
    estimated_tokens_saved = pre_estimated_tokens_saved + max(0, before_tokens - input_tokens)
    tokens_added = 0 if previous_input_tokens is None else input_tokens - previous_input_tokens
    percent_used = (
        round((input_tokens / budget_tokens) * 100, 1)
        if budget_tokens is not None and budget_tokens > 0
        else None
    )
    hard_budget_exceeded = budget_tokens is not None and input_tokens > budget_tokens
    if hard_budget_exceeded:
        compaction_level = "hard_stop"
    elif budget_exceeded_before:
        compaction_level = "budget"
    elif compacted_tool_results_count > 0:
        compaction_level = "tool_results"
    elif compacted_messages_count > 0:
        compaction_level = "messages"
    else:
        compaction_level = "none"
    return {
        "input_tokens": input_tokens,
        "budget_tokens": budget_tokens,
        "context_mode": budget_info.mode,
        "token_budget": budget_info.to_dict(),
        "percent_used": percent_used,
        "tokens_added_since_last_step": tokens_added,
        "compaction_enabled": compaction_enabled,
        "compaction_triggered": compacted_messages_count > 0 or estimated_tokens_saved > 0,
        "compaction_level": compaction_level,
        "compacted_messages_count": compacted_messages_count,
        "compacted_tool_results_count": compacted_tool_results_count,
        "estimated_tokens_saved": estimated_tokens_saved,
        "largest_context_sources": _largest_context_sources(messages),
        "warning_level": _context_warning_level(percent_used),
        "budget_exceeded_before_compaction": budget_exceeded_before,
        "budget_exceeded_after_compaction": hard_budget_exceeded,
        "hard_budget_exceeded": hard_budget_exceeded,
        "input_tokens_before_compaction": before_tokens,
        "incoming_token_count": diagnostics["incoming_token_count"],
        "compacted_token_count": diagnostics["compacted_token_count"],
        "protected_token_count": diagnostics["protected_token_count"],
        "dropped_messages": diagnostics["dropped_messages"],
        "dropped_token_count": diagnostics["dropped_token_count"],
        "preserved_tool_calls": diagnostics["preserved_tool_calls"],
        "preserved_tool_results": diagnostics["preserved_tool_results"],
        "preserved_todo_count": diagnostics["preserved_todo_count"],
        "active_files_detected": diagnostics["active_files_detected"],
        "task_progress_present": diagnostics["task_progress_present"],
        "structured_content_messages": diagnostics["structured_content_messages"],
        "cline_compatibility_mode": diagnostics["cline_compatibility_mode"],
        "suspiciously_empty": diagnostics["suspiciously_empty"],
    }


def _agent_context_input_budget(
    request: HubRequest,
    router: AgentRouter,
    messages: list[dict[str, Any]],
) -> int | None:
    return _agent_context_input_budget_info(request, router, messages).effective_budget


def _agent_context_input_budget_info(
    request: HubRequest,
    router: AgentRouter,
    messages: list[dict[str, Any]],
):
    override = _request_positive_int_option(request, "agent_context_budget_tokens")
    if override is None:
        override = _request_positive_int_option(request, "context_budget_tokens")
    configured = getattr(router.config, "agent_context_budget_tokens", None)
    try:
        configured_budget = int(configured) if configured is not None else 0
    except (TypeError, ValueError):
        configured_budget = 0

    try:
        candidates = router._candidate_agents(replace(request, messages=messages))
    except Exception:
        candidates = []
    budgets: list[int] = []
    for agent in candidates:
        if agent.context_window is None:
            continue
        output_tokens = _agent_output_budget(request, agent)
        budgets.append(max(1, int(agent.context_window) - output_tokens))
    model_budget = min(budgets) if budgets else None
    manager = TokenBudgetManager.from_request(
        request,
        getattr(router.config, "context_mode", "balanced"),
    )
    if override is not None:
        effective = min(override, model_budget) if model_budget is not None else override
        return TokenBudget(
            mode=manager.mode,
            configured_budget=override,
            provider_budget=model_budget,
            effective_budget=effective,
        )
    return manager.effective_input_budget(
        configured_budget=configured_budget if configured_budget > 0 else None,
        provider_budget=model_budget,
    )


def _agent_context_compaction_enabled(request: HubRequest, config: HubConfig) -> bool:
    return _request_bool(
        request,
        "agent_context_compaction_enabled",
        getattr(config, "agent_context_compaction_enabled", True),
    )


def _agent_output_budget(request: HubRequest, agent: Any) -> int:
    value = request.max_tokens if request.max_tokens is not None else getattr(agent, "max_tokens", None)
    try:
        return max(0, int(value if value is not None else 0))
    except (TypeError, ValueError):
        return 0


def _compact_agent_message_history(
    messages: list[dict[str, Any]],
    *,
    repair_active: bool,
    budget_tokens: int | None,
    context_mode: str = "balanced",
) -> int:
    compacted = 0
    keep_full = TokenBudgetManager(context_mode).full_tool_history(repair_active=repair_active)
    tool_messages = _tool_result_messages(messages)
    for item in tool_messages[:-keep_full]:
        if _compact_tool_message(messages, item, reason="old_tool_result"):
            compacted += 1
    compacted += _remove_old_assistant_tool_messages(messages, keep_full=keep_full)

    if budget_tokens is None:
        return compacted
    budget = max(1, budget_tokens - CONTEXT_BUDGET_MARGIN_TOKENS)
    while _estimated_message_tokens(messages) > budget:
        if not _compact_largest_tool_message(messages, protect_recent=keep_full):
            if not _compact_system_message(messages):
                if not _compact_largest_tool_message(messages, protect_recent=0):
                    break
        compacted += 1
    compacted += _remove_old_assistant_tool_messages(messages, keep_full=keep_full)
    return compacted


def _context_usage_message(context_usage: dict[str, Any]) -> str:
    input_tokens = int(context_usage.get("input_tokens") or 0)
    budget_tokens = context_usage.get("budget_tokens")
    percent_used = context_usage.get("percent_used")
    delta = int(context_usage.get("tokens_added_since_last_step") or 0)
    compacted = int(context_usage.get("compacted_messages_count") or 0)
    if isinstance(budget_tokens, int) and budget_tokens > 0:
        budget_text = f"{input_tokens}/{budget_tokens} tokens"
        percent_text = f"{percent_used}% used" if percent_used is not None else "budgeted"
    else:
        budget_text = f"{input_tokens} tokens"
        percent_text = "no budget"
    delta_text = f"+{delta}" if delta >= 0 else str(delta)
    level = str(context_usage.get("compaction_level") or "none")
    warning = str(context_usage.get("warning_level") or "normal")
    if compacted:
        return (
            f"Context {percent_text} ({budget_text}, {delta_text} since last step; "
            f"compacted {compacted}; level {level}; {warning})."
        )
    return f"Context {percent_text} ({budget_text}, {delta_text} since last step)."


def _tool_result_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        tool_result = _parse_tool_result_message(content)
        if tool_result is None:
            continue
        parsed.append({"index": index, **tool_result, "content_chars": len(content)})
    return parsed


def _remove_old_assistant_tool_messages(messages: list[dict[str, Any]], *, keep_full: int) -> int:
    removed = 0
    tool_messages = _tool_result_messages(messages)
    for item in reversed(tool_messages[:-keep_full]):
        index = item.get("index")
        if not isinstance(index, int) or index <= 0 or index > len(messages) - 1:
            continue
        previous = messages[index - 1]
        if not _assistant_tool_call_message(previous):
            continue
        del messages[index - 1]
        removed += 1
    return removed


def _assistant_tool_call_message(message: dict[str, Any]) -> bool:
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return False
    content = message.get("content")
    if not isinstance(content, str):
        return False
    text = content.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("action") in TOOL_ACTIONS | {"tool"}


def _parse_tool_result_message(content: str) -> dict[str, Any] | None:
    if not content.startswith("Tool result for "):
        return None
    header, separator, rest = content.partition(":\n")
    if not separator:
        return None
    tool_name = header.removeprefix("Tool result for ").strip()
    json_text = rest.split("\n\nContinue with", 1)[0].strip()
    if not tool_name or not json_text:
        return None
    try:
        result = json.loads(json_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(result, dict):
        return None
    return {"tool": tool_name, "result": result}


def _compact_tool_message(messages: list[dict[str, Any]], item: dict[str, Any], *, reason: str) -> bool:
    result = item.get("result")
    if not isinstance(result, dict) or result.get("compacted"):
        return False
    index = item.get("index")
    if not isinstance(index, int) or index < 0 or index >= len(messages):
        return False
    tool_name = str(item.get("tool") or result.get("tool") or "")
    if not tool_name:
        return False
    messages[index] = tool_result_message(
        tool_name,
        _compact_tool_result_for_history(tool_name, result, reason=reason),
    )
    return True


def _compact_largest_tool_message(messages: list[dict[str, Any]], *, protect_recent: int = 0) -> bool:
    tool_messages = _tool_result_messages(messages)
    protected_indexes = {
        int(item["index"])
        for item in tool_messages[-protect_recent:]
        if isinstance(item.get("index"), int)
    } if protect_recent > 0 else set()
    candidates = [
        item
        for item in tool_messages
        if isinstance(item.get("result"), dict)
        and not item["result"].get("compacted")
        and item.get("index") not in protected_indexes
    ]
    if not candidates:
        return False
    largest = max(candidates, key=lambda item: int(item.get("content_chars") or 0))
    return _compact_tool_message(messages, largest, reason="context_budget")


def _compact_system_message(messages: list[dict[str, Any]]) -> bool:
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "system":
            continue
        content = message.get("content")
        if not isinstance(content, str) or "agent_system_compacted" in content:
            continue
        if "You are an autonomous local coding agent" not in content:
            continue
        workspace = _regex_first(content, r"Workspace root:\s*(.+)")
        tools = _system_available_tools(content)
        reasoning = ""
        marker = "PERSISTENT WORKSPACE REASONING STATE (compact):"
        if marker in content:
            reasoning = content.split(marker, 1)[1].strip()
        compact_lines = [
            "agent_system_compacted: true",
            "You are an autonomous local coding agent inside the user's workspace.",
            "Inspect files before editing. Prefer apply_patch for coordinated edits and repairs.",
            "Reply with exactly one JSON object and no Markdown.",
            'Use {"action":"tool","tool":"read_file","args":{"path":"README.md"}} or {"action":"final","answer":"..."} only.',
        ]
        if workspace:
            compact_lines.append(f"Workspace root: {workspace}")
        if tools:
            compact_lines.append("Available tools: " + ", ".join(tools[:12]))
        if reasoning:
            compact_lines.append("Compact reasoning state:")
            compact_lines.append(_short_value(reasoning, maximum=600))
        messages[index] = {"role": "system", "content": "\n".join(compact_lines)}
        return True
    return False


def _regex_first(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _system_available_tools(content: str) -> list[str]:
    _, _, tail = content.partition("Available tools:")
    if not tail:
        return []
    tools: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        tools.append(stripped[2:].strip())
    return _dedupe_strings(tools)


def _compact_tool_result_for_history(
    tool_name: str,
    result: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    if result.get("compacted"):
        return result
    payload = result.get("result") if isinstance(result.get("result"), dict) else {}
    compact: dict[str, Any] = {
        "ok": result.get("ok") is not False,
        "tool": result.get("tool") or tool_name,
        "compacted": True,
        "compact_reason": reason,
    }
    for key in (
        "edit_policy_feedback",
        "context_change_bar_feedback",
        "duplicate_context_result",
        "duplicate_policy_feedback",
        "grouped_patch_required",
        "recommended_tool",
        "affected_files",
        "message",
    ):
        if key in result:
            compact[key] = result[key]
    changed_files = _changed_files_from_result(tool_name, result)
    if changed_files:
        compact["changed_files"] = changed_files
    if result.get("ok") is False and result.get("error"):
        compact["error"] = _short_value(result.get("error"), maximum=500)
    if payload:
        compact["result"] = _compact_tool_payload(tool_name, payload)
    validation = result.get("validation")
    if isinstance(validation, dict):
        compact["validation"] = _compact_validation_result(validation)
    repair = result.get("repair")
    if isinstance(repair, dict):
        compact["repair"] = repair
    rollback = result.get("rollback")
    if isinstance(rollback, dict):
        compact["rollback"] = _rollback_summary(rollback)
    checkpoint = result.get("checkpoint")
    if isinstance(checkpoint, dict):
        compact["checkpoint"] = _checkpoint_summary(checkpoint)
    policy = result.get("policy")
    if isinstance(policy, dict):
        compact["policy"] = _compact_policy_result(policy)
    return compact


def _compact_tool_payload(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "read_file":
        path = str(payload.get("path") or "")
        start_line = payload.get("start_line")
        end_line = payload.get("end_line")
        total_lines = payload.get("total_lines")
        chars = payload.get("chars")
        content = payload.get("content")
        return {
            "path": path,
            "summary": _read_file_compact_summary(
                path,
                start_line,
                end_line,
                total_lines,
                chars,
                content,
            ),
            "chars": chars,
            "start_line": start_line,
            "end_line": end_line,
            "total_lines": total_lines,
            "truncated": payload.get("truncated"),
            "content_hash": _content_hash(content) if isinstance(content, str) else "",
            "content_omitted": True,
        }
    if tool_name == "search_files":
        matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
        paths = _dedupe_strings(
            [
                str(item.get("path"))
                for item in matches
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            ]
        )
        return {
            "query": payload.get("query"),
            "match_count": len(matches),
            "matched_files": paths[:30],
            "matches": matches[:10],
            "summary": "Search results compacted; matched paths and first matches retained.",
        }
    if tool_name == "repo_map":
        related = _string_list_like(payload.get("related_files"))
        tests = _string_list_like(payload.get("test_files"))
        dependencies = _string_list_like(payload.get("dependency_files"))
        validation_targets = _string_list_like(payload.get("validation_targets"))
        return {
            "root": payload.get("root"),
            "focus": payload.get("focus"),
            "active_files": _string_list_like(payload.get("active_files"))[:20],
            "mentioned_files": _string_list_like(payload.get("mentioned_files"))[:20],
            "key_files": _string_list_like(payload.get("key_files"))[:20],
            "related_files": related[:30],
            "related_file_count": len(related),
            "test_files": tests[:30],
            "test_file_count": len(tests),
            "dependency_files": dependencies[:30],
            "dependency_file_count": len(dependencies),
            "validation_targets": validation_targets[:30],
            "validation_target_count": len(validation_targets),
            "search_hints": _string_list_like(payload.get("search_hints"))[:12],
            "summary": "Repository map compacted; file lists and counts retained.",
        }
    if tool_name == "apply_patch":
        patch_preview = payload.get("patch_preview")
        return {
            "paths": _string_list_like(payload.get("paths"))[:30],
            "changes": _compact_patch_changes(payload.get("changes")),
            "summary": _short_value(payload.get("summary"), maximum=500),
            "patch_preview_hash": _content_hash(patch_preview)
            if isinstance(patch_preview, str)
            else "",
            "patch_preview_chars": len(patch_preview) if isinstance(patch_preview, str) else 0,
            "patch_preview_omitted": True,
        }
    if tool_name == "run_command":
        return {
            "command": payload.get("command"),
            "cwd": payload.get("cwd"),
            "returncode": payload.get("returncode"),
            "stdout": _short_value(payload.get("stdout"), maximum=1000),
            "stderr": _short_value(payload.get("stderr"), maximum=1000),
            "stdout_truncated": payload.get("stdout_truncated"),
            "stderr_truncated": payload.get("stderr_truncated"),
        }
    summarized = _progress_tool_result(tool_name, {"ok": True, "result": payload})
    summarized.pop("ok", None)
    if isinstance(payload.get("files"), list):
        summarized["files"] = payload["files"][:20]
    if isinstance(payload.get("matches"), list):
        summarized["matches"] = payload["matches"][:20]
    return summarized or {"summary": "Tool result compacted."}


def _compact_patch_changes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    changes: list[dict[str, Any]] = []
    for item in value[:30]:
        if not isinstance(item, dict):
            continue
        changes.append(
            {
                "path": item.get("path"),
                "action": item.get("action"),
                "chars": item.get("chars"),
            }
        )
    return changes


def _read_file_compact_summary(
    path: str,
    start_line: Any,
    end_line: Any,
    total_lines: Any,
    chars: Any,
    content: Any = None,
) -> str:
    line_bits = []
    if start_line is not None and end_line is not None:
        line_bits.append(f"lines {start_line}-{end_line}")
    if total_lines is not None:
        line_bits.append(f"{total_lines} total lines")
    if chars is not None:
        line_bits.append(f"{chars} chars returned")
    if isinstance(content, str):
        line_bits.append(f"sha256:{_content_hash(content)}")
    details = ", ".join(line_bits) if line_bits else "content previously returned"
    return f"{path}: {details}; content omitted from compacted history."


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:12]


def _compact_validation_result(validation: dict[str, Any]) -> dict[str, Any]:
    checks = validation.get("checks")
    failed_checks = [
        {
            "name": check.get("name"),
            "category": check.get("category"),
            "failure_category": check.get("failure_category"),
            "command": check.get("command"),
            "returncode": check.get("returncode"),
            "stdout": _short_value(check.get("stdout"), maximum=2000),
            "stderr": _short_value(check.get("stderr"), maximum=2000),
        }
        for check in checks
        if isinstance(check, dict) and check.get("ok") is False
    ] if isinstance(checks, list) else []
    return {
        "ok": validation.get("ok"),
        "mode": validation.get("mode"),
        "changed_files": validation.get("changed_files", []),
        "validation_targets": validation.get("validation_targets", []),
        "failed_categories": validation.get("failed_categories", []),
        "failed_checks": failed_checks,
        "message": validation.get("message"),
    }


def _compact_policy_result(policy: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "name": policy.get("name"),
        "reason": _short_value(policy.get("reason"), maximum=500),
        "instructions": _string_list_like(policy.get("instructions"))[:4],
    }
    context = policy.get("context")
    if isinstance(context, dict):
        compact["context"] = {
            key: value
            for key, value in context.items()
            if key in {
                "target",
                "repair_context",
                "multi_file_task",
                "grouped_patch_required",
                "projected_changed_files",
                "impacted_files",
                "risky_files",
                "rewrite_risk",
            }
        }
    return compact


def _estimated_message_tokens(messages: list[dict[str, Any]]) -> int:
    return estimate_messages_tokens(messages)


def _largest_context_sources(messages: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        sources.append(
            {
                "index": index,
                "role": role,
                "tokens": _estimated_message_tokens([message]),
                "label": _context_source_label(content),
            }
        )
    sources.sort(key=lambda item: int(item.get("tokens") or 0), reverse=True)
    return sources[:limit]


def _context_source_label(content: str) -> str:
    if content.startswith("Tool result for "):
        header = content.split(":\n", 1)[0]
        return header[:120]
    if content.startswith("EXECUTION MEMORY SUMMARY"):
        return "execution_memory_summary"
    if content.startswith("PERSISTENT WORKSPACE REASONING STATE"):
        return "compact_reasoning_state"
    if "You are an autonomous local coding agent" in content:
        return "agent_system_instructions"
    return _short_value(content.replace("\n", " "), maximum=120)


def _context_warning_level(percent_used: Any) -> str:
    try:
        percent = float(percent_used)
    except (TypeError, ValueError):
        return "normal"
    if percent >= 95:
        return "critical"
    if percent >= 75:
        return "warn"
    return "normal"


def _context_tool_cache_key(
    toolbox: AgentToolbox,
    tool_name: str,
    args: dict[str, Any],
    *,
    workspace_revision: int,
    file_revisions: dict[str, int],
) -> tuple[Any, ...] | None:
    if tool_name not in DEDUPE_CONTEXT_TOOLS:
        return None
    if _context_tool_cache_bypass(args):
        return None
    if tool_name == "read_file":
        path = _context_cache_path(toolbox, args.get("path"))
        if not path:
            return None
        return (
            "read_file",
            path,
            args.get("start_line"),
            args.get("line_count"),
            args.get("max_chars"),
            file_revisions.get(path, 0),
        )
    focus = str(args.get("target") or args.get("path") or ".").strip() or "."
    return (
        "repo_map",
        _normalize_policy_path(focus),
        args.get("limit"),
        workspace_revision,
    )


def _context_cache_path(toolbox: AgentToolbox, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    target = _policy_resolved_path(toolbox, value)
    if target is not None:
        try:
            return _normalize_policy_path(toolbox._relative(target))
        except Exception:
            pass
    return _normalize_policy_path(value)


def _context_tool_cache_bypass(args: dict[str, Any]) -> bool:
    return any(_truthy_like(args.get(key)) for key in ("force", "refresh", "reread", "reload"))


def _duplicate_context_tool_result(tool_name: str, cached_result: dict[str, Any]) -> dict[str, Any]:
    result = _compact_tool_result_for_history(
        tool_name,
        deepcopy(cached_result),
        reason="duplicate_context_result",
    )
    result["duplicate_context_result"] = True
    result["message"] = (
        f"{tool_name} returned cached context; identical rereads are compacted to keep "
        "the agent history bounded. Request a specific line range or pass refresh=true if fresh content is required."
    )
    return result


def _policy_feedback_signature(tool_name: str, result: dict[str, Any]) -> str:
    payload = {
        "tool": tool_name,
        "affected_files": result.get("affected_files", []),
        "recommended_tool": result.get("recommended_tool"),
        "error": result.get("error"),
        "policy_name": result.get("policy", {}).get("name") if isinstance(result.get("policy"), dict) else None,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _duplicate_policy_feedback_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": tool_name,
        "edit_policy_feedback": True,
        "duplicate_policy_feedback": True,
        "recommended_tool": result.get("recommended_tool", "apply_patch"),
        "affected_files": result.get("affected_files", []),
        "grouped_patch_required": result.get("grouped_patch_required", False),
        "message": "Repeated identical edit-policy feedback was compacted; use apply_patch before retrying.",
        "error": "Repeated identical edit-policy feedback omitted from agent history.",
        "policy": {
            "name": "patch_first",
            "duplicate": True,
            "instructions": [
                "Use apply_patch with a concise summary and validation_plan.",
                "Do not repeat the same blocked edit tool call.",
            ],
        },
    }


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


def _context_change_bar_state(
    request: HubRequest,
    config: HubConfig,
    trace: list[dict[str, Any]],
    reasoning_state: WorkspaceReasoningState | None,
) -> dict[str, Any]:
    context_steps = _repo_context_steps(trace)
    broad_steps = [step for step in context_steps if step["tool"] in BROAD_CONTEXT_TOOLS]
    inspected_files = _inspected_files_from_trace(trace, reasoning_state)
    changed_files = _changed_files_from_trace(trace)
    return {
        "enabled": _context_change_bar_enabled(request, config),
        "mode": _request_context_change_bar_mode(request, config),
        "threshold": _request_context_change_bar_threshold(request, config),
        "score": _context_score(reasoning_state) if reasoning_state else 0,
        "minimum_score": _context_score_threshold(_request_context_change_bar_mode(request, config)),
        "repository_graph_nodes": len(_repository_graph_nodes(reasoning_state)) if reasoning_state else 0,
        "repository_graph_edges": len(reasoning_state.dependency_edges) if reasoning_state else 0,
        "inspected_files": inspected_files,
        "changed_files": changed_files,
        "repo_context_tools": [step["tool"] for step in context_steps],
        "broad_context_tools": [step["tool"] for step in broad_steps],
        "recent_context": _has_recent_repo_context(trace, reasoning_state),
        "last_context_tool": context_steps[-1]["tool"] if context_steps else "",
    }


def _context_score(reasoning_state: WorkspaceReasoningState | None) -> int:
    if reasoning_state is None:
        return 0
    try:
        return max(0, int(reasoning_state.context_score or 0))
    except (TypeError, ValueError):
        return 0


def _context_score_threshold(mode: str) -> int:
    if mode == "strict":
        return 6
    if mode == "light":
        return 3
    return 0


def _has_sufficient_context(
    toolbox: AgentToolbox,
    request: HubRequest,
    trace: list[dict[str, Any]],
    *,
    tool_name: str,
    args: dict[str, Any],
    messages: list[dict[str, Any]],
    reasoning_state: WorkspaceReasoningState,
    affected_files: list[str],
    multi_file_task: bool,
) -> dict[str, Any]:
    mode = _request_context_change_bar_mode(request, toolbox.config)
    score_threshold = _context_score_threshold(mode)
    changed_threshold = _request_context_change_bar_threshold(request, toolbox.config)
    score = _context_score(reasoning_state)
    context_tools = _context_tools_used(trace, reasoning_state)
    read_files = _read_files_used(trace, reasoning_state)
    inspected_files = _inspected_files_from_trace(trace, reasoning_state)
    changed_files = _changed_files_from_trace(trace)
    projected_changed_files = _dedupe_strings([*changed_files, *affected_files])
    existing_targets = _existing_affected_files(toolbox, affected_files)
    impacted_files = _impacted_files_for_files(reasoning_state, affected_files)
    related_tests = _related_tests_for_files(reasoning_state, existing_targets or affected_files)
    related_configs = _related_configs_for_files(reasoning_state, existing_targets or affected_files)
    related_dependencies = _related_dependencies_for_files(reasoning_state, existing_targets or affected_files)
    hallucinated_files = _hallucinated_edit_files(
        toolbox,
        tool_name,
        args,
        affected_files,
        reasoning_state,
    )
    missing: list[str] = []

    if not _context_change_bar_enabled(request, toolbox.config):
        return {
            "ok": True,
            "score": score,
            "threshold": score_threshold,
            "changed_file_threshold": changed_threshold,
            "missing_context": missing,
            "inspected_files": inspected_files,
            "read_files": read_files,
            "context_tools": context_tools,
            "changed_files": changed_files,
            "projected_changed_files": projected_changed_files,
            "existing_targets": existing_targets,
            "impacted_files": impacted_files,
            "related_tests": related_tests,
            "related_configs": related_configs,
            "related_dependencies": related_dependencies,
            "hallucinated_files": hallucinated_files,
        }

    if not context_tools:
        missing.append(
            "Inspect repository structure before editing: no repo_map, list_files, search_files, or read_file has run yet."
        )

    if mode == "light":
        if score < score_threshold:
            missing.append(
                f"Context score {score} is below light minimum {score_threshold}; use repo_map, search_files, or read_file."
            )
    elif mode == "strict":
        if score < score_threshold:
            missing.append(
                f"Context score {score} is below strict minimum {score_threshold}; use repo_map or search_files, then read_file."
            )
        if not ({"repo_map", "search_files"} & set(context_tools)):
            missing.append("Strict mode requires repo_map or search_files before editing.")
        unread_targets = [path for path in existing_targets if path not in read_files]
        if unread_targets:
            missing.append("Target file has not been inspected yet: " + ", ".join(unread_targets))
        if multi_file_task and not _has_related_context_read(read_files, existing_targets, reasoning_state):
            missing.append("Read related tests before modifying implementation.")
        unread_tests = [path for path in related_tests if path not in read_files]
        if unread_tests:
            missing.append("unread_related_test: " + ", ".join(unread_tests))
        unread_configs = [path for path in related_configs if path not in read_files]
        if unread_configs:
            missing.append("impacted config unread: " + ", ".join(unread_configs))
        unread_dependencies = [path for path in related_dependencies if path not in read_files]
        if unread_dependencies:
            missing.append("unread_dependency: " + ", ".join(unread_dependencies))
        if multi_file_task and not reasoning_state.dependency_edges:
            missing.append("repository graph incomplete in strict mode; run repo_map or search_files.")

    if multi_file_task and not _has_recent_repo_context(trace, reasoning_state):
        missing.append(
            "Multi-file task needs recent repository context; run repo_map, search_files, or read_file before editing."
        )
    if hallucinated_files and (mode == "strict" or _team_role(request) in {"reviewer", "fixer"}):
        missing.append("hallucinated_file_edit: " + ", ".join(hallucinated_files))
    if (
        changed_threshold > 0
        and len(projected_changed_files) > changed_threshold
        and not _has_recent_repo_context(trace, reasoning_state)
    ):
        missing.append(
            f"Changed files exceed context change threshold {changed_threshold}; refresh context with repo_map, search_files, or read_file."
        )
    if _repair_context_active(trace, messages) and not ({"repo_map", "search_files"} & set(context_tools)):
        missing.append("Validation repair needs repository context before editing; use repo_map or search_files.")

    return {
        "ok": not missing,
        "score": score,
        "threshold": score_threshold,
        "changed_file_threshold": changed_threshold,
        "missing_context": _dedupe_strings(missing),
        "inspected_files": inspected_files,
        "read_files": read_files,
        "context_tools": context_tools,
        "changed_files": changed_files,
        "projected_changed_files": projected_changed_files,
        "existing_targets": existing_targets,
        "impacted_files": impacted_files,
        "related_tests": related_tests,
        "related_configs": related_configs,
        "related_dependencies": related_dependencies,
        "hallucinated_files": hallucinated_files,
    }


def _is_multi_file_task(
    request: HubRequest,
    trace: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    reasoning_state: WorkspaceReasoningState | None,
    affected_files: list[str],
) -> bool:
    if len(_dedupe_strings(affected_files)) > 1:
        return True
    if reasoning_state and reasoning_state.grouped_patch_required:
        return True
    if reasoning_state and _has_graph_related_files(reasoning_state, affected_files):
        return True
    if reasoning_state and len(_impacted_files_for_files(reasoning_state, affected_files)) > 1:
        return True
    text = " ".join(
        [
            _task_policy_text(request),
            _recent_policy_message_text(messages[-8:]),
        ]
    ).lower()
    if any(
        phrase in text
        for phrase in (
            "multiple files",
            "multi-file",
            "several files",
            "many files",
            "multiple modules",
            "tests",
            "docs",
            "documentation",
            "config",
            "configuration",
            "migration",
            "refactor",
            "integration",
            "validation repair",
            "repair loop",
            "patch",
            "workspace-wide",
            "repository-wide",
            "repo-wide",
            "across",
            "reviewer requested",
            "required fixes",
        )
    ):
        return True
    if re.search(r"\band\b", text):
        return True
    if len(_path_like_tokens(text)) > 1:
        return True
    if _repair_context_active(trace, messages):
        return True
    if len(_changed_files_from_trace(trace)) > 1:
        return True
    if reasoning_state is not None:
        if len(_execution_plan_files(reasoning_state)) > 1:
            return True
        if len(_execution_plan_validation_targets(reasoning_state)) > 1:
            return True
        if _team_role(request) in {"reviewer", "fixer"} and reasoning_state.related_files:
            return True
    return False


def _reviewer_unread_files(
    toolbox: AgentToolbox,
    request: HubRequest,
    affected_files: list[str],
    reasoning_state: WorkspaceReasoningState,
) -> list[str]:
    if _team_role(request) != "reviewer":
        return []
    if not _context_change_bar_enabled(request, toolbox.config):
        return []
    read_files = set(_read_files_used([], reasoning_state))
    return [path for path in _existing_affected_files(toolbox, affected_files) if path not in read_files]


def _reviewer_rejection_reasons(
    toolbox: AgentToolbox,
    request: HubRequest,
    tool_name: str,
    args: dict[str, Any],
    affected_files: list[str],
    multi_file_task: bool,
    sufficiency: dict[str, Any],
    reasoning_state: WorkspaceReasoningState,
) -> list[str]:
    if _team_role(request) != "reviewer":
        return []
    reasons: list[str] = []
    read_files = set(_read_files_used([], reasoning_state))
    for path in _string_list_like(sufficiency.get("related_tests")):
        if path not in read_files:
            reasons.append("unread_related_test")
    for path in _string_list_like(sufficiency.get("related_dependencies")):
        if path not in read_files:
            reasons.append("unread_dependency")
    if _string_list_like(sufficiency.get("hallucinated_files")):
        reasons.append("hallucinated_file_edit")
    related_tests = set(_string_list_like(sufficiency.get("related_tests")))
    if related_tests and not (related_tests & set(affected_files)):
        reasons.append("missing_validation_target")
    if tool_name in {"write_file", "replace_in_file"} and (
        multi_file_task or _has_graph_related_files(reasoning_state, affected_files)
    ):
        reasons.append("fragmented_patch_strategy")
    if tool_name == "apply_patch" and _has_graph_related_files(reasoning_state, affected_files):
        impacted = set(_string_list_like(sufficiency.get("impacted_files")))
        if len(impacted - set(affected_files)) > 0 and related_tests and not (related_tests & set(affected_files)):
            reasons.append("fragmented_patch_strategy")
    if _hallucinated_edit_files(toolbox, tool_name, args, affected_files, reasoning_state):
        reasons.append("hallucinated_file_edit")
    return _dedupe_strings(reasons)


def _recommended_context_tools(sufficiency: dict[str, Any], affected_files: list[str]) -> list[str]:
    tools: list[str] = []
    context_tools = set(_string_list_like(sufficiency.get("context_tools")))
    if not ({"repo_map", "search_files"} & context_tools):
        tools.extend(["repo_map", "search_files"])
    if affected_files or sufficiency.get("existing_targets"):
        tools.append("read_file")
    if not tools:
        tools.append("repo_map")
    return _dedupe_strings(tools)


def _context_change_bar_feedback(
    toolbox: AgentToolbox,
    tool_name: str,
    args: dict[str, Any],
    request: HubRequest,
    trace: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    reasoning_state: WorkspaceReasoningState,
) -> dict[str, Any] | None:
    if tool_name not in EDIT_TOOLS:
        return None

    mode = _request_context_change_bar_mode(request, toolbox.config)
    affected = _policy_affected_files(toolbox, tool_name, args)
    multi_file_task = _is_multi_file_task(request, trace, messages, reasoning_state, affected)
    reviewer_unread = _reviewer_unread_files(toolbox, request, affected, reasoning_state)
    sufficiency = _has_sufficient_context(
        toolbox,
        request,
        trace,
        tool_name=tool_name,
        args=args,
        messages=messages,
        reasoning_state=reasoning_state,
        affected_files=affected,
        multi_file_task=multi_file_task,
    )
    missing = list(sufficiency["missing_context"])
    if reviewer_unread:
        missing.append("Reviewer rejected edits against unread file(s): " + ", ".join(reviewer_unread))
    reviewer_reasons = _reviewer_rejection_reasons(
        toolbox,
        request,
        tool_name,
        args,
        affected,
        multi_file_task,
        sufficiency,
        reasoning_state,
    )
    if reviewer_reasons:
        missing.append("reviewer_rejected_patch: " + ", ".join(reviewer_reasons))

    if not missing:
        return None

    impacted_files = _string_list_like(sufficiency.get("impacted_files"))
    grouped_required = (
        multi_file_task
        or len(affected) > 1
        or _repair_context_active(trace, messages)
        or len(_dedupe_strings([*affected, *impacted_files])) > 1
        or _has_graph_related_files(reasoning_state, affected)
        or bool(reviewer_reasons)
    )
    recommended_tools = _recommended_context_tools(sufficiency, affected)
    return {
        "ok": False,
        "tool": tool_name,
        "edit_policy_feedback": True,
        "context_change_bar_feedback": True,
        "grouped_patch_required": grouped_required,
        "reviewer_rejected_unread_edit": bool(reviewer_unread),
        "reviewer_rejection_reasons": reviewer_reasons,
        "recommended_tool": recommended_tools[0] if recommended_tools else "repo_map",
        "affected_files": affected,
        "error": "Context change bar blocked the edit: " + "; ".join(missing),
        "message": "Context change bar blocked this edit until repository context is gathered.",
        "policy": {
            "name": "context_change_bar",
            "mode": mode,
            "score": sufficiency["score"],
            "threshold": sufficiency["threshold"],
            "changed_file_threshold": sufficiency["changed_file_threshold"],
            "missing_context": missing,
            "inspected_files": sufficiency["inspected_files"],
            "read_files": sufficiency["read_files"],
            "context_tools": sufficiency["context_tools"],
            "changed_files": sufficiency["changed_files"],
            "projected_changed_files": sufficiency["projected_changed_files"],
            "impacted_files": impacted_files,
            "related_tests": sufficiency["related_tests"],
            "related_configs": sufficiency["related_configs"],
            "related_dependencies": sufficiency["related_dependencies"],
            "hallucinated_files": sufficiency["hallucinated_files"],
            "multi_file_task": multi_file_task,
            "recommended_tools": recommended_tools,
            "instructions": [
                "Inspect repository structure before editing with repo_map.",
                "Use search_files for usages/imports and read_file for files you plan to edit.",
                "Read related tests before modifying implementation.",
                "Use apply_patch for coordinated multi-file changes.",
            ],
        },
    }


def _edit_policy_feedback(
    toolbox: AgentToolbox,
    tool_name: str,
    args: dict[str, Any],
    request: HubRequest,
    trace: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    reasoning_state: WorkspaceReasoningState,
) -> dict[str, Any] | None:
    context_feedback = _context_change_bar_feedback(
        toolbox,
        tool_name,
        args,
        request,
        trace,
        messages,
        reasoning_state,
    )
    if context_feedback is not None:
        return context_feedback
    if tool_name == "apply_patch":
        return _apply_patch_rewrite_policy_feedback(toolbox, args, request)
    if tool_name not in {"write_file", "replace_in_file"}:
        return None
    if not _request_bool(request, "prefer_multi_file_patches", toolbox.config.prefer_multi_file_patches):
        return None

    affected = _policy_affected_files(toolbox, tool_name, args)
    in_repair = _repair_context_active(trace, messages)
    multi_file_task = _is_multi_file_task(request, trace, messages, reasoning_state, affected)
    impacted_files = _impacted_files_for_files(reasoning_state, affected)
    projected_changed = _dedupe_strings([*_changed_files_from_trace(trace), *affected])
    grouped_required = (
        multi_file_task
        or in_repair
        or len(projected_changed) > 1
        or _has_impl_and_support_files(projected_changed)
        or _reviewer_requested_fixes(request, messages)
        or _has_graph_related_files(reasoning_state, affected)
        or len(_dedupe_strings([*affected, *impacted_files])) > 1
    )
    if tool_name == "write_file":
        path = affected[0] if affected else _short_value(args.get("path"))
        target = _policy_resolved_path(toolbox, args.get("path"))
        append = bool(args.get("append", False))
        existing_overwrite = bool(target and target.exists() and not append)
        entirely_new = bool(target and not target.exists())
        content = args.get("content")
        content_chars = len(content) if isinstance(content, str) else 0
        fragmented_chain = _fragmented_write_chain_active(trace, affected, reasoning_state)
        if (
            existing_overwrite
            or in_repair
            or fragmented_chain
            or (grouped_required and not entirely_new and content_chars > 0)
        ):
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
                    "grouped_patch_required": grouped_required,
                    "projected_changed_files": projected_changed,
                    "impacted_files": impacted_files,
                    "fragmented_write_chain": fragmented_chain,
                    "content_chars": content_chars,
                    "target": path,
                },
                grouped_patch_required=grouped_required or fragmented_chain,
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
        if not (in_repair or grouped_required or large_replace):
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
                "grouped_patch_required": grouped_required,
                "projected_changed_files": projected_changed,
                "impacted_files": impacted_files,
                "large_replace": large_replace,
                "old_chars": old_chars,
                "new_chars": new_chars,
                "expected_replacements": expected_replacements,
                "target": affected[0] if affected else _short_value(args.get("path")),
            },
            grouped_patch_required=grouped_required,
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
    grouped_patch_required: bool = False,
) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": tool_name,
        "edit_policy_feedback": True,
        "grouped_patch_required": grouped_patch_required,
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
    if tool_name == "apply_patch":
        try:
            return [str(path) for path in toolbox._get_affected_files(tool_name, args) if str(path)]
        except Exception:
            return _patch_path_hints(args)
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
    text = _task_policy_text(request).lower()
    return any(
        phrase in text
        for phrase in (
            "multiple files",
            "multi-file",
            "several files",
            "many files",
            "multiple modules",
            "module and",
            "modules",
            "implementation and tests",
            "implementation plus tests",
            "tests and docs",
            "tests and config",
            "update tests",
            "add tests",
            "test suite",
            "config",
            "configuration",
            "docs",
            "documentation",
            "readme",
            "examples",
            "refactor",
            "repository-wide",
            "repo-wide",
        )
    )


def _task_policy_text(request: HubRequest) -> str:
    parts = [str(value or "") for value in (request.task, request.context) if value]
    for message in request.messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(_message_task_section(content))
    return " ".join(part for part in parts if part)


def _message_task_section(content: str) -> str:
    match = re.search(r"(?im)^Task:\s*$", content)
    if not match:
        return content
    rest = content[match.end() :]
    end = re.search(
        r"(?im)^(Selected plan|Research context|Review context|Coder result|Task result):\s*$",
        rest,
    )
    return rest[: end.start()].strip() if end else rest.strip()


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
            completed = run_workspace_command(
                CommandExecutionRequest(
                    command=item["command"],
                    workspace_dir=root,
                    cwd=root,
                    timeout_seconds=item["timeout_seconds"],
                    state_dir=config.state_dir,
                    source=f"post_edit_validation.{item['name']}",
                )
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


def _request_context_change_bar_mode(request: HubRequest, config: HubConfig) -> str:
    value = str(
        _request_option(request, "context_change_bar_mode", config.context_change_bar_mode)
        or "light"
    ).strip().lower()
    if value in {"off", "light", "strict"}:
        return value
    return "light"


def _request_context_change_bar_threshold(request: HubRequest, config: HubConfig) -> int:
    value = _request_option(
        request,
        "context_change_bar_threshold",
        config.context_change_bar_threshold,
    )
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = config.context_change_bar_threshold
    return max(0, min(number, 50))


def _context_change_bar_enabled(request: HubRequest, config: HubConfig) -> bool:
    return (
        _request_bool(request, "context_change_bar_enabled", config.context_change_bar_enabled)
        and _request_context_change_bar_mode(request, config) != "off"
    )


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
            "stdout": _short_value(check.get("stdout", ""), maximum=4000),
            "stderr": _short_value(check.get("stderr", ""), maximum=4000),
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


def _repo_context_steps(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for index, step in enumerate(trace):
        tool = str(step.get("tool") or "")
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        if tool in CONTEXT_TOOLS and result.get("ok") is not False:
            steps.append({"index": index, "step": step.get("step"), "tool": tool})
    return steps


def _has_recent_repo_context(
    trace: list[dict[str, Any]],
    reasoning_state: WorkspaceReasoningState | None,
) -> bool:
    last_edit_index = -1
    last_context_index = -1
    for index, step in enumerate(trace):
        tool = str(step.get("tool") or "")
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        if tool in CONTEXT_TOOLS and result.get("ok") is not False:
            last_context_index = index
        if tool in EDIT_TOOLS and _changed_files_from_result(tool, result):
            last_edit_index = index
    if last_context_index > last_edit_index:
        return True
    return last_edit_index < 0 and bool(
        reasoning_state
        and (
            reasoning_state.inspected_files
            or _context_tools_used([], reasoning_state)
        )
    )


def _inspected_files_from_trace(
    trace: list[dict[str, Any]],
    reasoning_state: WorkspaceReasoningState | None,
) -> list[str]:
    files: list[str] = []
    if reasoning_state is not None:
        files.extend(reasoning_state.inspected_files)
    for step in trace:
        tool = str(step.get("tool") or "")
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        if tool == "read_file" and isinstance(payload.get("path"), str):
            files.append(payload["path"])
        elif tool == "list_files" and isinstance(payload.get("files"), list):
            files.extend(str(item.get("path")) for item in payload["files"] if isinstance(item, dict))
        elif tool == "search_files" and isinstance(payload.get("matches"), list):
            files.extend(str(item.get("path")) for item in payload["matches"] if isinstance(item, dict))
        elif tool == "repo_map":
            for key in ("active_files", "mentioned_files", "key_files", "related_files", "test_files"):
                values = payload.get(key)
                if isinstance(values, list):
                    files.extend(str(value) for value in values if isinstance(value, str))
    return _dedupe_strings([path for path in files if path])[:80]


def _changed_files_from_trace(trace: list[dict[str, Any]]) -> list[str]:
    changed: list[str] = []
    for step in trace:
        tool = str(step.get("tool") or "")
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        changed.extend(_changed_files_from_result(tool, result))
    return _dedupe_strings(changed)[:80]


def _patch_path_hints(args: dict[str, Any]) -> list[str]:
    changes = args.get("changes")
    if isinstance(changes, list):
        return [
            str(item.get("path"))
            for item in changes
            if isinstance(item, dict) and isinstance(item.get("path"), str) and item.get("path")
        ]
    patch = args.get("patch")
    if isinstance(patch, str):
        paths: list[str] = []
        for line in patch.splitlines():
            if not line.startswith("+++ "):
                continue
            value = line[4:].strip().split("\t", 1)[0].split(" ", 1)[0]
            if value in {"/dev/null", "dev/null"}:
                continue
            if value.startswith("b/"):
                value = value[2:]
            if value:
                paths.append(value)
        return _dedupe_strings(paths)
    return []


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


def _request_positive_int_option(request: HubRequest, key: str) -> int | None:
    value = _request_option(request, key, None)
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _truthy_like(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


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


def _compact_session_history_messages(
    history: list[dict[str, Any]],
    current_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for index, message in enumerate(history):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        content = message.get("content")
        if role not in {"user", "assistant", "system", "tool"}:
            continue
        recent = index >= max(0, len(history) - 8)
        protected = is_protected_context_message(message, recent=recent)
        if isinstance(content, str) and _session_history_content_is_tool_noise(content) and not protected:
            continue
        if isinstance(content, str):
            maximum = 4000 if protected else 1200
            cleaned.append({"role": role, "content": _short_value(content, maximum=maximum)})
            continue
        if protected:
            cleaned.append(dict(message))
            continue
        text = _short_value(json.dumps(content, ensure_ascii=False), maximum=1200)
        cleaned.append({"role": role, "content": text})
    if not cleaned:
        return []

    last_user = next((message for message in reversed(cleaned) if message["role"] == "user"), None)
    last_assistant = next(
        (message for message in reversed(cleaned) if message["role"] == "assistant"),
        None,
    )
    compact: list[dict[str, str]] = []
    if last_user:
        compact.append(
            {
                "role": "user",
                "content": "Prior session request (compact): " + _short_value(
                    last_user.get("content"),
                    maximum=1200,
                ),
            }
        )
    if last_assistant:
        compact.append(
            {
                "role": "assistant",
                "content": "Prior session answer (compact): " + _short_value(
                    last_assistant.get("content"),
                    maximum=1200,
                ),
            }
        )
    for message in cleaned[-MAX_COMPACT_SESSION_MESSAGES:]:
        if message not in compact:
            compact.append(message)
    current_texts = {
        message_signature(message)
        for message in current_messages
        if isinstance(message, dict)
    }
    return [
        message
        for message in compact[-MAX_COMPACT_SESSION_MESSAGES:]
        if message_signature(message) not in current_texts
    ]


def _session_history_content_is_tool_noise(content: str) -> bool:
    text = content.strip()
    if text.startswith("Tool result for "):
        return True
    if text.startswith("EXECUTION MEMORY SUMMARY"):
        return True
    if "Continue with exactly one JSON object" in text:
        return True
    if _assistant_tool_call_message({"role": "assistant", "content": text}):
        return True
    return False


def _is_prefix(prefix: list[dict], messages: list[dict]) -> bool:
    if len(prefix) > len(messages):
        return False
    return all(
        left.get("role") == right.get("role") and left.get("content") == right.get("content")
        for left, right in zip(prefix, messages, strict=False)
    )
