from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


MAX_EVENT_BYTES = 20_000
MAX_RECENT_EVENTS = 200
STREAM_FILES = {
    "requests": "request_trace.jsonl",
    "routing": "routing_decisions.jsonl",
    "events": "events.jsonl",
    "permissions": "permission_audit.jsonl",
    "security_audit": "security_audit.jsonl",
    "tools": "tool_execution_history.jsonl",
}


def record_event(state_dir: str | Path, stream: str, event: dict[str, Any]) -> None:
    filename = STREAM_FILES.get(stream, f"{stream}.jsonl")
    path = Path(state_dir) / filename
    entry = _compact_event({"time": time.time(), "stream": stream, **event})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n")
    except OSError:
        return


def recent_events(state_dir: str | Path, stream: str, *, limit: int = 50) -> list[dict[str, Any]]:
    filename = STREAM_FILES.get(stream, f"{stream}.jsonl")
    path = Path(state_dir) / filename
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-max(1, min(limit, MAX_RECENT_EVENTS)) :]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def usage_snapshot(state_dir: str | Path, provider_health: dict[str, dict[str, Any]]) -> dict[str, Any]:
    input_tokens = 0
    output_tokens = 0
    success_count = 0
    failure_count = 0
    for row in provider_health.values():
        input_tokens += _safe_int(row.get("tokens_in"))
        output_tokens += _safe_int(row.get("tokens_out"))
        success_count += _safe_int(row.get("success_count"))
        failure_count += _safe_int(row.get("failure_count"))
    tool_events = recent_events(state_dir, "tools", limit=MAX_RECENT_EVENTS)
    permission_events = recent_events(state_dir, "permissions", limit=MAX_RECENT_EVENTS)
    return {
        "object": "agent_hub.usage",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "successful_provider_calls": success_count,
        "failed_provider_calls": failure_count,
        "tool_executions": len(tool_events),
        "permission_events": len(permission_events),
        "recent_tool_executions": tool_events[-25:],
        "recent_permissions": permission_events[-25:],
    }


def metrics_snapshot(state_dir: str | Path, provider_health: dict[str, dict[str, Any]]) -> dict[str, Any]:
    usage = usage_snapshot(state_dir, provider_health)
    available = sum(1 for row in provider_health.values() if row.get("available"))
    degraded = sum(1 for row in provider_health.values() if row.get("degraded"))
    return {
        "object": "agent_hub.metrics",
        "providers_total": len(provider_health),
        "providers_available": available,
        "providers_degraded": degraded,
        "usage": {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
            "tool_executions": usage["tool_executions"],
            "permission_events": usage["permission_events"],
        },
        "routing_decisions": recent_events(state_dir, "routing", limit=50),
        "request_traces": recent_events(state_dir, "requests", limit=50),
    }


def permission_snapshot(state_dir: str | Path, *, approval_mode: str, safe_mode: bool) -> dict[str, Any]:
    events = recent_events(state_dir, "permissions", limit=100)
    return {
        "object": "agent_hub.permissions",
        "approval_mode": approval_mode,
        "safe_mode": safe_mode,
        "recent": events,
        "counts": {
            "allowed": sum(1 for item in events if item.get("allowed") is True),
            "denied": sum(1 for item in events if item.get("denied") is True),
            "approval_required": sum(1 for item in events if item.get("requires_approval") is True),
        },
    }


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(event, ensure_ascii=False, default=str)
    if len(text.encode("utf-8")) <= MAX_EVENT_BYTES:
        return event
    compact = dict(event)
    for key in ("messages", "raw", "content", "stdout", "stderr", "patch_preview"):
        if key in compact:
            compact[key] = _short(compact[key])
    text = json.dumps(compact, ensure_ascii=False, default=str)
    if len(text.encode("utf-8")) <= MAX_EVENT_BYTES:
        return compact
    return {"time": event.get("time"), "stream": event.get("stream"), "type": event.get("type"), "truncated": True}


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    return text[:2000] + ("..." if len(text) > 2000 else "")


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
