from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .agent_tools import AgentToolbox, tool_result_message
from .config import HubConfig
from .models import FailoverEvent, HubRequest, HubResponse
from .router import AgentRouter


TOOL_ACTIONS = {
    "list_files",
    "read_file",
    "search_files",
    "write_file",
    "replace_in_file",
    "run_command",
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


class AgentRunner:
    def __init__(self, config: HubConfig, router: AgentRouter | None = None) -> None:
        self.config = config
        self.router = router or AgentRouter(config)

    def run(self, request: HubRequest, event_sink: AgentEventSink | None = None) -> HubResponse:
        toolbox = AgentToolbox(self.config, request)
        messages = self._initial_messages(request, toolbox)
        max_steps = _request_int(request, "agent_max_steps", self.config.agent_max_steps)
        trace: list[dict[str, Any]] = []
        failover: list[FailoverEvent] = []
        last_response: HubResponse | None = None

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
                result = toolbox.run(tool_name, args)
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
                messages.append({"role": "assistant", "content": response.text})
                messages.append(tool_result_message(tool_name, result))
                continue

            if command["action"] == "final":
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
                )
                self._record_final(request, final)
                return final

            if command["action"] == "invalid":
                _emit(
                    event_sink,
                    "invalid_response",
                    message=f"Step {step_number}: model response did not match the agent protocol; retrying.",
                    step=step_number,
                    reason=command.get("reason"),
                )
                messages.append({"role": "assistant", "content": response.text})
                messages.append(_invalid_response_message(command))
                continue

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
        )
        self._record_final(request, final)
        return final

    def _initial_messages(self, request: HubRequest, toolbox: AgentToolbox) -> list[dict[str, Any]]:
        request_with_history = self._with_session_history(request)
        return [
            {"role": "system", "content": toolbox.instructions()},
            *request_with_history.messages,
        ]

    def _with_session_history(self, request: HubRequest) -> HubRequest:
        if not request.use_session_history:
            return request
        history = self.router.session_store.load(request.session_id).get("messages", [])
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
    ) -> HubResponse:
        raw = dict(response.raw) if response else {}
        existing_metadata = raw.get("agent_hub")
        base_metadata = existing_metadata if isinstance(existing_metadata, dict) else {}
        raw["agent_hub"] = {
            **base_metadata,
            "mode": "agent",
            "steps": trace,
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
    if tool_name == "search_files":
        query = _short_value(args.get("query"))
        path = _short_value(args.get("path", "."))
        return f"{query} in {path}" if query else path
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
    if tool_name == "search_files":
        matches = payload.get("matches")
        return f"{len(matches)} match(es)" if isinstance(matches, list) else ""
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
        "replacements",
        "chars",
        "append",
        "truncated",
        "start_line",
        "end_line",
        "total_lines",
        "query",
    }
    summarized = {key: value for key, value in payload.items() if key in summary_keys}
    if isinstance(payload.get("files"), list):
        summarized["file_count"] = len(payload["files"])
    if isinstance(payload.get("matches"), list):
        summarized["match_count"] = len(payload["matches"])
    return {"ok": True, **summarized}


def _short_value(value: Any, maximum: int = 120) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= maximum:
        return text
    return f"{text[: maximum - 1]}..."


def _command_from_response(response: HubResponse) -> dict[str, Any]:
    tool_call = _openai_tool_call(response.raw) or _anthropic_tool_call(response.raw)
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


def _is_prefix(prefix: list[dict], messages: list[dict]) -> bool:
    if len(prefix) > len(messages):
        return False
    return all(
        left.get("role") == right.get("role") and left.get("content") == right.get("content")
        for left, right in zip(prefix, messages, strict=False)
    )
