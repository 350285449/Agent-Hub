from __future__ import annotations

import time
import uuid
from typing import Any

from .models import HubRequest, HubResponse, Message


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
    return HubRequest(
        messages=_message_list(payload.get("messages")),
        session_id=_session_id(payload, metadata, hub_options),
        route=hub_options.get("route") or payload.get("route"),
        preferred_agent=hub_options.get("agent") or payload.get("agent"),
        max_tokens=payload.get("max_completion_tokens") or payload.get("max_tokens"),
        temperature=payload.get("temperature"),
        stream=bool(payload.get("stream", False)),
        use_session_history=bool(hub_options.get("use_session_history", False)),
        api_shape="openai-chat",
        raw=payload,
        metadata=metadata,
    )


def request_from_anthropic_messages(payload: dict[str, Any]) -> HubRequest:
    metadata = dict(payload.get("metadata", {}))
    hub_options = dict(payload.get("agent_hub", {}))
    messages = _message_list(payload.get("messages"))
    system = payload.get("system")
    if system:
        messages = [{"role": "system", "content": system}, *messages]

    return HubRequest(
        messages=messages,
        session_id=_session_id(payload, metadata, hub_options),
        route=hub_options.get("route") or payload.get("route"),
        preferred_agent=hub_options.get("agent") or payload.get("agent"),
        max_tokens=payload.get("max_tokens"),
        temperature=payload.get("temperature"),
        stream=bool(payload.get("stream", False)),
        use_session_history=bool(hub_options.get("use_session_history", False)),
        api_shape="anthropic-messages",
        raw=payload,
        metadata=metadata,
    )


def openai_chat_response(response: HubResponse) -> dict[str, Any]:
    created = int(time.time())
    return {
        "id": f"chatcmpl-{response.request_id}",
        "object": "chat.completion",
        "created": created,
        "model": response.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response.text,
                },
                "finish_reason": response.finish_reason or "stop",
            }
        ],
        "usage": response.usage,
        "agent_hub": _hub_metadata(response),
    }


def anthropic_message_response(response: HubResponse) -> dict[str, Any]:
    return {
        "id": f"msg_{response.request_id}",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "text",
                "text": response.text,
            }
        ],
        "model": response.model,
        "stop_reason": _anthropic_stop_reason(response.finish_reason),
        "stop_sequence": None,
        "usage": response.usage,
        "agent_hub": _hub_metadata(response),
    }


def openai_stream_events(response: HubResponse) -> list[dict[str, Any] | str]:
    created = int(time.time())
    chunk_id = f"chatcmpl-{response.request_id}"
    return [
        {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": response.model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": response.text},
                    "finish_reason": None,
                }
            ],
            "agent_hub": _hub_metadata(response),
        },
        {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": response.model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": response.finish_reason or "stop",
                }
            ],
        },
        "[DONE]",
    ]


def anthropic_stream_events(response: HubResponse) -> list[tuple[str, dict[str, Any]]]:
    message = anthropic_message_response(response)
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


def _hub_metadata(response: HubResponse) -> dict[str, Any]:
    return {
        "session_id": response.session_id,
        "agent": response.agent,
        "provider": response.provider,
        "failover": [event.to_dict() for event in response.failover],
    }


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


def _anthropic_stop_reason(reason: str | None) -> str:
    if reason in {"max_tokens", "stop_sequence", "tool_use", "end_turn"}:
        return reason
    if reason == "length":
        return "max_tokens"
    return "end_turn"
