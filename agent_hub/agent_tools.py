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
            "list_files: list files under a workspace path.",
            "read_file: read a UTF-8 text file.",
            "search_files: search text files for a query.",
            "write_file: create, overwrite, or append a UTF-8 text file.",
        ]
        if self.allow_shell:
            tools.append("run_command: run a shell command from the workspace.")
        else:
            tools.append("run_command: unavailable unless allow_shell_tools is true.")

        return "\n".join(
            [
                "You are an autonomous local workspace agent.",
                "Use tools when you need to inspect or change files. Do not invent file contents you have not inspected.",
                "Reply with exactly one JSON object and no Markdown.",
                'To use a tool: {"action":"tool","tool":"read_file","args":{"path":"README.md"}}',
                'When finished: {"action":"final","answer":"your final answer"}',
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
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]
        return {
            "path": self._relative(path),
            "content": text,
            "truncated": truncated,
            "chars": len(text),
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
