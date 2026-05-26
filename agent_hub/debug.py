from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


MAX_DEBUG_VALUE_CHARS = 20_000
SECRET_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "password",
    "secret",
    "token",
    "x-api-key",
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)ghp_[A-Za-z0-9_]{12,}"),
)


def debug_dir_for_state(state_dir: str | Path) -> Path:
    """Return the sibling debug directory for an Agent Hub state directory."""

    return Path(state_dir).expanduser().resolve().parent / "debug"


def provider_debug_context(
    *,
    enabled: bool,
    debug_dir: str | Path,
    request_id: str,
    provider: str,
    provider_name: str,
    model: str,
    routing_mode: str,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
    provider_limit: int | None,
    stream_id: str | None = None,
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "debug_dir": str(debug_dir),
        "request_id": request_id,
        "provider": provider,
        "provider_name": provider_name,
        "model": model,
        "routing_mode": routing_mode,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "provider_limit": provider_limit,
        "stream_id": stream_id,
    }


def log_provider_debug_event(context: dict[str, Any] | None, event: dict[str, Any]) -> None:
    """Append a redacted, truncation-safe provider debug event.

    Debug logging is deliberately best-effort: provider calls must never fail
    because the local trace file cannot be written.
    """

    if not isinstance(context, dict) or not context.get("enabled"):
        return
    debug_dir = context.get("debug_dir")
    request_id = str(context.get("request_id") or "unknown")
    if not isinstance(debug_dir, str) or not debug_dir:
        return
    entry = {
        "time": time.time(),
        "request_id": request_id,
        "provider_request_id": event.get("provider_request_id"),
        "stream_id": context.get("stream_id") or event.get("stream_id"),
        "provider": context.get("provider"),
        "provider_name": context.get("provider_name"),
        "model": context.get("model"),
        "routing_mode": context.get("routing_mode"),
        "estimated_tokens": {
            "input": context.get("estimated_input_tokens"),
            "output": context.get("estimated_output_tokens"),
            "provider_limit": context.get("provider_limit"),
        },
        **event,
    }
    safe = redact_and_truncate(entry)
    try:
        path = Path(debug_dir)
        path.mkdir(parents=True, exist_ok=True)
        trace_path = path / f"{_safe_filename(request_id)}.jsonl"
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe, ensure_ascii=False, default=str) + "\n")
    except OSError:
        return


def redact_and_truncate(value: Any, *, max_chars: int = MAX_DEBUG_VALUE_CHARS) -> Any:
    redacted = _redact(value)
    return _truncate(redacted, max_chars=max_chars)


def _redact(value: Any, key: str = "") -> Any:
    if _secret_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        text = value
        for pattern in SECRET_VALUE_PATTERNS:
            text = pattern.sub(_redacted_secret_match, text)
        return text
    return value


def _truncate(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, dict):
        return {key: _truncate(item, max_chars=max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate(item, max_chars=max_chars) for item in value]
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        return value[: max(0, max_chars - 32)] + f"... [truncated {len(value)} chars]"
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return value
    if len(text) <= max_chars:
        return value
    return text[: max(0, max_chars - 32)] + f"... [truncated {len(text)} chars]"


def _secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(marker in lowered for marker in SECRET_KEY_MARKERS)


def _redacted_secret_match(match: re.Match[str]) -> str:
    if match.lastindex:
        return f"{match.group(1)}[REDACTED]"
    return "[REDACTED]"


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return cleaned[:120] or "unknown"
