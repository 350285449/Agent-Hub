from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..config import HubConfig
from .registry import ToolRegistry
from .types import Tool, ToolCall, ToolResult


MAX_FILE_CHARS = 80_000
MAX_SEARCH_RESULTS = 100
MAX_COMMAND_SECONDS = 120


def create_builtin_registry(config: HubConfig | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin_tools(registry, config=config)
    return registry


def register_builtin_tools(registry: ToolRegistry, *, config: HubConfig | None = None) -> None:
    registry.register(
        Tool(
            name="file_read",
            description="Read a text file inside the configured workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "line_count": {"type": "integer"},
                    "max_chars": {"type": "integer"},
                },
                "required": ["path"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "truncated": {"type": "boolean"},
                },
            },
            executor=_file_read,
            read_only=True,
            permission="read",
            permissions=["filesystem:read"],
            metadata={"mcp_compatible": True, "safe_by_default": True},
        )
    )
    registry.register(
        Tool(
            name="file_write",
            description="Write or append a text file inside the configured workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "append": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "bytes": {"type": "integer"},
                },
            },
            executor=_file_write,
            read_only=False,
            permission="file_write",
            permissions=["filesystem:write"],
            metadata={"mcp_compatible": True, "requires_permission": True},
        )
    )
    registry.register(
        Tool(
            name="shell_execute",
            description="Execute a local shell command in the workspace, subject to permission policy.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                },
                "required": ["command"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "returncode": {"type": "integer"},
                    "output": {"type": "string"},
                    "truncated": {"type": "boolean"},
                },
            },
            executor=_shell_execute,
            read_only=False,
            permission="shell_command",
            permissions=["shell:execute"],
            metadata={
                "mcp_compatible": True,
                "requires_permission": True,
                "dangerous_commands_blocked": True,
            },
        )
    )
    registry.register(
        Tool(
            name="search_repo",
            description="Search text files in the workspace for a literal query.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "pattern": {"type": "string"},
                    "case_sensitive": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "matches": {
                        "type": "array",
                        "items": {"type": "object"},
                    }
                },
            },
            executor=_search_repo,
            read_only=True,
            permission="read",
            permissions=["filesystem:read", "repo:search"],
            metadata={"mcp_compatible": True, "safe_by_default": True},
        )
    )
    for alias, target in {
        "read_file": "file_read",
        "write_file": "file_write",
        "run_command": "shell_execute",
        "search_files": "search_repo",
    }.items():
        registry.register_alias(alias, target)


def _file_read(call: ToolCall, context: Any) -> ToolResult:
    path = _workspace_path(context.workspace_dir, call.arguments.get("path"))
    max_chars = _int_arg(call.arguments, "max_chars", MAX_FILE_CHARS, 1, MAX_FILE_CHARS)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = _int_arg(call.arguments, "start_line", 1, 1, max(1, len(lines))) - 1
    count = _int_arg(call.arguments, "line_count", len(lines), 1, max(1, len(lines)))
    selected = "\n".join(lines[start : start + count])
    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=True,
        content={
            "path": path.relative_to(context.workspace_dir).as_posix(),
            "content": selected[:max_chars],
            "truncated": len(selected) > max_chars,
        },
    )


def _file_write(call: ToolCall, context: Any) -> ToolResult:
    path = _workspace_path(context.workspace_dir, call.arguments.get("path"), allow_missing=True)
    content = str(call.arguments.get("content") or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    if bool(call.arguments.get("append")):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(content)
    else:
        path.write_text(content, encoding="utf-8")
    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=True,
        content={"path": path.relative_to(context.workspace_dir).as_posix(), "bytes": len(content.encode("utf-8"))},
    )


def _shell_execute(call: ToolCall, context: Any) -> ToolResult:
    command = str(call.arguments.get("command") or "").strip()
    if not command:
        raise ValueError("shell_execute requires a command")
    cwd = _workspace_path(context.workspace_dir, call.arguments.get("cwd") or ".", allow_missing=False)
    if not cwd.is_dir():
        raise ValueError("cwd must be a workspace directory")
    timeout = _int_arg(call.arguments, "timeout_seconds", 30, 1, MAX_COMMAND_SECONDS)
    completed = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=completed.returncode == 0,
        content={
            "returncode": completed.returncode,
            "output": output[:MAX_FILE_CHARS],
            "truncated": len(output) > MAX_FILE_CHARS,
        },
        error="" if completed.returncode == 0 else f"Command exited with {completed.returncode}",
    )


def _search_repo(call: ToolCall, context: Any) -> ToolResult:
    query = str(call.arguments.get("query") or "")
    if not query:
        raise ValueError("search_repo requires a query")
    root = _workspace_path(context.workspace_dir, call.arguments.get("path") or ".", allow_missing=False)
    pattern = str(call.arguments.get("pattern") or "*")
    limit = _int_arg(call.arguments, "limit", 50, 1, MAX_SEARCH_RESULTS)
    case_sensitive = bool(call.arguments.get("case_sensitive"))
    needle = query if case_sensitive else query.lower()
    matches: list[dict[str, Any]] = []
    files = [root] if root.is_file() else root.rglob(pattern)
    for path in files:
        if len(matches) >= limit:
            break
        if not path.is_file() or _skip_path(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        haystack = text if case_sensitive else text.lower()
        if needle not in haystack:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if len(matches) >= limit:
                break
            target = line if case_sensitive else line.lower()
            if needle in target:
                matches.append(
                    {
                        "path": path.relative_to(context.workspace_dir).as_posix(),
                        "line": line_no,
                        "text": line[:500],
                    }
                )
    return ToolResult(call_id=call.id, name=call.name, ok=True, content={"matches": matches})


def _workspace_path(root: Path, value: Any, *, allow_missing: bool = False) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A workspace-relative path is required")
    workspace = root.expanduser().resolve()
    path = (workspace / value).resolve()
    try:
        inside = path == workspace or path.is_relative_to(workspace)
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("Path escapes the workspace")
    if not allow_missing and not path.exists():
        raise FileNotFoundError(value)
    return path


def _skip_path(path: Path) -> bool:
    return any(part in {".git", ".agent-hub", "__pycache__", "node_modules", ".venv"} for part in path.parts)


def _int_arg(args: dict[str, Any], name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(args.get(name, default))
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))
