from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from typing import Any

from .context import content_to_text
from .models import ProviderResult


SAFE_MALFORMED_CONTENT = "[Provider returned malformed response]"
ALLOWED_ROLES = {"assistant", "user", "system", "developer", "tool"}
SANE_FINISH_REASONS = {
    None,
    "stop",
    "length",
    "tool_calls",
    "function_call",
    "content_filter",
    "tool_use",
    "end_turn",
    "max_tokens",
    "stop_sequence",
    "safety",
    "recitation",
}


@dataclass(slots=True)
class ResponseValidation:
    valid: bool
    reason: str = ""
    issues: list[str] = field(default_factory=list)


def safe_empty_provider_result(
    *,
    model: str,
    raw: dict[str, Any] | None = None,
    reason: str = "malformed_response",
) -> ProviderResult:
    normalized = _openai_safe_raw(model=model, content=SAFE_MALFORMED_CONTENT, raw=raw or {})
    _mark_normalization(normalized, valid=False, reason=reason)
    return ProviderResult(
        text=SAFE_MALFORMED_CONTENT,
        model=model,
        raw=normalized,
        usage={},
        finish_reason="stop",
    )


def validate_provider_result(result: ProviderResult) -> ResponseValidation:
    raw = result.raw if isinstance(result.raw, dict) else {}
    normalization = raw.get("agent_hub_normalization") if isinstance(raw, dict) else None
    if isinstance(normalization, dict) and normalization.get("valid") is False:
        return ResponseValidation(
            valid=False,
            reason=str(normalization.get("reason") or "provider_normalization_failed"),
            issues=[str(item) for item in normalization.get("issues", []) if isinstance(item, str)],
        )
    if result.text:
        return ResponseValidation(valid=True)
    if _openai_tool_calls(raw) or _anthropic_tool_uses(raw) or _gemini_tool_calls(raw):
        return ResponseValidation(valid=True)
    return ResponseValidation(valid=False, reason="empty_provider_response", issues=["missing_content_or_tool_calls"])


def normalize_openai_compatible_result(
    raw: dict[str, Any],
    *,
    default_model: str,
    provider_name: str = "",
) -> ProviderResult:
    data = dict(raw) if isinstance(raw, dict) else {}
    issues: list[str] = []
    choices = data.get("choices")
    normalized_choices: list[dict[str, Any]] = []
    if isinstance(choices, list) and choices:
        for index, choice_value in enumerate(choices):
            if not isinstance(choice_value, dict):
                issues.append(f"choice_{index}_not_object")
                continue
            normalized_choices.append(_normalize_openai_choice(choice_value, index=index, issues=issues))
    else:
        issues.append("missing_choices")
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        content = (
            message.get("content")
            if isinstance(message, dict) and message.get("content") is not None
            else data.get("content", data.get("response", data.get("text", data.get("output_text", ""))))
        )
        tool_calls = _normalize_tool_calls(
            message.get("tool_calls") if isinstance(message, dict) else data.get("tool_calls"),
            issues=issues,
        )
        normalized_message: dict[str, Any] = {
            "role": _normalize_role(message.get("role") if isinstance(message, dict) else None, issues=issues),
            "content": content_to_text(content),
        }
        if tool_calls:
            normalized_message["content"] = normalized_message["content"] or None
            normalized_message["tool_calls"] = tool_calls
        function_call = message.get("function_call") if isinstance(message, dict) else data.get("function_call")
        function_call = _normalize_function_call(function_call, issues=issues)
        if function_call:
            normalized_message["function_call"] = function_call
        normalized_choices.append(
            {
                "index": 0,
                "message": normalized_message,
                "finish_reason": _normalize_finish_reason(
                    data.get("finish_reason") or data.get("done_reason"),
                    has_tool_calls=bool(tool_calls or function_call),
                    issues=issues,
                ),
            }
        )

    if not normalized_choices:
        return safe_empty_provider_result(model=default_model, raw=data, reason="missing_choices")

    data["choices"] = normalized_choices
    data["model"] = str(data.get("model") or default_model)
    choice = normalized_choices[0]
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    text = content_to_text(message.get("content"))
    tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
    function_call = message.get("function_call") if isinstance(message, dict) else None
    valid = bool(text or tool_calls or function_call)
    if not valid:
        return safe_empty_provider_result(model=data["model"], raw=data, reason="missing_content_or_tool_calls")
    _mark_normalization(
        data,
        valid=True,
        reason="normalized",
        issues=issues,
        provider_family=provider_name or "openai-compatible",
    )
    return ProviderResult(
        text=text,
        model=data["model"],
        raw=data,
        usage=dict(data.get("usage") or {}),
        finish_reason=choice.get("finish_reason") or "stop",
    )


def normalize_ollama_result(raw: dict[str, Any], *, default_model: str) -> ProviderResult:
    data = dict(raw) if isinstance(raw, dict) else {}
    if isinstance(data.get("choices"), list):
        return normalize_openai_compatible_result(data, default_model=default_model, provider_name="ollama")
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    converted = {
        **data,
        "model": data.get("model") or default_model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": message.get("content", data.get("response", "")),
                    **({"tool_calls": message.get("tool_calls")} if isinstance(message.get("tool_calls"), list) else {}),
                },
                "finish_reason": data.get("done_reason") or data.get("finish_reason") or "stop",
            }
        ],
    }
    return normalize_openai_compatible_result(converted, default_model=default_model, provider_name="ollama")


def normalize_groq_openrouter_result(raw: dict[str, Any], *, default_model: str, provider_name: str) -> ProviderResult:
    result = normalize_openai_compatible_result(
        raw,
        default_model=default_model,
        provider_name=provider_name or "openai-compatible",
    )
    if isinstance(result.raw, dict):
        normalization = dict(result.raw.get("agent_hub_normalization") or {})
        normalization["provider_family"] = provider_name or "groq-openrouter"
        result.raw["agent_hub_normalization"] = normalization
    return result


def normalize_anthropic_result(raw: dict[str, Any], *, default_model: str) -> ProviderResult:
    data = dict(raw) if isinstance(raw, dict) else {}
    issues: list[str] = []
    content = data.get("content")
    if isinstance(content, str):
        issues.append("content_string_repaired")
        content = [{"type": "text", "text": content}]
    elif not isinstance(content, list):
        issues.append("missing_content")
        text = data.get("text") or data.get("output_text") or ""
        content = [{"type": "text", "text": content_to_text(text)}]

    blocks: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for index, item in enumerate(content):
        if not isinstance(item, dict):
            issues.append(f"content_{index}_not_object")
            continue
        block_type = str(item.get("type") or "text")
        if block_type == "tool_use":
            name = item.get("name")
            if not isinstance(name, str) or not name:
                issues.append(f"tool_use_{index}_missing_name")
                continue
            blocks.append(
                {
                    "type": "tool_use",
                    "id": str(item.get("id") or f"toolu_{index}"),
                    "name": name,
                    "input": _json_object(item.get("input"), issues=issues, issue_prefix=f"tool_use_{index}"),
                }
            )
            continue
        text = item.get("text", item.get("content", ""))
        text_value = content_to_text(text)
        blocks.append({"type": "text", "text": text_value})
        if text_value:
            text_parts.append(text_value)

    if not blocks:
        return safe_empty_provider_result(model=str(data.get("model") or default_model), raw=data, reason="missing_content")

    data["content"] = blocks
    data["model"] = str(data.get("model") or default_model)
    finish = _normalize_finish_reason(data.get("stop_reason"), has_tool_calls=_has_anthropic_tool_use(blocks), issues=issues)
    data["stop_reason"] = _anthropic_finish_reason(finish, has_tool_calls=_has_anthropic_tool_use(blocks))
    _mark_normalization(data, valid=True, reason="normalized", issues=issues, provider_family="anthropic")
    return ProviderResult(
        text="\n".join(text_parts),
        model=data["model"],
        raw=data,
        usage=dict(data.get("usage") or {}),
        finish_reason=data["stop_reason"],
    )


def normalize_gemini_result(raw: dict[str, Any], *, default_model: str) -> ProviderResult:
    data = dict(raw) if isinstance(raw, dict) else {}
    issues: list[str] = []
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        issues.append("missing_candidates")
        text = content_to_text(data.get("text") or data.get("output_text") or data.get("response") or "")
        if not text:
            return safe_empty_provider_result(model=default_model, raw=data, reason="missing_candidates")
        candidates = [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}]

    normalized_candidates: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for candidate_index, candidate_value in enumerate(candidates):
        if not isinstance(candidate_value, dict):
            issues.append(f"candidate_{candidate_index}_not_object")
            continue
        content = candidate_value.get("content") if isinstance(candidate_value.get("content"), dict) else {}
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            issues.append(f"candidate_{candidate_index}_missing_parts")
            parts = []
        normalized_parts: list[dict[str, Any]] = []
        for part_index, part in enumerate(parts):
            if not isinstance(part, dict):
                issues.append(f"part_{candidate_index}_{part_index}_not_object")
                continue
            function_call = part.get("functionCall") or part.get("function_call")
            if isinstance(function_call, dict) and isinstance(function_call.get("name"), str):
                normalized_parts.append(
                    {
                        "functionCall": {
                            "name": function_call["name"],
                            "args": _json_object(
                                function_call.get("args"),
                                issues=issues,
                                issue_prefix=f"function_call_{part_index}",
                            ),
                        }
                    }
                )
                continue
            text = content_to_text(part.get("text", part.get("content", "")))
            normalized_parts.append({"text": text})
            if text:
                text_parts.append(text)
        if not normalized_parts:
            normalized_parts.append({"text": ""})
        normalized_candidates.append(
            {
                **candidate_value,
                "content": {"role": "model", "parts": normalized_parts},
                "finishReason": str(candidate_value.get("finishReason") or candidate_value.get("finish_reason") or "STOP"),
            }
        )

    if not normalized_candidates:
        return safe_empty_provider_result(model=default_model, raw=data, reason="missing_candidates")
    data["candidates"] = normalized_candidates
    _mark_normalization(data, valid=True, reason="normalized", issues=issues, provider_family="gemini")
    first = normalized_candidates[0]
    return ProviderResult(
        text="\n".join(text_parts),
        model=default_model,
        raw=data,
        usage=dict(data.get("usageMetadata") or data.get("usage") or {}),
        finish_reason=first.get("finishReason"),
    )


def normalize_openai_stream_data(data: dict[str, Any], *, default_model: str) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        content = content_to_text(message.get("content", data.get("content", data.get("response", ""))))
        if not content:
            return None
        choices = [{"index": 0, "delta": {"content": content}, "finish_reason": data.get("finish_reason")}]
    choice = choices[0] if isinstance(choices[0], dict) else {}
    delta = choice.get("delta")
    if not isinstance(delta, dict):
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        delta = dict(message) if message else {}
    issues: list[str] = []
    normalized_delta = _normalize_stream_delta(delta, issues=issues)
    finish_reason = _normalize_finish_reason(choice.get("finish_reason"), has_tool_calls=bool(normalized_delta.get("tool_calls")), issues=issues)
    if not normalized_delta and not finish_reason:
        return None
    raw = dict(data)
    raw["choices"] = [{"index": 0, "delta": normalized_delta, "finish_reason": finish_reason}]
    if issues:
        _mark_normalization(raw, valid=True, reason="stream_chunk_repaired", issues=issues)
    return {
        "text": _stream_delta_text(normalized_delta),
        "delta": normalized_delta,
        "model": str(data.get("model") or default_model),
        "finish_reason": finish_reason,
        "raw": raw,
    }


def _normalize_openai_choice(choice: dict[str, Any], *, index: int, issues: list[str]) -> dict[str, Any]:
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    if not message and isinstance(choice.get("delta"), dict):
        issues.append(f"choice_{index}_delta_promoted_to_message")
        message = choice["delta"]
    normalized_message: dict[str, Any] = {
        "role": _normalize_role(message.get("role"), issues=issues),
        "content": content_to_text(message.get("content")),
    }
    tool_calls = _normalize_tool_calls(message.get("tool_calls"), issues=issues)
    if tool_calls:
        normalized_message["content"] = normalized_message["content"] or None
        normalized_message["tool_calls"] = tool_calls
    function_call = _normalize_function_call(message.get("function_call"), issues=issues)
    if function_call:
        normalized_message["function_call"] = function_call
    return {
        "index": int(choice.get("index") if isinstance(choice.get("index"), int) else index),
        "message": normalized_message,
        "finish_reason": _normalize_finish_reason(
            choice.get("finish_reason"),
            has_tool_calls=bool(tool_calls or function_call),
            issues=issues,
        ),
    }


def _normalize_stream_delta(delta: dict[str, Any], *, issues: list[str]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    role = delta.get("role")
    if role is not None:
        normalized["role"] = _normalize_role(role, issues=issues)
    content = delta.get("content")
    if content is not None:
        normalized["content"] = content_to_text(content)
    tool_calls = _normalize_tool_calls(delta.get("tool_calls"), issues=issues, allow_partial=True)
    if tool_calls:
        normalized["tool_calls"] = tool_calls
    function_call = _normalize_function_call(delta.get("function_call"), issues=issues, allow_missing_name=True)
    if function_call:
        normalized["function_call"] = function_call
    return normalized


def _normalize_role(value: Any, *, issues: list[str]) -> str:
    role = str(value or "assistant")
    if role not in ALLOWED_ROLES:
        issues.append(f"invalid_role_{role}")
        return "assistant"
    return role


def _normalize_finish_reason(value: Any, *, has_tool_calls: bool = False, issues: list[str]) -> str | None:
    if value is None:
        return "tool_calls" if has_tool_calls else "stop"
    reason = str(value)
    if reason == "tool_use":
        return "tool_calls" if has_tool_calls else "stop"
    if reason.upper() == "STOP":
        return "stop"
    if reason.upper() == "MAX_TOKENS":
        return "length"
    if reason not in SANE_FINISH_REASONS:
        issues.append(f"invalid_finish_reason_{reason}")
        return "tool_calls" if has_tool_calls else "stop"
    return reason


def _normalize_tool_calls(value: Any, *, issues: list[str], allow_partial: bool = False) -> list[dict[str, Any]]:
    if value is None:
        return []
    raw_calls = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    if value is not None and not isinstance(value, list):
        issues.append("tool_calls_not_array")
    calls: list[dict[str, Any]] = []
    for index, call_value in enumerate(raw_calls):
        if not isinstance(call_value, dict):
            issues.append(f"tool_call_{index}_not_object")
            continue
        function = call_value.get("function") if isinstance(call_value.get("function"), dict) else {}
        name = function.get("name") or call_value.get("name")
        if not isinstance(name, str) or not name:
            if allow_partial:
                name = ""
            else:
                issues.append(f"tool_call_{index}_missing_name")
                continue
        args = (
            function.get("arguments")
            if "arguments" in function
            else call_value.get("arguments", call_value.get("args", call_value.get("input", {})))
        )
        arguments = _json_args(args, issues=issues, issue_prefix=f"tool_call_{index}")
        calls.append(
            {
                "id": str(call_value.get("id") or f"call_{index}"),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }
        )
    return calls


def _normalize_function_call(value: Any, *, issues: list[str], allow_missing_name: bool = False) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name:
        if not allow_missing_name:
            issues.append("function_call_missing_name")
            return None
        name = ""
    return {"name": name, "arguments": _json_args(value.get("arguments", {}), issues=issues, issue_prefix="function_call")}


def _json_args(value: Any, *, issues: list[str], issue_prefix: str) -> str:
    parsed = _json_object(value, issues=issues, issue_prefix=issue_prefix)
    return json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)


def _json_object(value: Any, *, issues: list[str], issue_prefix: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            repaired = _repair_json_object_text(text)
            try:
                parsed = json.loads(repaired)
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(text)
                except (SyntaxError, ValueError):
                    issues.append(f"{issue_prefix}_invalid_json_arguments")
                    return {}
        if isinstance(parsed, dict):
            return parsed
        issues.append(f"{issue_prefix}_arguments_not_object")
        return {}
    if value not in (None, ""):
        issues.append(f"{issue_prefix}_arguments_not_object")
    return {}


def _repair_json_object_text(value: str) -> str:
    text = value.strip()
    if text.startswith("{") and not text.endswith("}"):
        text += "}"
    return text


def _openai_tool_calls(raw: dict[str, Any]) -> list[dict[str, Any]]:
    choices = raw.get("choices") if isinstance(raw, dict) else None
    if not isinstance(choices, list) or not choices:
        return []
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    calls = message.get("tool_calls")
    if isinstance(calls, list) and calls:
        return [call for call in calls if isinstance(call, dict)]
    return [message["function_call"]] if isinstance(message.get("function_call"), dict) else []


def _anthropic_tool_uses(raw: dict[str, Any]) -> list[dict[str, Any]]:
    content = raw.get("content") if isinstance(raw, dict) else None
    if not isinstance(content, list):
        return []
    return [item for item in content if isinstance(item, dict) and item.get("type") == "tool_use"]


def _gemini_tool_calls(raw: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = raw.get("candidates") if isinstance(raw, dict) else None
    if not isinstance(candidates, list) or not candidates:
        return []
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return []
    return [part for part in parts if isinstance(part, dict) and isinstance(part.get("functionCall"), dict)]


def _has_anthropic_tool_use(blocks: list[dict[str, Any]]) -> bool:
    return any(block.get("type") == "tool_use" for block in blocks)


def _anthropic_finish_reason(reason: str | None, *, has_tool_calls: bool) -> str:
    if has_tool_calls:
        return "tool_use"
    if reason == "length":
        return "max_tokens"
    if reason in {"end_turn", "max_tokens", "stop_sequence"}:
        return reason
    return "end_turn"


def _stream_delta_text(delta: dict[str, Any]) -> str:
    content = delta.get("content")
    return content if isinstance(content, str) else content_to_text(content)


def _openai_safe_raw(*, model: str, content: str, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        **dict(raw),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def _mark_normalization(
    raw: dict[str, Any],
    *,
    valid: bool,
    reason: str,
    issues: list[str] | None = None,
    provider_family: str = "",
) -> None:
    raw["agent_hub_normalization"] = {
        "valid": valid,
        "reason": reason,
        "issues": list(issues or []),
        **({"provider_family": provider_family} if provider_family else {}),
    }
