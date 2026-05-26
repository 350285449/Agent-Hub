from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .observability import record_event


PROVIDER_SELECTED = "provider.selected"
PROVIDER_FAILED = "provider.failed"
ROUTER_FALLBACK = "router.fallback"
TOOL_EXECUTED = "tool.executed"
STREAM_STARTED = "stream.started"
STREAM_FAILED = "stream.failed"
CONTEXT_TRUNCATED = "context.truncated"

MAX_INTERNAL_EVENT_VALUE = 4000


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
    "STREAM_FAILED",
    "STREAM_STARTED",
    "TOOL_EXECUTED",
    "record_internal_event",
]
