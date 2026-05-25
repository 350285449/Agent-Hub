from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .context import (
    compatibility_mode_enabled,
    content_to_text as structured_content_to_text,
    enrich_metadata_with_context,
)
from .models import HubRequest, HubResponse, Message


ROUTE_MODEL_ALIASES = {
    "agent-hub": "cloud-agent",
    "agent-hub-cloud": "cloud-agent",
    "agent-hub-coding": "coding",
    "agent-hub-tools": "coding",
    "agent-hub-agent": "coding",
    "agent-hub-local": "local-agent",
    "agent-hub-research": "research",
    "cloud-agent": "cloud-agent",
    "hybrid-agent": "hybrid-agent",
    "local-agent": "local-agent",
    "coding": "coding",
    "research": "research",
}


def content_to_text(content: Any) -> str:
    return structured_content_to_text(content)


def request_text(request: HubRequest) -> str:
    parts = [request.task or "", request.context or ""]
    parts.extend(content_to_text(message.get("content")) for message in request.messages)
    return "\n".join(part for part in parts if part)


def request_from_payload(payload: dict[str, Any], api_shape: str = "native") -> HubRequest:
    if api_shape == "openai-chat":
        return request_from_openai_chat(payload)
    if api_shape == "openai-responses":
        return request_from_openai_responses(payload)
    if api_shape == "anthropic-messages":
        return request_from_anthropic_messages(payload)
    return request_from_native(payload)


def request_from_native(payload: dict[str, Any]) -> HubRequest:
    session_id = _session_id(payload)
    messages = _message_list(payload.get("messages"))
    task = payload.get("task") or payload.get("input") or payload.get("prompt")
    context = payload.get("context")
    if not messages:
        messages = _messages_from_task(task=task, context=context)

    return HubRequest(
        messages=messages,
        session_id=session_id,
        task=task,
        context=context,
        route=payload.get("route"),
        preferred_agent=payload.get("agent") or payload.get("preferred_agent"),
        max_tokens=payload.get("max_tokens"),
        temperature=payload.get("temperature"),
        stream=bool(payload.get("stream", False)),
        use_session_history=bool(payload.get("use_session_history", True)),
        api_shape="native",
        raw=payload,
        metadata=enrich_metadata_with_context(payload, _dict_value(payload.get("metadata"))),
    )


def request_from_openai_chat(payload: dict[str, Any]) -> HubRequest:
    metadata = enrich_metadata_with_context(payload, _dict_value(payload.get("metadata")))
    hub_options = _dict_value(payload.get("agent_hub"))
    model_route, model_agent = _routing_from_model(payload.get("model"))
    return HubRequest(
        messages=_message_list(payload.get("messages")),
        session_id=_session_id(payload, metadata, hub_options),
        route=hub_options.get("route") or payload.get("route") or model_route,
        preferred_agent=hub_options.get("agent") or payload.get("agent") or model_agent,
        max_tokens=payload.get("max_completion_tokens") or payload.get("max_tokens"),
        temperature=payload.get("temperature"),
        stream=bool(payload.get("stream", False)),
        use_session_history=bool(hub_options.get("use_session_history", False)),
        api_shape="openai-chat",
        raw=payload,
        metadata=metadata,
    )


def request_from_openai_responses(payload: dict[str, Any]) -> HubRequest:
    metadata = enrich_metadata_with_context(payload, _dict_value(payload.get("metadata")))
    hub_options = _dict_value(payload.get("agent_hub"))
    model_route, model_agent = _routing_from_model(payload.get("model"))
    messages = _responses_input_messages(
        payload.get("input"),
        preserve_structured=compatibility_mode_enabled(payload),
    )
    instructions = payload.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        messages = [{"role": "system", "content": instructions}, *messages]
    return HubRequest(
        messages=messages,
        session_id=_session_id(payload, metadata, hub_options),
        route=hub_options.get("route") or payload.get("route") or model_route,
        preferred_agent=hub_options.get("agent") or payload.get("agent") or model_agent,
        max_tokens=payload.get("max_output_tokens") or payload.get("max_tokens"),
        temperature=payload.get("temperature"),
        stream=bool(payload.get("stream", False)),
        use_session_history=bool(hub_options.get("use_session_history", False)),
        api_shape="openai-responses",
        raw=payload,
        metadata=metadata,
    )


def request_from_anthropic_messages(payload: dict[str, Any]) -> HubRequest:
    metadata = enrich_metadata_with_context(payload, _dict_value(payload.get("metadata")))
    hub_options = _dict_value(payload.get("agent_hub"))
    model_route, model_agent = _routing_from_model(payload.get("model"))
    messages = _message_list(payload.get("messages"))
    system = payload.get("system")
    if system:
        messages = [{"role": "system", "content": system}, *messages]

    return HubRequest(
        messages=messages,
        session_id=_session_id(payload, metadata, hub_options),
        route=hub_options.get("route") or payload.get("route") or model_route,
        preferred_agent=hub_options.get("agent") or payload.get("agent") or model_agent,
        max_tokens=payload.get("max_tokens"),
        temperature=payload.get("temperature"),
        stream=bool(payload.get("stream", False)),
        use_session_history=bool(hub_options.get("use_session_history", False)),
        api_shape="anthropic-messages",
        raw=payload,
        metadata=metadata,
    )


def openai_chat_response(
    response: HubResponse,
    include_routing_details: bool = False,
) -> dict[str, Any]:
    created = int(time.time())
    model = response.public_model or response.model
    raw_choice = _first_choice(response.raw)
    raw_message = raw_choice.get("message") if isinstance(raw_choice.get("message"), dict) else {}
    tool_calls = _openai_tool_calls_from_raw(response.raw)
    function_call = raw_message.get("function_call") if isinstance(raw_message, dict) else None
    message: dict[str, Any] = {
        "role": str(raw_message.get("role") or "assistant") if isinstance(raw_message, dict) else "assistant",
        "content": response.text,
    }
    if tool_calls:
        raw_content = raw_message.get("content") if isinstance(raw_message, dict) else None
        message["content"] = raw_content if raw_content is not None else (response.text or None)
        message["tool_calls"] = tool_calls
    if isinstance(function_call, dict):
        message["function_call"] = function_call
    data: dict[str, Any] = {
        "id": f"chatcmpl-{response.request_id}",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": response.finish_reason or raw_choice.get("finish_reason") or "stop",
            }
        ],
        "usage": response.usage,
    }
    if include_routing_details:
        data["agent_hub"] = _hub_metadata(response)
    _add_research_metadata(data, response)
    return data


def anthropic_message_response(
    response: HubResponse,
    include_routing_details: bool = False,
) -> dict[str, Any]:
    model = response.public_model or response.model
    content = _anthropic_content_blocks(response)
    data: dict[str, Any] = {
        "id": f"msg_{response.request_id}",
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": model,
        "stop_reason": _anthropic_stop_reason(
            response.finish_reason,
            has_tool_use=any(block.get("type") == "tool_use" for block in content),
        ),
        "stop_sequence": None,
        "usage": response.usage,
    }
    if include_routing_details:
        data["agent_hub"] = _hub_metadata(response)
        _add_research_metadata(data["agent_hub"], response)
    else:
        _add_research_metadata(data, response)
    return data


def openai_response_response(
    response: HubResponse,
    include_routing_details: bool = False,
) -> dict[str, Any]:
    created = int(time.time())
    model = response.public_model or response.model
    tool_calls = _openai_tool_calls_from_raw(response.raw)
    if tool_calls:
        output = [
            {
                "id": call.get("id") or f"call_{index}",
                "type": "function_call",
                "status": "completed",
                "call_id": call.get("id") or f"call_{index}",
                "name": (call.get("function") or {}).get("name"),
                "arguments": (call.get("function") or {}).get("arguments", "{}"),
            }
            for index, call in enumerate(tool_calls)
            if isinstance(call.get("function"), dict)
        ]
    else:
        output = [
            {
                "id": f"msg_{response.request_id}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": response.text}],
            }
        ]
    data: dict[str, Any] = {
        "id": f"resp_{response.request_id}",
        "object": "response",
        "created_at": created,
        "status": "completed",
        "model": model,
        "output": output,
        "output_text": response.text,
        "usage": response.usage,
    }
    if include_routing_details:
        data["agent_hub"] = _hub_metadata(response)
    _add_research_metadata(data, response)
    return data


def openai_stream_events(
    response: HubResponse,
    include_routing_details: bool = False,
) -> list[dict[str, Any] | str]:
    created = int(time.time())
    chunk_id = f"chatcmpl-{response.request_id}"
    model = response.public_model or response.model
    tool_calls = _openai_tool_calls_from_raw(response.raw)
    function_call = _openai_function_call_from_raw(response.raw)
    delta: dict[str, Any] = {"role": "assistant"}
    if tool_calls:
        delta["tool_calls"] = tool_calls
    elif function_call:
        delta["function_call"] = function_call
    else:
        delta["content"] = response.text
    first_event: dict[str, Any] = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": None,
            }
        ],
    }
    if include_routing_details:
        first_event["agent_hub"] = _hub_metadata(response)
    return [
        first_event,
        {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": (
                        response.finish_reason
                        or ("tool_calls" if tool_calls else "function_call" if delta.get("function_call") else "stop")
                    ),
                }
            ],
        },
        "[DONE]",
    ]


def anthropic_stream_events(
    response: HubResponse,
    include_routing_details: bool = False,
) -> list[tuple[str, dict[str, Any]]]:
    message = anthropic_message_response(
        response,
        include_routing_details=include_routing_details,
    )
    started = dict(message)
    started["content"] = []
    started["stop_reason"] = None
    events: list[tuple[str, dict[str, Any]]] = [
        ("message_start", {"type": "message_start", "message": started}),
    ]
    for index, block in enumerate(message["content"]):
        block_type = block.get("type")
        if block_type == "tool_use":
            input_payload = block.get("input") if isinstance(block.get("input"), dict) else {}
            events.extend(
                [
                    (
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": index,
                            "content_block": {
                                "type": "tool_use",
                                "id": block.get("id") or f"toolu_{index}",
                                "name": block.get("name") or "",
                                "input": {},
                            },
                        },
                    ),
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {
                                "type": "input_json_delta",
                                "partial_json": json_dumps_compact(input_payload),
                            },
                        },
                    ),
                    ("content_block_stop", {"type": "content_block_stop", "index": index}),
                ]
            )
            continue
        text = str(block.get("text") or "")
        events.extend(
            [
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": index,
                        "content_block": {"type": "text", "text": ""},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": text},
                    },
                ),
                ("content_block_stop", {"type": "content_block_stop", "index": index}),
            ]
        )
    events.extend(
        [
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": message["stop_reason"]},
                    "usage": response.usage,
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )
    return events


def openai_response_stream_events(
    response: HubResponse,
    include_routing_details: bool = False,
) -> list[dict[str, Any] | str]:
    data = openai_response_response(
        response,
        include_routing_details=include_routing_details,
    )
    return [
        {"type": "response.created", "response": {**data, "output": []}},
        *(
            [
                {
                    "type": "response.output_text.delta",
                    "item_id": data["output"][0]["id"],
                    "output_index": 0,
                    "content_index": 0,
                    "delta": response.text,
                }
            ]
            if response.text and data["output"] and data["output"][0].get("type") == "message"
            else []
        ),
        {"type": "response.completed", "response": data},
        "[DONE]",
    ]


def _hub_metadata(response: HubResponse) -> dict[str, Any]:
    data = {
        "session_id": response.session_id,
        "agent": response.agent,
        "provider": response.provider,
        "model": response.model,
        "active_model": {
            "agent": response.agent,
            "provider": response.provider,
            "model": response.model,
        },
        "failover": [event.to_dict() for event in response.failover],
    }
    raw_metadata = response.raw.get("agent_hub") if isinstance(response.raw, dict) else None
    if isinstance(raw_metadata, dict):
        for key in (
            "limits",
            "selected_health",
            "active_model",
            "failed_models",
            "fallback_models",
            "session_models",
            "context_usage",
            "token_budget",
            "confidence",
        ):
            if key in raw_metadata:
                data[key] = raw_metadata[key]
    if "failed_models" not in data:
        data["failed_models"] = [event.to_dict() for event in response.failover]
    if "fallback_models" not in data:
        data["fallback_models"] = [event.to_dict() for event in response.failover]
    return data


def _routing_from_model(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, None
    model = value.strip()
    if not model:
        return None, None
    normalized = model.lower()
    if normalized in ROUTE_MODEL_ALIASES:
        return ROUTE_MODEL_ALIASES[normalized], None
    for prefix in ("agent:", "agent-hub-agent:"):
        if normalized.startswith(prefix):
            agent = model[len(prefix) :].strip()
            return None, agent or None
    if normalized.startswith("agent-hub/"):
        route = normalized.split("/", 1)[1].strip()
        return route or None, None
    return None, None


def _first_choice(raw: dict[str, Any]) -> dict[str, Any]:
    choices = raw.get("choices") if isinstance(raw, dict) else None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0]
    return {}


def _openai_tool_calls_from_raw(raw: dict[str, Any]) -> list[dict[str, Any]]:
    direct = _openai_message_tool_calls(raw)
    if direct:
        return direct
    anthropic = _anthropic_tool_calls(raw)
    if anthropic:
        return anthropic
    return _gemini_tool_calls(raw)


def _anthropic_content_blocks(response: HubResponse) -> list[dict[str, Any]]:
    raw_content = _anthropic_content_from_raw(response.raw)
    if raw_content:
        return raw_content
    tool_uses = _anthropic_tool_uses_from_raw(response.raw)
    if tool_uses:
        blocks: list[dict[str, Any]] = []
        if response.text:
            blocks.append({"type": "text", "text": response.text})
        blocks.extend(tool_uses)
        return blocks
    return [{"type": "text", "text": response.text}]


def _anthropic_content_from_raw(raw: dict[str, Any]) -> list[dict[str, Any]]:
    content = raw.get("content") if isinstance(raw, dict) else None
    if not isinstance(content, list):
        return []
    blocks: list[dict[str, Any]] = []
    for index, item in enumerate(content):
        if not isinstance(item, dict):
            continue
        block_type = item.get("type")
        if block_type == "text":
            blocks.append({"type": "text", "text": str(item.get("text") or "")})
        elif block_type == "tool_use" and isinstance(item.get("name"), str):
            input_payload = item.get("input") if isinstance(item.get("input"), dict) else {}
            blocks.append(
                {
                    "type": "tool_use",
                    "id": str(item.get("id") or f"toolu_{index}"),
                    "name": item["name"],
                    "input": input_payload,
                }
            )
    return blocks


def _anthropic_tool_uses_from_raw(raw: dict[str, Any]) -> list[dict[str, Any]]:
    direct = [
        block
        for block in _anthropic_content_from_raw(raw)
        if block.get("type") == "tool_use"
    ]
    if direct:
        return direct

    calls = _openai_message_tool_calls(raw)
    function_call = _openai_function_call_from_raw(raw)
    if not calls and function_call:
        calls = [
            {
                "id": "call_0",
                "type": "function",
                "function": function_call,
            }
        ]
    if not calls:
        calls = _gemini_tool_calls(raw)
    blocks: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        block = _openai_tool_call_to_anthropic(call, index)
        if block:
            blocks.append(block)
    return blocks


def _openai_tool_call_to_anthropic(call: dict[str, Any], index: int) -> dict[str, Any] | None:
    function = call.get("function") if isinstance(call, dict) else None
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None
    arguments = function.get("arguments", {})
    return {
        "type": "tool_use",
        "id": str(call.get("id") or f"toolu_{index}"),
        "name": name,
        "input": _json_object(arguments),
    }


def _openai_message_tool_calls(raw: dict[str, Any]) -> list[dict[str, Any]]:
    choice = _first_choice(raw)
    message = choice.get("message") if isinstance(choice.get("message"), dict) else None
    if not isinstance(message, dict):
        return []
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        return [call for call in tool_calls if isinstance(call, dict)]
    return []


def _openai_function_call_from_raw(raw: dict[str, Any]) -> dict[str, Any] | None:
    choice = _first_choice(raw)
    message = choice.get("message") if isinstance(choice.get("message"), dict) else None
    if not isinstance(message, dict):
        return None
    function_call = message.get("function_call")
    return function_call if isinstance(function_call, dict) else None


def _anthropic_tool_calls(raw: dict[str, Any]) -> list[dict[str, Any]]:
    content = raw.get("content") if isinstance(raw, dict) else None
    if not isinstance(content, list):
        return []
    calls: list[dict[str, Any]] = []
    for index, item in enumerate(content):
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        calls.append(
            {
                "id": str(item.get("id") or f"call_{index}"),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json_dumps_compact(item.get("input", {})),
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
        if not isinstance(name, str):
            continue
        calls.append(
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json_dumps_compact(function_call.get("args", {})),
                },
            }
        )
    return calls


def json_dumps_compact(value: Any) -> str:
    return json.dumps(value if isinstance(value, dict) else {}, separators=(",", ":"), ensure_ascii=False)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _add_research_metadata(data: dict[str, Any], response: HubResponse) -> None:
    if response.citations:
        data["citations"] = response.citations
    if response.search_results:
        data["search_results"] = response.search_results
    if response.images:
        data["images"] = response.images
    if response.related_questions:
        data["related_questions"] = response.related_questions


def _session_id(*sources: dict[str, Any]) -> str:
    for source in sources:
        for key in ("session_id", "conversation_id", "thread_id"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return uuid.uuid4().hex


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _message_list(value: Any) -> list[Message]:
    if not isinstance(value, list):
        return []
    messages: list[Message] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        role = item.get("role", "user")
        content = item.get("content", "")
        message = dict(item)
        message["role"] = role
        message["content"] = content
        messages.append(message)
    return messages


def _messages_from_task(task: Any, context: Any) -> list[Message]:
    parts: list[str] = []
    if context:
        parts.append(f"Context:\n{content_to_text(context)}")
    if task:
        parts.append(f"Task:\n{content_to_text(task)}")
    return [{"role": "user", "content": "\n\n".join(parts)}] if parts else []


def _responses_input_messages(value: Any, *, preserve_structured: bool = False) -> list[Message]:
    if isinstance(value, str):
        return [{"role": "user", "content": value}]
    if isinstance(value, list):
        messages: list[Message] = []
        for item in value:
            if isinstance(item, dict) and item.get("type") == "message":
                role = item.get("role", "user")
                messages.append(
                    {
                        "role": role,
                        "content": _responses_content_value(
                            item.get("content"),
                            preserve_structured=preserve_structured,
                        ),
                    }
                )
            elif isinstance(item, dict) and "role" in item:
                message = dict(item)
                message["content"] = _responses_content_value(
                    item.get("content"),
                    preserve_structured=preserve_structured,
                )
                messages.append(message)
            elif isinstance(item, dict) and item.get("type") in {"function_call", "tool_use"}:
                messages.append({"role": "assistant", "content": [dict(item)] if preserve_structured else content_to_text(item)})
            elif isinstance(item, dict) and item.get("type") in {"function_call_output", "tool_result"}:
                messages.append({"role": "tool", "content": [dict(item)] if preserve_structured else content_to_text(item)})
            elif isinstance(item, str):
                messages.append({"role": "user", "content": item})
        return messages
    return []


def _responses_content_value(value: Any, *, preserve_structured: bool) -> Any:
    if preserve_structured and isinstance(value, list):
        return [dict(item) if isinstance(item, dict) else item for item in value]
    return _responses_content_text(value)


def _responses_content_text(value: Any) -> str:
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(parts)
    return content_to_text(value)


def _anthropic_stop_reason(reason: str | None, *, has_tool_use: bool = False) -> str:
    if has_tool_use:
        return "tool_use"
    if reason in {"max_tokens", "stop_sequence", "tool_use", "end_turn"}:
        return reason
    if reason in {"tool_calls", "function_call"}:
        return "tool_use"
    if reason == "length":
        return "max_tokens"
    return "end_turn"
