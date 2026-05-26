from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..models import ProviderResult
from .types import ToolCall, ToolResult


@dataclass(slots=True)
class ToolLoopMetadata:
    """Execution metadata attached to Agent Hub routing details."""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    tool_iteration_count: int = 0
    max_tool_iterations: int = 0
    max_tool_iterations_reached: bool = False
    invalid_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    duplicate_tool_call_detected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_calls": list(self.tool_calls),
            "tool_results": list(self.tool_results),
            "tool_iteration_count": self.tool_iteration_count,
            "max_tool_iterations": self.max_tool_iterations,
            "max_tool_iterations_reached": self.max_tool_iterations_reached,
            "invalid_tool_calls": list(self.invalid_tool_calls),
            "duplicate_tool_call_detected": self.duplicate_tool_call_detected,
        }


def extract_tool_calls(result: ProviderResult) -> list[ToolCall]:
    """Normalize OpenAI, Anthropic, and Gemini function calls."""

    raw = result.raw if isinstance(result.raw, dict) else {}
    calls = _openai_tool_calls(raw)
    if not calls:
        calls = _anthropic_tool_calls(raw)
    if not calls:
        calls = _gemini_tool_calls(raw)
    return [ToolCall.from_openai(call) for call in calls]


def valid_tool_calls(calls: list[ToolCall], metadata: ToolLoopMetadata) -> list[ToolCall]:
    valid: list[ToolCall] = []
    for call in calls:
        if not call.name:
            metadata.invalid_tool_calls.append(
                {
                    "id": call.id,
                    "reason": "missing_tool_name",
                    "raw": dict(call.raw),
                }
            )
            continue
        if not isinstance(call.arguments, dict):
            metadata.invalid_tool_calls.append(
                {
                    "id": call.id,
                    "name": call.name,
                    "reason": "arguments_not_object",
                }
            )
            call.arguments = {}
        valid.append(call)
    return valid


def tool_call_signature(call: ToolCall) -> str:
    try:
        args = json.dumps(call.arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        args = "{}"
    return f"{call.name}:{args}"


def compact_tool_result_for_loop(result: ToolResult, *, max_chars: int = 12_000) -> ToolResult:
    data = result.to_dict()
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return result
    preview = text[: max(0, max_chars - 500)]
    return ToolResult(
        call_id=result.call_id,
        name=result.name,
        ok=result.ok,
        content={
            "summary": "Tool result was reduced before being sent back to the provider.",
            "truncated": True,
            "original_chars": len(text),
            "preview": preview,
        },
        error=result.error[:1000] if result.error else "",
        started_at=result.started_at,
        finished_at=result.finished_at,
        metadata={**dict(result.metadata), "compacted_for_provider": True},
    )


def assistant_message_from_result(result: ProviderResult, calls: list[ToolCall]) -> dict[str, Any]:
    raw = result.raw if isinstance(result.raw, dict) else {}
    raw_message = _openai_message(raw)
    content = raw_message.get("content") if isinstance(raw_message, dict) else None
    if content is None:
        content = result.text or None
    message: dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "tool_calls": [_openai_call_from_tool_call(call) for call in calls],
    }
    return message


def tool_results_ok(results: list[ToolResult]) -> bool:
    return all(result.ok for result in results)


def merge_tool_loop_metadata(raw: dict[str, Any], metadata: ToolLoopMetadata) -> dict[str, Any]:
    copied = dict(raw)
    hub = dict(copied.get("agent_hub") or {})
    data = metadata.to_dict()
    hub["tool_loop"] = data
    hub["tool_calls"] = data["tool_calls"]
    hub["tool_results"] = data["tool_results"]
    hub["tool_iteration_count"] = data["tool_iteration_count"]
    copied["agent_hub"] = hub
    return copied


def max_loop_result(result: ProviderResult, metadata: ToolLoopMetadata) -> ProviderResult:
    raw = _raw_without_pending_tool_calls(result.raw if isinstance(result.raw, dict) else {})
    raw = merge_tool_loop_metadata(raw, metadata)
    text = result.text.strip() if result.text else ""
    if not text:
        text = (
            "Tool execution stopped because the maximum Agent Hub tool "
            f"iteration count ({metadata.max_tool_iterations}) was reached."
        )
    return ProviderResult(
        text=text,
        model=result.model,
        raw=raw,
        usage=dict(result.usage),
        finish_reason="tool_loop_max_reached",
        citations=list(result.citations),
        search_results=list(result.search_results),
        images=list(result.images),
        related_questions=list(result.related_questions),
    )


def _openai_tool_calls(raw: dict[str, Any]) -> list[dict[str, Any]]:
    message = _openai_message(raw)
    if not message:
        return []
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        return [call for call in tool_calls if isinstance(call, dict)]
    function_call = message.get("function_call")
    if isinstance(function_call, dict) and function_call.get("name"):
        return [{"id": "function_call", "type": "function", "function": function_call}]
    return []


def _openai_message(raw: dict[str, Any]) -> dict[str, Any]:
    choices = raw.get("choices") if isinstance(raw, dict) else None
    if not isinstance(choices, list) or not choices:
        return {}
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    return message


def _anthropic_tool_calls(raw: dict[str, Any]) -> list[dict[str, Any]]:
    content = raw.get("content") if isinstance(raw, dict) else None
    if not isinstance(content, list):
        return []
    calls: list[dict[str, Any]] = []
    for index, item in enumerate(content):
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        calls.append(
            {
                "id": str(item.get("id") or f"call_{index}"),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": _json_args(item.get("input")),
                },
            }
        )
    return calls


def _gemini_tool_calls(raw: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = raw.get("candidates") if isinstance(raw, dict) else None
    if not isinstance(candidates, list) or not candidates:
        return []
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return []
    calls: list[dict[str, Any]] = []
    for index, part in enumerate(parts):
        function_call = part.get("functionCall") or part.get("function_call") if isinstance(part, dict) else None
        if not isinstance(function_call, dict):
            continue
        name = function_call.get("name")
        if not isinstance(name, str) or not name:
            continue
        calls.append(
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": _json_args(function_call.get("args")),
                },
            }
        )
    return calls


def _openai_call_from_tool_call(call: ToolCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.name,
            "arguments": _json_args(call.arguments),
        },
    }


def _json_args(value: Any) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = {}
        value = parsed if isinstance(parsed, dict) else {}
    return json.dumps(value if isinstance(value, dict) else {}, separators=(",", ":"), ensure_ascii=False)


def _raw_without_pending_tool_calls(raw: dict[str, Any]) -> dict[str, Any]:
    copied = dict(raw)
    choices = copied.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        first = dict(choices[0])
        message = first.get("message")
        if isinstance(message, dict):
            message = dict(message)
            message.pop("tool_calls", None)
            message.pop("function_call", None)
            if message.get("content") is None:
                message["content"] = ""
            first["message"] = message
        first["finish_reason"] = "tool_loop_max_reached"
        copied["choices"] = [first, *choices[1:]]
    return copied
