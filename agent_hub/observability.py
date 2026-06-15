from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


MAX_EVENT_BYTES = 20_000
MAX_RECENT_EVENTS = 200
STREAM_FILES = {
    "requests": "request_trace.jsonl",
    "routing": "routing_decisions.jsonl",
    "events": "events.jsonl",
    "logs": "structured_logs.jsonl",
    "permissions": "permission_audit.jsonl",
    "security_audit": "security_audit.jsonl",
    "enterprise_audit": "enterprise_audit.jsonl",
    "audit": "local_audit.jsonl",
    "tools": "tool_execution_history.jsonl",
    "workflows": "workflow_execution.jsonl",
    "adaptive": "adaptive_learning_events.jsonl",
    "token_budget": "token_budget_ledger.jsonl",
}
DEFAULT_COMPACT_STREAMS = tuple(STREAM_FILES.keys())


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


def compact_event_stream(
    state_dir: str | Path,
    stream: str,
    *,
    retention_days: int | None = None,
    max_events: int | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Prune one JSONL observability stream by age and count."""

    filename = STREAM_FILES.get(stream, f"{stream}.jsonl")
    path = Path(state_dir) / filename
    rows, invalid_lines = _read_event_rows(path)
    original_count = len(rows)
    cutoff = _retention_cutoff(retention_days, now=now)
    if cutoff is not None:
        rows = [row for row in rows if _event_time(row) is None or _event_time(row) >= cutoff]
    if max_events is not None:
        keep = max(0, int(max_events or 0))
        rows = rows[-keep:] if keep else []
    rewritten = False
    if invalid_lines or len(rows) != original_count:
        _write_event_rows(path, rows)
        rewritten = True
    return {
        "stream": stream,
        "file": filename,
        "original_count": original_count,
        "retained_count": len(rows),
        "removed_count": max(0, original_count - len(rows)),
        "invalid_lines": invalid_lines,
        "rewritten": rewritten,
        "retention_days": retention_days,
        "max_events": max_events,
    }


def compact_observability_state(
    state_dir: str | Path,
    *,
    retention_days: int | None = None,
    max_events_per_stream: int | None = None,
    streams: list[str] | tuple[str, ...] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Compact the local analytics JSONL files without affecting runtime behavior."""

    selected = list(streams or DEFAULT_COMPACT_STREAMS)
    reports = [
        compact_event_stream(
            state_dir,
            stream,
            retention_days=retention_days,
            max_events=max_events_per_stream,
            now=now,
        )
        for stream in selected
    ]
    return {
        "object": "agent_hub.analytics_compaction",
        "state_dir": str(Path(state_dir)),
        "retention_days": retention_days,
        "max_events_per_stream": max_events_per_stream,
        "streams": reports,
        "removed_count": sum(int(item.get("removed_count") or 0) for item in reports),
        "rewritten_streams": [
            str(item.get("stream"))
            for item in reports
            if item.get("rewritten")
        ],
    }


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


def audit_snapshot(state_dir: str | Path, *, limit: int = 100) -> dict[str, Any]:
    audit_events = recent_events(state_dir, "audit", limit=limit)
    tool_events = recent_events(state_dir, "tools", limit=limit)
    permission_events = recent_events(state_dir, "permissions", limit=limit)
    security_events = recent_events(state_dir, "security_audit", limit=limit)
    plugin_events = recent_events(state_dir, "plugin_audit", limit=limit)
    events = [*audit_events, *tool_events, *permission_events, *security_events, *plugin_events]
    events.sort(key=lambda item: float(item.get("time") or 0.0))
    events = events[-max(1, min(limit, MAX_RECENT_EVENTS)) :]
    count_source = audit_events or events
    return {
        "object": "agent_hub.audit",
        "events": events,
        "counts": {
            "files_read": sum(1 for item in count_source if item.get("action") == "file_read"),
            "files_modified": sum(1 for item in count_source if item.get("action") == "file_modified"),
            "commands_executed": sum(1 for item in count_source if item.get("action") == "command_executed" or item.get("type") == "command_execution"),
            "plugins_invoked": sum(1 for item in count_source if item.get("action") == "plugin_invoked"),
            "denied_actions": sum(1 for item in count_source if item.get("denied") is True or item.get("permission_denied") is True),
        },
    }


def metrics_snapshot(state_dir: str | Path, provider_health: dict[str, dict[str, Any]]) -> dict[str, Any]:
    usage = usage_snapshot(state_dir, provider_health)
    available = sum(1 for row in provider_health.values() if row.get("available"))
    degraded = sum(1 for row in provider_health.values() if row.get("degraded"))
    routing = recent_events(state_dir, "routing", limit=50)
    requests = recent_events(state_dir, "requests", limit=50)
    internal = recent_events(state_dir, "events", limit=MAX_RECENT_EVENTS)
    workflows = recent_events(state_dir, "workflows", limit=50)
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
        "counters": metrics_counters(provider_health, internal_events=internal),
        "recent_failures": _recent_failures(provider_health, internal),
        "workflow_events": workflows,
        "routing_decisions": routing,
        "request_traces": requests,
        "internal_events": internal[-50:],
    }


def record_structured_log(
    state_dir: str | Path,
    level: str,
    message: str,
    **fields: Any,
) -> None:
    record_event(
        state_dir,
        "logs",
        {
            "type": "log",
            "level": str(level or "info").lower(),
            "message": message,
            **fields,
        },
    )


def metrics_counters(
    provider_health: dict[str, dict[str, Any]],
    *,
    internal_events: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    internal_events = internal_events or []
    return {
        "provider_successes": sum(_safe_int(row.get("success_count")) for row in provider_health.values()),
        "provider_failures": sum(_safe_int(row.get("failure_count")) for row in provider_health.values()),
        "provider_timeouts": sum(_safe_int(row.get("timeout_count")) for row in provider_health.values()),
        "routing_fallbacks": sum(1 for event in internal_events if event.get("name") == "router.fallback"),
        "stream_failures": sum(1 for event in internal_events if event.get("name") == "stream.failed"),
        "context_truncations": sum(1 for event in internal_events if event.get("name") == "context.truncated"),
        "tool_executions": sum(1 for event in internal_events if event.get("name") == "tool.executed"),
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


def _read_event_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], 0
    rows: list[dict[str, Any]] = []
    invalid = 0
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            invalid += 1
            continue
        if isinstance(value, dict):
            rows.append(value)
        else:
            invalid += 1
    return rows, invalid


def _write_event_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not path.exists() and not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(row, separators=(",", ":"), ensure_ascii=False, default=str) + "\n" for row in rows)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            temp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def _retention_cutoff(retention_days: int | None, *, now: float | None) -> float | None:
    if retention_days is None:
        return None
    try:
        days = int(retention_days)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return float(now if now is not None else time.time()) - days * 86400.0


def _event_time(event: dict[str, Any]) -> float | None:
    try:
        value = float(event.get("time"))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _recent_failures(
    provider_health: dict[str, dict[str, Any]],
    internal_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    failures = [
        event
        for event in internal_events
        if event.get("name") in {"provider.failed", "stream.failed"}
    ]
    for row in provider_health.values():
        for event in row.get("failover_events", []) or []:
            if isinstance(event, dict):
                failures.append(event)
    return failures[-25:]


__all__ = [
    "MAX_RECENT_EVENTS",
    "STREAM_FILES",
    "audit_snapshot",
    "compact_event_stream",
    "compact_observability_state",
    "metrics_counters",
    "metrics_snapshot",
    "permission_snapshot",
    "recent_events",
    "record_event",
    "record_structured_log",
    "usage_snapshot",
]
