from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .payloads import content_to_text
from .providers.base import StreamChunk


@dataclass(slots=True)
class StreamNormalizationIssue:
    kind: str
    detail: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {"kind": self.kind}
        if self.detail:
            data["detail"] = self.detail
        if self.raw:
            data["raw"] = self.raw
        return data


def normalize_stream_chunk(
    value: Any,
    *,
    default_model: str,
) -> StreamChunk | None:
    """Normalize provider stream items into Agent Hub's StreamChunk contract."""

    if isinstance(value, StreamChunk):
        if not value.text and not value.delta and value.finish_reason is None:
            return None
        return value
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        return StreamChunk(text=value, delta={"content": value}, model=default_model)
    if not isinstance(value, dict):
        text = str(value)
        if not text.strip():
            return None
        return StreamChunk(text=text, delta={"content": text}, model=default_model)

    choices = value.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        delta = first.get("delta") if isinstance(first.get("delta"), dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        if not delta and message:
            delta = {"content": _message_text(message)}
        text = _delta_text(delta)
        finish_reason = first.get("finish_reason")
        if not text and not delta and finish_reason is None:
            return None
        return StreamChunk(
            text=text,
            delta=dict(delta),
            model=str(value.get("model") or default_model),
            finish_reason=str(finish_reason) if finish_reason is not None else None,
            raw=dict(value),
        )

    delta = value.get("delta") if isinstance(value.get("delta"), dict) else {}
    text = str(value.get("text") or _delta_text(delta) or "")
    if text and "content" not in delta:
        delta = {**delta, "content": text}
    finish_reason = value.get("finish_reason")
    if not text and not delta and finish_reason is None:
        return None
    return StreamChunk(
        text=text,
        delta=dict(delta),
        model=str(value.get("model") or default_model),
        finish_reason=str(finish_reason) if finish_reason is not None else None,
        raw=dict(value),
    )


def safe_stream_failure_chunk(*, model: str, message: str) -> StreamChunk:
    text = message or "[Provider stream interrupted; switched to safe termination]"
    return StreamChunk(
        text=text,
        delta={"content": text},
        model=model,
        finish_reason=None,
        raw={"agent_hub_stream_recovery": True},
    )


def _message_text(message: dict[str, Any]) -> str:
    return content_to_text(message.get("content"))


def _delta_text(delta: dict[str, Any]) -> str:
    content = delta.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return content_to_text(content)
    return ""


__all__ = [
    "StreamNormalizationIssue",
    "normalize_stream_chunk",
    "safe_stream_failure_chunk",
]
