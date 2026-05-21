from __future__ import annotations

import time
import uuid
from typing import Any

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
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        if isinstance(content.get("content"), str):
            return content["content"]
    return str(content)


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
        metadata=dict(payload.get("metadata", {})),
    )


def request_from_openai_chat(payload: dict[str, Any]) -> HubRequest:
    metadata = dict(payload.get("metadata", {}))
    hub_options = dict(payload.get("agent_hub", {}))
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
    metadata = dict(payload.get("metadata", {}))
    hub_options = dict(payload.get("agent_hub", {}))
    model_route, model_agent = _routing_from_model(payload.get("model"))
    messages = _responses_input_messages(payload.get("input"))
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
    metadata = dict(payload.get("metadata", {}))
    hub_options = dict(payload.get("agent_hub", {}))
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
        message["content"] = raw_message.get("content") if isinstance(raw_message, dict) else None
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
    data: dict[str, Any] = {
        "id": f"msg_{response.request_id}",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "text",
                "text": response.text,
            }
        ],
        "model": model,
        "stop_reason": _anthropic_stop_reason(response.finish_reason),
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
    delta: dict[str, Any] = {"role": "assistant"}
    if tool_calls:
        delta["tool_calls"] = tool_calls
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
                    "finish_reason": response.finish_reason or ("tool_calls" if tool_calls else "stop"),
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
    return [
        ("message_start", {"type": "message_start", "message": message}),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": response.text},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": _anthropic_stop_reason(response.finish_reason)},
                "usage": response.usage,
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]


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
    return {
        "session_id": response.session_id,
        "agent": response.agent,
        "provider": response.provider,
        "failover": [event.to_dict() for event in response.failover],
    }


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


def _openai_message_tool_calls(raw: dict[str, Any]) -> list[dict[str, Any]]:
    choice = _first_choice(raw)
    message = choice.get("message") if isinstance(choice.get("message"), dict) else None
    if not isinstance(message, dict):
        return []
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        return [call for call in tool_calls if isinstance(call, dict)]
    return []


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
    import json

    return json.dumps(value if isinstance(value, dict) else {}, separators=(",", ":"), ensure_ascii=False)


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


def _responses_input_messages(value: Any) -> list[Message]:
    if isinstance(value, str):
        return [{"role": "user", "content": value}]
    if isinstance(value, list):
        messages: list[Message] = []
        for item in value:
            if isinstance(item, dict) and item.get("type") == "message":
                role = item.get("role", "user")
                messages.append({"role": role, "content": _responses_content_text(item.get("content"))})
            elif isinstance(item, dict) and "role" in item:
                message = dict(item)
                message["content"] = _responses_content_text(item.get("content"))
                messages.append(message)
            elif isinstance(item, str):
                messages.append({"role": "user", "content": item})
        return messages
    return []


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


def _anthropic_stop_reason(reason: str | None) -> str:
    if reason in {"max_tokens", "stop_sequence", "tool_use", "end_turn"}:
        return reason
    if reason == "length":
        return "max_tokens"
    return "end_turn"
