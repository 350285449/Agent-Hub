from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import HubConfig
from .models import HubRequest


SKIPPED_DIRS = {".agent-hub", ".git", ".hg", ".svn", ".venv", "__pycache__", "node_modules"}
MAX_FILE_CHARS = 80_000
MAX_TOOL_OUTPUT_CHARS = 20_000
MAX_REPLACE_CHARS = 200_000


class ToolError(Exception):
    pass


@dataclass(slots=True)
class AgentToolbox:
    config: HubConfig
    request: HubRequest

    @property
    def root(self) -> Path:
        workspace = _request_option(self.request, "workspace_dir", self.config.workspace_dir)
        return Path(workspace).expanduser().resolve()

    @property
    def allow_shell(self) -> bool:
        value = _request_option(self.request, "allow_shell_tools", self.config.allow_shell_tools)
        return bool(value)

    def instructions(self) -> str:
        tools = [
            'list_files args: {"path":".","pattern":"*","recursive":true,"limit":200}',
            'read_file args: {"path":"README.md","start_line":1,"line_count":200}',
            'search_files args: {"query":"needle","path":".","pattern":"*.py","limit":50}',
            'write_file args: {"path":"file.txt","content":"full file content","append":false}',
            'replace_in_file args: {"path":"file.txt","old":"exact text","new":"replacement","expected_replacements":1}',
        ]
        if self.allow_shell:
            tools.append('run_command args: {"command":"python -m unittest","cwd":".","timeout_seconds":120}')
        else:
            tools.append("run_command: unavailable unless allow_shell_tools is true.")

        return "\n".join(
            [
                "You are an autonomous local coding agent running inside the user's workspace.",
                "Work like a careful repository agent: inspect before editing, keep changes scoped, and verify when possible.",
                "Use tools for file inspection and edits. Do not invent file contents you have not inspected.",
                "Prefer replace_in_file for targeted edits. Use write_file only when creating a file or rewriting a file you have read.",
                "If shell tools are enabled, run focused checks after meaningful code changes.",
                "Never read or write outside the workspace root.",
                "Reply with exactly one JSON object and no Markdown.",
                'Valid actions are only "tool" and "final"; do not invent other action names.',
                'To use a tool: {"action":"tool","tool":"read_file","args":{"path":"README.md"}}',
                'When finished: {"action":"final","answer":"brief summary, changed files, and verification"}',
                f"Workspace root: {self.root}",
                "Available tools:",
                *[f"- {tool}" for tool in tools],
            ]
        )

    def run(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        try:
            if name == "list_files":
                result = self._list_files(args)
            elif name == "read_file":
                result = self._read_file(args)
            elif name == "search_files":
                result = self._search_files(args)
            elif name == "write_file":
                result = self._write_file(args)
            elif name == "replace_in_file":
                result = self._replace_in_file(args)
            elif name == "run_command":
                result = self._run_command(args)
            else:
                raise ToolError(f"Unknown tool {name!r}")
            return {"ok": True, "tool": name, "result": result}
        except Exception as exc:
            return {"ok": False, "tool": name, "error": str(exc)}

    def _list_files(self, args: dict[str, Any]) -> dict[str, Any]:
        target = self._resolve(args.get("path", "."))
        pattern = str(args.get("pattern", "*"))
        recursive = bool(args.get("recursive", True))
        limit = _positive_int(args.get("limit"), default=200, maximum=1000)

        if not target.exists():
            raise ToolError(f"Path does not exist: {self._relative(target)}")
        if target.is_file():
            return {"files": [self._file_info(target)]}

        iterator = target.rglob(pattern) if recursive else target.glob(pattern)
        files: list[dict[str, Any]] = []
        for item in iterator:
            if self._is_skipped(item):
                continue
            files.append(self._file_info(item))
            if len(files) >= limit:
                break
        return {"root": str(self.root), "path": self._relative(target), "files": files}

    def _read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_required_path(args, "path")
        if not path.is_file():
            raise ToolError(f"Not a file: {self._relative(path)}")
        max_chars = _positive_int(args.get("max_chars"), default=MAX_FILE_CHARS, maximum=MAX_FILE_CHARS)
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)
        start_line = _positive_int(args.get("start_line"), default=1, maximum=max(1, total_lines))
        line_count_value = args.get("line_count")
        if line_count_value is not None:
            line_count = _positive_int(line_count_value, default=200, maximum=5000)
            selected = lines[start_line - 1 : start_line - 1 + line_count]
            text = "".join(selected)
        else:
            selected = lines[start_line - 1 :]
            text = "".join(selected)
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]
        returned_lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        return {
            "path": self._relative(path),
            "content": text,
            "truncated": truncated,
            "chars": len(text),
            "start_line": start_line,
            "end_line": min(total_lines, start_line + max(0, returned_lines - 1)),
            "total_lines": total_lines,
        }

    def _search_files(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", ""))
        if not query:
            raise ToolError("search_files requires a non-empty query")

        target = self._resolve(args.get("path", "."))
        pattern = str(args.get("pattern", "*"))
        case_sensitive = bool(args.get("case_sensitive", False))
        limit = _positive_int(args.get("limit"), default=50, maximum=200)
        needle = query if case_sensitive else query.lower()

        matches: list[dict[str, Any]] = []
        files = [target] if target.is_file() else target.rglob(pattern)
        for path in files:
            if len(matches) >= limit:
                break
            if self._is_skipped(path) or not path.is_file():
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                haystack = line if case_sensitive else line.lower()
                if needle in haystack:
                    matches.append(
                        {
                            "path": self._relative(path),
                            "line": line_number,
                            "text": line[:500],
                        }
                    )
                    if len(matches) >= limit:
                        break
        return {"query": query, "matches": matches}

    def _write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_required_path(args, "path")
        content = args.get("content")
        if not isinstance(content, str):
            raise ToolError("write_file requires string content")
        if len(content) > 500_000:
            raise ToolError("write_file content is too large")

        append = bool(args.get("append", False))
        path.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(content)
        else:
            path.write_text(content, encoding="utf-8")
        return {"path": self._relative(path), "chars": len(content), "append": append}

    def _replace_in_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_required_path(args, "path")
        if not path.is_file():
            raise ToolError(f"Not a file: {self._relative(path)}")
        old = args.get("old")
        new = args.get("new")
        if not isinstance(old, str) or not old:
            raise ToolError("replace_in_file requires non-empty old text")
        if not isinstance(new, str):
            raise ToolError("replace_in_file requires string new text")
        if len(old) > MAX_REPLACE_CHARS or len(new) > MAX_REPLACE_CHARS:
            raise ToolError("replace_in_file replacement is too large")

        expected = args.get("expected_replacements", 1)
        expected_count = _positive_int(expected, default=1, maximum=100)
        text = path.read_text(encoding="utf-8", errors="replace")
        actual_count = text.count(old)
        if actual_count != expected_count:
            raise ToolError(
                f"Expected {expected_count} replacement(s), found {actual_count}. "
                "Read the file and provide a more exact old string."
            )
        updated = text.replace(old, new, expected_count)
        path.write_text(updated, encoding="utf-8")
        return {
            "path": self._relative(path),
            "replacements": expected_count,
            "chars": len(updated),
        }

    def _run_command(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.allow_shell:
            raise ToolError("run_command is disabled. Set allow_shell_tools to true to enable it.")
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ToolError("run_command requires a command string")

        cwd = self._resolve(args.get("cwd", "."))
        if not cwd.is_dir():
            raise ToolError(f"Command cwd is not a directory: {self._relative(cwd)}")
        timeout = _positive_int(args.get("timeout_seconds"), default=30, maximum=120)
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "command": command,
            "cwd": self._relative(cwd),
            "returncode": completed.returncode,
            "stdout": completed.stdout[:MAX_TOOL_OUTPUT_CHARS],
            "stderr": completed.stderr[:MAX_TOOL_OUTPUT_CHARS],
            "stdout_truncated": len(completed.stdout) > MAX_TOOL_OUTPUT_CHARS,
            "stderr_truncated": len(completed.stderr) > MAX_TOOL_OUTPUT_CHARS,
        }

    def _resolve_required_path(self, args: dict[str, Any], key: str) -> Path:
        value = args.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ToolError(f"Missing required path argument: {key}")
        return self._resolve(value)

    def _resolve(self, value: Any) -> Path:
        raw = str(value or ".")
        path = Path(raw).expanduser()
        resolved = path.resolve() if path.is_absolute() else (self.root / path).resolve()
        if resolved != self.root and not resolved.is_relative_to(self.root):
            raise ToolError(f"Path escapes workspace: {raw}")
        return resolved

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix() or "."
        except ValueError:
            return str(path)

    def _file_info(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "path": self._relative(path),
            "type": "directory" if path.is_dir() else "file",
            "size": None if path.is_dir() else stat.st_size,
        }

    def _is_skipped(self, path: Path) -> bool:
        try:
            parts = path.relative_to(self.root).parts
        except ValueError:
            parts = path.parts
        return any(part in SKIPPED_DIRS for part in parts)


def _request_option(request: HubRequest, key: str, default: Any) -> Any:
    raw = request.raw or {}
    hub_options = raw.get("agent_hub")
    if isinstance(hub_options, dict) and key in hub_options:
        return hub_options[key]
    return raw.get(key, default)


def _positive_int(value: Any, default: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, maximum))


def tool_result_message(tool_name: str, result: dict[str, Any]) -> dict[str, str]:
    content = json.dumps(result, indent=2, ensure_ascii=False)
    return {
        "role": "user",
        "content": (
            f"Tool result for {tool_name}:\n{content}\n\n"
            "Continue with exactly one JSON object: another tool call or a final answer."
        ),
    }
