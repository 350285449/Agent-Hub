from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

from .capabilities import agent_supports_tools
from .config import AgentConfig, HubConfig, normalize_provider
from .context import content_to_text
from .models import HubRequest, ProviderResult


TOOL_COMPATIBILITY_MARKER = "agent_hub_tool_compatibility"


def universal_compatibility_enabled(config: HubConfig) -> bool:
    mode = getattr(config, "compatibility_mode", {}) or {}
    return bool(mode.get("universal_routing", True))


def tool_emulation_enabled(config: HubConfig) -> bool:
    mode = getattr(config, "compatibility_mode", {}) or {}
    return universal_compatibility_enabled(config) and bool(mode.get("emulate_tools", True))


def tool_compatibility_mode(config: HubConfig, agent: AgentConfig) -> str:
    if agent_supports_tools(agent):
        return "native"
    if agent_can_emulate_tools(config, agent):
        return "emulated"
    return "unavailable"


def tool_emulation_can_handle(config: HubConfig, request: HubRequest) -> bool:
    return tool_emulation_enabled(config) and bool(request_tool_specs(request))


def agent_can_emulate_tools(config: HubConfig, agent: AgentConfig) -> bool:
    return (
        tool_emulation_enabled(config)
        and normalize_provider(agent.provider) not in {"echo", "local-research"}
    )


def request_tool_specs(request: HubRequest) -> list[dict[str, Any]]:
    raw = request.raw if isinstance(request.raw, dict) else {}
    sources = [
        raw.get("agent_hub_tools"),
        raw.get("tools"),
        raw.get("functions"),
    ]
    specs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, list):
            continue
        for item in source:
            spec = _tool_spec(item)
            if spec is None or spec["name"] in seen:
                continue
            seen.add(spec["name"])
            specs.append(spec)
    return specs


def prepare_tool_compatibility_request(
    config: HubConfig,
    agent: AgentConfig,
    request: HubRequest,
) -> HubRequest:
    if _agent_runner_managed_request(request):
        return request
    specs = request_tool_specs(request)
    existing = _request_tool_compatibility(request)
    if not specs and existing.get("mode") == "emulated":
        specs = [
            dict(spec)
            for spec in existing.get("tools", [])
            if isinstance(spec, dict) and isinstance(spec.get("name"), str)
        ]
    if agent_supports_tools(agent) or not agent_can_emulate_tools(config, agent) or not specs:
        return request

    raw = dict(request.raw or {})
    hub = dict(raw.get("agent_hub") or {})
    client_owned_tools = bool(
        (isinstance(raw.get("tools"), list) and raw["tools"])
        or (isinstance(raw.get("functions"), list) and raw["functions"])
    ) and not bool(isinstance(raw.get("agent_hub_tools"), list) and raw["agent_hub_tools"])
    compatibility = {
        "mode": "emulated",
        "native_tool_support": False,
        "client_owned_tools": client_owned_tools or bool(existing.get("client_owned_tools")),
        "provider": agent.provider,
        "model": agent.model,
        "tool_names": [spec["name"] for spec in specs],
        "tools": specs,
    }
    hub["tool_compatibility"] = compatibility
    raw["agent_hub"] = hub
    for key in ("agent_hub_tools", "function_call", "functions", "tool_choice", "tools"):
        raw.pop(key, None)

    metadata = dict(request.metadata or {})
    metadata["tool_compatibility"] = compatibility
    messages = _emulation_messages(request.messages, specs)
    return replace(request, raw=raw, metadata=metadata, messages=messages)


def normalize_emulated_tool_result(
    request: HubRequest,
    result: ProviderResult,
) -> ProviderResult:
    compatibility = _request_tool_compatibility(request)
    if compatibility.get("mode") != "emulated" or _raw_has_tool_calls(result.raw):
        return result

    allowed = {
        str(name)
        for name in compatibility.get("tool_names", [])
        if isinstance(name, str) and name
    }
    calls = _tool_calls_from_text(result.text, allowed=allowed)
    if not calls:
        return result

    raw = dict(result.raw or {})
    choices = raw.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        first = dict(choices[0])
        first["message"] = {
            "role": "assistant",
            "content": None,
            "tool_calls": calls,
        }
        first["finish_reason"] = "tool_calls"
        raw["choices"] = [first, *choices[1:]]
    else:
        raw["choices"] = [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": calls,
                },
                "finish_reason": "tool_calls",
            }
        ]
    bridge = dict(raw.get("agent_hub_compatibility") or {})
    bridge["tool_mode"] = "emulated"
    bridge["tool_names"] = [call["function"]["name"] for call in calls]
    raw["agent_hub_compatibility"] = bridge
    return replace(result, text="", raw=raw, finish_reason="tool_calls")


def _emulation_messages(
    messages: list[dict[str, Any]],
    specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = [
        _text_only_message(message)
        for message in messages
        if not (isinstance(message, dict) and message.get(TOOL_COMPATIBILITY_MARKER))
    ]
    instruction = {
        "role": "system",
        "content": (
            "Agent Hub universal compatibility bridge: this provider does not expose native "
            "tool calling. When a tool is needed, respond with only one JSON object in this "
            'form: {"tool_call":{"name":"tool_name","arguments":{}}}. Use only a listed '
            "tool and always make arguments an object. To answer without a tool, respond "
            "normally and do not wrap the answer in JSON.\nAvailable tools:\n"
            + json.dumps(specs, ensure_ascii=False, separators=(",", ":"))
        ),
        TOOL_COMPATIBILITY_MARKER: True,
    }
    return [instruction, *normalized]


def _text_only_message(message: dict[str, Any]) -> dict[str, Any]:
    copied = dict(message)
    role = str(copied.get("role") or "user")
    content = content_to_text(copied.get("content"))
    calls = _message_tool_calls(copied)
    if calls:
        rendered = json.dumps({"tool_calls": calls}, ensure_ascii=False, separators=(",", ":"))
        content = "\n".join(part for part in (content, rendered) if part)
    if role == "tool":
        identity = (
            copied.get("name")
            or copied.get("tool_call_id")
            or copied.get("tool_use_id")
            or "tool"
        )
        content = f"Tool result for {identity}:\n{content}"
        role = "user"
    copied["role"] = role
    copied["content"] = content
    copied.pop("function_call", None)
    copied.pop("tool_calls", None)
    return copied


def _message_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls")
    if isinstance(calls, list):
        return [dict(call) for call in calls if isinstance(call, dict)]
    function_call = message.get("function_call")
    if isinstance(function_call, dict):
        return [{"type": "function", "function": dict(function_call)}]
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [
        dict(item)
        for item in content
        if isinstance(item, dict) and item.get("type") in {"function_call", "tool_use"}
    ]


def _tool_spec(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    function = value.get("function") if isinstance(value.get("function"), dict) else value
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None
    parameters = (
        function.get("parameters")
        or function.get("input_schema")
        or {"type": "object", "properties": {}}
    )
    if not isinstance(parameters, dict):
        parameters = {"type": "object", "properties": {}}
    return {
        "name": name,
        "description": str(function.get("description") or ""),
        "parameters": parameters,
    }


def _request_tool_compatibility(request: HubRequest) -> dict[str, Any]:
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    value = metadata.get("tool_compatibility")
    if isinstance(value, dict):
        return value
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    value = hub.get("tool_compatibility")
    return value if isinstance(value, dict) else {}


def _agent_runner_managed_request(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    return isinstance(raw.get("agent_hub_runtime"), dict)


def _raw_has_tool_calls(raw: dict[str, Any]) -> bool:
    if not isinstance(raw, dict):
        return False
    choices = raw.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and (
            isinstance(message.get("function_call"), dict)
            or isinstance(message.get("tool_calls"), list) and message["tool_calls"]
        ):
            return True
    content = raw.get("content")
    if isinstance(content, list) and any(
        isinstance(item, dict) and item.get("type") == "tool_use"
        for item in content
    ):
        return True
    candidates = raw.get("candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        content = candidates[0].get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        return isinstance(parts, list) and any(
            isinstance(part, dict) and (
                isinstance(part.get("functionCall"), dict)
                or isinstance(part.get("function_call"), dict)
            )
            for part in parts
        )
    return False


def _tool_calls_from_text(text: str, *, allowed: set[str]) -> list[dict[str, Any]]:
    value = _json_value_from_text(text)
    if value is None:
        return []
    raw_calls: Any = value
    if isinstance(value, dict):
        raw_calls = (
            value.get("tool_calls")
            or value.get("tool_call")
            or value.get("function_call")
            or value
        )
    if isinstance(raw_calls, dict):
        raw_calls = [raw_calls]
    if not isinstance(raw_calls, list):
        return []

    calls: list[dict[str, Any]] = []
    for index, item in enumerate(raw_calls):
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else item
        name = function.get("name")
        if not isinstance(name, str) or not name or allowed and name not in allowed:
            continue
        arguments = function.get("arguments", function.get("input", function.get("args", {})))
        calls.append(
            {
                "id": str(item.get("id") or f"emulated_call_{index}"),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(
                        _arguments_object(arguments),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            }
        )
    return calls


def _json_value_from_text(text: str) -> Any:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    candidates = [stripped]
    candidates.extend(
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*(.*?)```", stripped, re.IGNORECASE | re.DOTALL)
    )
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        for index, char in enumerate(candidate):
            if char not in "[{":
                continue
            try:
                value, _end = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            return value
    return None


def _arguments_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


__all__ = [
    "TOOL_COMPATIBILITY_MARKER",
    "agent_can_emulate_tools",
    "normalize_emulated_tool_result",
    "prepare_tool_compatibility_request",
    "request_tool_specs",
    "tool_compatibility_mode",
    "tool_emulation_can_handle",
    "tool_emulation_enabled",
    "universal_compatibility_enabled",
]
