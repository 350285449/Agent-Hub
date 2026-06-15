from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    request_id: str = ""
    parent_id: str = ""
    span_id: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "parent_id": self.parent_id,
            "span_id": self.span_id,
            "attributes": dict(self.attributes),
        }
        return {key: value for key, value in data.items() if value not in ("", {}, None)}


def trace_context_from_request(request: Any, *, request_id: str = "") -> TraceContext:
    raw = getattr(request, "raw", {})
    raw = raw if isinstance(raw, dict) else {}
    metadata = getattr(request, "metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    explicit = _first_text(
        metadata.get("trace_id"),
        raw.get("trace_id"),
        hub.get("trace_id"),
        request_id,
    )
    trace_id = explicit if explicit.startswith("trace_") else f"trace_{_stable_hash(explicit or _seed(request))}"
    return TraceContext(
        trace_id=trace_id[:80],
        request_id=str(request_id or raw.get("request_id") or metadata.get("request_id") or "")[:120],
        parent_id=str(metadata.get("parent_trace_id") or raw.get("parent_trace_id") or hub.get("parent_trace_id") or "")[:120],
        span_id=f"span_{_stable_hash(f'{trace_id}:{time.time_ns()}')[:16]}",
        attributes={
            "session_id": str(getattr(request, "session_id", "") or "")[:120],
            "route": str(getattr(request, "route", "") or "")[:120],
            "api_shape": str(getattr(request, "api_shape", "") or "")[:80],
        },
    )


def trace_event_fields(request: Any, *, request_id: str = "") -> dict[str, Any]:
    return trace_context_from_request(request, request_id=request_id).to_dict()


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _seed(request: Any) -> str:
    return "|".join(
        (
            str(getattr(request, "session_id", "") or ""),
            str(getattr(request, "route", "") or ""),
            str(getattr(request, "task", "") or ""),
            str(time.time_ns()),
        )
    )


def _stable_hash(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:32]


__all__ = ["TraceContext", "trace_context_from_request", "trace_event_fields"]
