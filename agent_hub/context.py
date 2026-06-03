from __future__ import annotations

import json
from typing import Any


PROTECTED_CONTEXT_KEYS = (
    "task_progress",
    "todo",
    "todos",
    "todo_list",
    "active_file",
    "active_files",
    "open_file",
    "open_files",
    "open_tabs",
    "workspace",
    "workspace_metadata",
    "workspace_state",
    "mcp",
    "mcp_state",
    "tool_state",
    "reasoning",
    "reasoning_chain",
    "latest_reasoning_chain",
    "assistant_actions",
    "latest_assistant_actions",
)

STRUCTURED_BLOCK_TYPES = {
    "text",
    "input_text",
    "output_text",
    "tool_use",
    "tool_result",
    "function_call",
    "function_call_output",
    "file",
    "input_file",
}


def compatibility_mode_enabled(
    payload: dict[str, Any] | None,
    *,
    default: bool = True,
) -> bool:
    """Return whether rich client context should be preserved verbatim.

    Cline, Claude Code, and newer OpenAI-compatible clients send task state as
    structured message blocks or top-level metadata. Treat preservation as the
    safe default, while still allowing an explicit false override for legacy
    clients that need compact text-only payloads.
    """

    if not isinstance(payload, dict):
        return default
    explicit = _lookup_option(
        payload,
        "cline_compatibility_mode",
        "preserve_structured_context",
        "preserve_context_blocks",
    )
    if explicit is not None:
        return _truthy(explicit, default=default)
    source = _lookup_option(payload, "source", "client", "client_name")
    if isinstance(source, str) and source.strip().lower() in {
        "cline",
        "claude-code",
        "claude_code",
        "codex",
        "vscode",
    }:
        return True
    if extract_context_state(payload):
        return True
    if _contains_structured_content(payload.get("messages")):
        return True
    if _contains_structured_content(payload.get("input")):
        return True
    return default


def enrich_metadata_with_context(
    payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enriched = dict(metadata or {})
    context_state = extract_context_state(payload)
    if context_state:
        existing = enriched.get("context_state")
        if isinstance(existing, dict):
            context_state = {**context_state, **existing}
        enriched["context_state"] = context_state
    enriched["cline_compatibility_mode"] = compatibility_mode_enabled(payload)
    return enriched


def extract_context_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    state: dict[str, Any] = {}
    for key in PROTECTED_CONTEXT_KEYS:
        if key in payload and payload[key] not in (None, "", [], {}):
            state[key] = payload[key]
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        for key in PROTECTED_CONTEXT_KEYS:
            if key in metadata and metadata[key] not in (None, "", [], {}):
                state.setdefault(key, metadata[key])
    hub_options = payload.get("agent_hub")
    if isinstance(hub_options, dict):
        for key in PROTECTED_CONTEXT_KEYS:
            if key in hub_options and hub_options[key] not in (None, "", [], {}):
                state.setdefault(key, hub_options[key])
    return state


def context_state_messages(state: dict[str, Any]) -> list[dict[str, Any]]:
    if not state:
        return []
    lines = ["Protected client context:"]
    for key in PROTECTED_CONTEXT_KEYS:
        if key in state:
            lines.append(f"{key}: {_compact_json(state[key], maximum=1600)}")
    return [{"role": "user", "content": "\n".join(lines), "agent_hub_protected": True}]


def message_context_categories(message: dict[str, Any]) -> set[str]:
    categories: set[str] = set()
    if not isinstance(message, dict):
        return categories
    content = message.get("content")
    if isinstance(content, list):
        categories.add("structured_content")
        for item in content:
            if isinstance(item, dict):
                item_type = str(item.get("type") or "")
                if item_type in {"tool_use", "function_call"}:
                    categories.add("tool_call")
                if item_type in {"tool_result", "function_call_output"}:
                    categories.add("tool_result")
                if item_type in STRUCTURED_BLOCK_TYPES:
                    categories.add(f"block:{item_type}")
    if isinstance(message.get("tool_calls"), list) or isinstance(message.get("function_call"), dict):
        categories.add("tool_call")
    if message.get("role") == "tool" or message.get("tool_call_id") or message.get("tool_use_id"):
        categories.add("tool_result")
    keys = set(message)
    if keys & {"task_progress", "progress"}:
        categories.add("task_progress")
    if keys & {"todo", "todos", "todo_list"}:
        categories.add("todo")
    if keys & {"active_file", "active_files", "open_files", "open_tabs"}:
        categories.add("active_editor")
    if keys & {"workspace", "workspace_metadata", "workspace_state"}:
        categories.add("workspace_state")
    if keys & {"mcp", "mcp_state", "tool_state"}:
        categories.add("mcp_state")
    if keys & {"reasoning", "reasoning_chain", "latest_reasoning_chain"}:
        categories.add("reasoning")
    text = content_to_text(content).lower()
    if "task_progress" in text or "task progress" in text:
        categories.add("task_progress")
    if "todo" in text or "checklist" in text:
        categories.add("todo")
    if "active file" in text or "open tabs" in text or "open files" in text:
        categories.add("active_editor")
    return categories


def is_protected_context_message(message: dict[str, Any], *, recent: bool = False) -> bool:
    if not isinstance(message, dict):
        return False
    if message.get("agent_hub_protected"):
        return True
    categories = message_context_categories(message)
    if categories & {
        "task_progress",
        "todo",
        "active_editor",
        "workspace_state",
        "mcp_state",
        "reasoning",
    }:
        return True
    if recent and categories & {"tool_call", "tool_result", "structured_content"}:
        return True
    return False


def request_context_diagnostics(
    request: Any,
    *,
    messages: list[dict[str, Any]] | None = None,
    compacted_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    incoming = messages if messages is not None else list(getattr(request, "messages", []) or [])
    after = compacted_messages if compacted_messages is not None else incoming
    raw = getattr(request, "raw", {}) or {}
    metadata = getattr(request, "metadata", {}) or {}
    context_state = metadata.get("context_state") if isinstance(metadata, dict) else {}
    if not isinstance(context_state, dict):
        context_state = {}
    protected_messages = [
        message
        for index, message in enumerate(after)
        if is_protected_context_message(message, recent=index >= max(0, len(after) - 8))
    ]
    incoming_tokens = estimate_message_tokens(incoming)
    compacted_tokens = estimate_message_tokens(after)
    protected_tokens = estimate_message_tokens(protected_messages)
    incoming_count = len(incoming)
    compacted_count = len(after)
    dropped_messages = max(0, incoming_count - compacted_count)
    dropped_token_count = max(0, incoming_tokens - compacted_tokens)
    todo_count = _todo_count(context_state) + sum(
        1
        for message in after
        if message_context_categories(message) & {"todo", "task_progress"}
    )
    active_files = _active_files(context_state, after)
    tool_calls = sum(1 for message in after if "tool_call" in message_context_categories(message))
    tool_results = sum(1 for message in after if "tool_result" in message_context_categories(message))
    text_tokens = estimate_text_tokens("\n".join(content_to_text(m.get("content")) for m in after))
    suspicious = incoming_count > 0 and text_tokens <= 8 and not protected_messages
    return {
        "incoming_token_count": incoming_tokens,
        "compacted_token_count": compacted_tokens,
        "protected_token_count": protected_tokens,
        "dropped_messages": dropped_messages,
        "dropped_token_count": dropped_token_count,
        "preserved_tool_calls": tool_calls,
        "preserved_tool_results": tool_results,
        "preserved_todo_count": todo_count,
        "active_files_detected": active_files,
        "task_progress_present": bool(context_state.get("task_progress"))
        or any("task_progress" in message_context_categories(m) for m in after),
        "structured_content_messages": sum(
            1 for message in after if "structured_content" in message_context_categories(message)
        ),
        "cline_compatibility_mode": compatibility_mode_enabled(raw),
        "suspiciously_empty": suspicious,
    }


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = content_to_text(message.get("content"))
        extra = ""
        for key in ("tool_calls", "function_call", "task_progress", "todos", "active_files"):
            if key in message:
                extra += "\n" + _compact_json(message[key], maximum=4000)
        total += max(1, (len(role) + len(content) + len(extra) + 3) // 4) + 4
    return max(1, total)


def estimate_text_tokens(text: str) -> int:
    return max(0, (len(text or "") + 3) // 4)


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
                value = item.get("text")
                if isinstance(value, str):
                    parts.append(value)
                    continue
                value = item.get("content")
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, (list, dict)):
                    parts.append(content_to_text(value))
                elif item.get("type") in {"tool_use", "function_call"}:
                    parts.append(_compact_json(item, maximum=2000))
                elif item.get("type") in {"tool_result", "function_call_output"}:
                    parts.append(_compact_json(item, maximum=3000))
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        value = content.get("text") or content.get("content")
        if isinstance(value, str):
            return value
        if isinstance(value, (list, dict)):
            return content_to_text(value)
    return str(content)


def message_signature(message: dict[str, Any]) -> str:
    return _compact_json(message, maximum=10000)


def _lookup_option(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        for key in keys:
            if key in metadata:
                return metadata[key]
    hub_options = payload.get("agent_hub")
    if isinstance(hub_options, dict):
        for key in keys:
            if key in hub_options:
                return hub_options[key]
    return None


def _contains_structured_content(value: Any) -> bool:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                content = item.get("content", item)
                if isinstance(content, list) and any(
                    isinstance(block, dict)
                    and str(block.get("type") or "") in STRUCTURED_BLOCK_TYPES
                    for block in content
                ):
                    return True
                if _contains_structured_content(content):
                    return True
            elif isinstance(item, list) and _contains_structured_content(item):
                return True
    if isinstance(value, dict):
        if str(value.get("type") or "") in STRUCTURED_BLOCK_TYPES:
            return True
        return any(_contains_structured_content(item) for item in value.values())
    return False


def _truthy(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"0", "false", "no", "off", "disabled"}:
            return False
        if lowered in {"1", "true", "yes", "on", "enabled"}:
            return True
    return bool(value)


def _todo_count(context_state: dict[str, Any]) -> int:
    total = 0
    for key in ("todo", "todos", "todo_list", "task_progress"):
        value = context_state.get(key)
        if isinstance(value, list):
            total += len(value)
        elif isinstance(value, dict):
            total += len(value)
        elif isinstance(value, str) and value.strip():
            total += 1
    return total


def _active_files(context_state: dict[str, Any], messages: list[dict[str, Any]]) -> list[str]:
    files: list[str] = []
    for key in ("active_file", "open_file"):
        value = context_state.get(key)
        if isinstance(value, str):
            files.append(value)
        elif isinstance(value, dict):
            candidate = value.get("path") or value.get("file") or value.get("uri")
            if isinstance(candidate, str):
                files.append(candidate)
    for key in ("active_files", "open_files", "open_tabs"):
        value = context_state.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    files.append(item)
                elif isinstance(item, dict):
                    candidate = item.get("path") or item.get("file") or item.get("uri")
                    if isinstance(candidate, str):
                        files.append(candidate)
    for message in messages:
        for key in ("active_file", "active_files", "open_files", "open_tabs"):
            value = message.get(key) if isinstance(message, dict) else None
            if isinstance(value, str):
                files.append(value)
            elif isinstance(value, list):
                files.extend(str(item) for item in value if isinstance(item, str))
    seen: set[str] = set()
    result: list[str] = []
    for item in files:
        clean = item.strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result[:40]


def _compact_json(value: Any, *, maximum: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(value)
    if len(text) <= maximum:
        return text
    return text[: maximum - 1] + "..."
