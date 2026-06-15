from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .observability import record_event
from .tracing import trace_event_fields


PROVIDER_SELECTED = "provider.selected"
PROVIDER_FAILED = "provider.failed"
ROUTER_FALLBACK = "router.fallback"
TOOL_EXECUTED = "tool.executed"
STREAM_STARTED = "stream.started"
STREAM_FAILED = "stream.failed"
CONTEXT_TRUNCATED = "context.truncated"

MAX_INTERNAL_EVENT_VALUE = 4000


class RouterEventRecorder:
    """Records router observability events with stable request context fields."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = state_dir

    def route(
        self,
        event_type: str,
        *,
        request_id: str,
        request: Any,
        **data: Any,
    ) -> None:
        try:
            record_event(
                self.state_dir,
                "routing",
                {
                    "type": event_type,
                    "request_id": request_id,
                    **trace_event_fields(request, request_id=request_id),
                    **request_event_context(request),
                    **data,
                },
            )
        except Exception:
            return

    def internal(
        self,
        name: str,
        *,
        request_id: str,
        request: Any,
        **data: Any,
    ) -> None:
        trace = trace_event_fields(request, request_id=request_id)
        trace.pop("request_id", None)
        record_internal_event(
            self.state_dir,
            name,
            request_id=request_id,
            **trace,
            **request_event_context(request),
            **data,
        )


def request_event_context(request: Any) -> dict[str, Any]:
    return {
        "session_id": getattr(request, "session_id", ""),
        "route": getattr(request, "route", ""),
        "preferred_agent": getattr(request, "preferred_agent", None),
        "api_shape": getattr(request, "api_shape", ""),
        "source": request_source(request),
        "request_preview": request_preview(request),
    }


def request_source(request: Any) -> str:
    raw = getattr(request, "raw", {})
    raw = raw if isinstance(raw, dict) else {}
    metadata = getattr(request, "metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    for value in (
        metadata.get("source"),
        metadata.get("client"),
        raw.get("source"),
        raw.get("client"),
        hub.get("source"),
        hub.get("client"),
        getattr(request, "api_shape", ""),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return "unknown"


def request_preview(request: Any) -> str:
    task = getattr(request, "task", "")
    if isinstance(task, str) and task.strip():
        return _one_line(task)
    messages = getattr(request, "messages", [])
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").lower() not in {"user", "system"}:
            continue
        text = _content_text(message.get("content"))
        if text:
            return _one_line(text)
    return ""


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts)
    return ""


def _one_line(value: str) -> str:
    text = " ".join(str(value or "").split())
    return text[:240] + ("..." if len(text) > 240 else "")


def record_internal_event(state_dir: str | Path, name: str, **data: Any) -> None:
    """Append a compact internal event without letting observability break requests."""

    try:
        payload = {
            "type": name,
            "name": name,
            **{
                key: _sanitize_event_value(value)
                for key, value in data.items()
                if value is not None
            },
        }
        record_event(state_dir, "events", payload)
    except Exception:
        return


def _sanitize_event_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > MAX_INTERNAL_EVENT_VALUE:
            return value[:MAX_INTERNAL_EVENT_VALUE] + "..."
        return value
    if isinstance(value, list):
        return [_sanitize_event_value(item) for item in value[:100]]
    if isinstance(value, dict):
        return {
            str(key): _sanitize_event_value(item)
            for key, item in list(value.items())[:100]
            if _safe_event_key(str(key))
        }
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > MAX_INTERNAL_EVENT_VALUE:
        return text[:MAX_INTERNAL_EVENT_VALUE] + "..."
    return text


def _safe_event_key(key: str) -> bool:
    lowered = key.lower()
    return not any(secret in lowered for secret in ("api_key", "authorization", "token", "secret"))


__all__ = [
    "CONTEXT_TRUNCATED",
    "PROVIDER_FAILED",
    "PROVIDER_SELECTED",
    "ROUTER_FALLBACK",
    "RouterEventRecorder",
    "STREAM_FAILED",
    "STREAM_STARTED",
    "TOOL_EXECUTED",
    "record_internal_event",
    "request_event_context",
    "request_preview",
    "request_source",
]
