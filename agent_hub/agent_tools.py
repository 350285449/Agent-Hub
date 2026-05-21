from __future__ import annotations

import json
import re
import subprocess
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import HubConfig
from .models import HubRequest


SKIPPED_DIRS = {".agent-hub", ".git", ".hg", ".svn", ".venv", "__pycache__", "node_modules"}
MAX_FILE_CHARS = 80_000
MAX_TOOL_OUTPUT_CHARS = 20_000
MAX_REPLACE_CHARS = 200_000
MAX_PATCH_CHARS = 1_000_000
MAX_PATH_HINTS = 10
MAX_COMMAND_TIMEOUT_SECONDS = 600

AGENT_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_files",
        "description": "List files or directories inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path."},
                "pattern": {"type": "string", "description": "Glob pattern to match."},
                "recursive": {"type": "boolean", "description": "Search subdirectories."},
                "limit": {"type": "integer", "description": "Maximum number of entries."},
            },
        },
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file from the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "start_line": {"type": "integer", "description": "First 1-based line to read."},
                "line_count": {"type": "integer", "description": "Maximum lines to read."},
                "max_chars": {"type": "integer", "description": "Maximum characters to return."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Search workspace text files for a literal query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Literal text to search for."},
                "path": {"type": "string", "description": "Workspace-relative file or folder."},
                "pattern": {"type": "string", "description": "Glob pattern to search."},
                "case_sensitive": {"type": "boolean", "description": "Use case-sensitive matching."},
                "limit": {"type": "integer", "description": "Maximum number of matches."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "write_file",
        "description": "Create, overwrite, or append to a workspace text file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "content": {"type": "string", "description": "Content to write."},
                "append": {"type": "boolean", "description": "Append instead of overwriting."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "replace_in_file",
        "description": "Replace exact text in a workspace text file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "old": {"type": "string", "description": "Exact text to replace."},
                "new": {"type": "string", "description": "Replacement text."},
                "expected_replacements": {
                    "type": "integer",
                    "description": "Expected number of replacements, usually 1.",
                },
            },
            "required": ["path", "old", "new"],
        },
    },
    {
        "name": "apply_patch",
        "description": "Apply a validated multi-file patch atomically where possible.",
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "Unified diff patch. Supports multiple files.",
                },
                "changes": {
                    "type": "array",
                    "description": "Structured changes as path/content or path/old/new objects.",
                },
                "summary": {"type": "string", "description": "Short summary of planned changes."},
                "validation_plan": {
                    "type": "string",
                    "description": "Validation plan to run after applying the patch.",
                },
                "commands": {
                    "type": "array",
                    "description": "Commands the agent plans to run after applying the patch.",
                },
            },
        },
    },
]

RUN_COMMAND_TOOL_DEFINITION: dict[str, Any] = {
    "name": "run_command",
    "description": "Run a shell command inside the workspace.",
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run."},
            "cwd": {"type": "string", "description": "Workspace-relative working directory."},
            "timeout_seconds": {"type": "integer", "description": "Timeout in seconds."},
        },
        "required": ["command"],
    },
}


class ToolError(Exception):
    pass


ShellPermissionCallback = Callable[[dict[str, Any]], bool]


def agent_tool_definitions(allow_shell: bool) -> list[dict[str, Any]]:
    """Common workspace tool definitions converted by each provider."""

    tools = [*AGENT_TOOL_DEFINITIONS]
    if allow_shell:
        tools.append(RUN_COMMAND_TOOL_DEFINITION)
    return tools


@dataclass(slots=True)
class AgentToolbox:
    config: HubConfig
    request: HubRequest
    shell_permission_callback: ShellPermissionCallback | None = None

    @property
    def root(self) -> Path:
        workspace = _request_option(self.request, "workspace_dir", self.config.workspace_dir)
        return Path(workspace).expanduser().resolve()

    @property
    def allow_shell(self) -> bool:
        value = _request_option(self.request, "allow_shell_tools", self.config.allow_shell_tools)
        return bool(value)

    @property
    def shell_command_policy(self) -> str:
        value = _request_option(
            self.request,
            "shell_command_policy",
            self.config.shell_command_policy,
        )
        return _normalize_shell_policy(value)

    @property
    def allowed_tool_names(self) -> set[str] | None:
        value = _request_option(self.request, "agent_hub_allowed_tools", None)
        if value is None:
            hub_options = self.request.raw.get("agent_hub") if isinstance(self.request.raw, dict) else None
            value = hub_options.get("allowed_tools") if isinstance(hub_options, dict) else None
        if not isinstance(value, list):
            return None
        allowed = {str(item) for item in value if isinstance(item, str)}
        if not self.allow_shell or self.shell_command_policy == "deny":
            allowed.discard("run_command")
        return allowed

    def instructions(self) -> str:
        tool_examples = {
            "list_files": 'list_files args: {"path":".","pattern":"*","recursive":true,"limit":200}',
            "read_file": 'read_file args: {"path":"README.md","start_line":1,"line_count":200}',
            "search_files": 'search_files args: {"query":"needle","path":".","pattern":"*.py","limit":50}',
            "write_file": 'write_file args: {"path":"file.txt","content":"full file content","append":false}',
            "replace_in_file": 'replace_in_file args: {"path":"file.txt","old":"exact text","new":"replacement","expected_replacements":1}',
            "apply_patch": 'apply_patch args: {"summary":"update implementation and tests","changes":[{"path":"file.py","old":"old","new":"new","expected_replacements":1}],"validation_plan":"py_compile and tests"}',
            "run_command": 'run_command args: {"command":"python -m unittest","cwd":".","timeout_seconds":300}',
        }
        allowed = self.allowed_tool_names
        tool_order = [
            "list_files",
            "read_file",
            "search_files",
            "write_file",
            "replace_in_file",
            "apply_patch",
            "run_command",
        ]
        tools = [
            tool_examples[name]
            for name in tool_order
            if (allowed is None or name in allowed) and (name != "run_command" or self.allow_shell)
        ]
        shell_policy = self.shell_command_policy
        if not self.allow_shell:
            tools.append("run_command: unavailable unless allow_shell_tools is true.")
        elif shell_policy == "deny":
            tools.append("run_command: unavailable because shell_command_policy is deny.")
        elif shell_policy == "ask":
            tools.append("run_command: asks the user for permission before execution.")

        return "\n".join(
            [
                "You are an autonomous local coding agent running inside the user's workspace.",
                "Work like a careful repository agent: inspect before editing, keep changes scoped, and verify when possible.",
                "Use tools for file inspection, file creation, and edits. Do not invent file contents you have not inspected.",
                "When the user asks to create, edit, fix, update, or implement something, make the requested file change before your final answer.",
                "Use write_file to create files or rewrite a file you have read. Use replace_in_file for targeted edits.",
                "Prefer apply_patch when a task needs multiple coordinated file changes so approval and validation can happen once.",
                _shell_instruction(self.allow_shell, shell_policy),
                "Before editing, confirm the workspace root and target path from the request, active file context, or inspected files.",
                "When the request is about the open file or folder, prefer the Current file and Current folder paths from context.",
                "Do not edit duplicate workspace copies such as vscode-extension/backend/... unless that path is the active file or explicitly requested.",
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
            allowed = self.allowed_tool_names
            if allowed is not None and name not in allowed:
                raise ToolError(f"Tool {name!r} is not available for this agent stage")
            
            # Check if approval is needed
            approval_needed = self._is_approval_needed(name, args)
            if approval_needed and not self._approval_granted():
                approval_mode = self._get_approval_mode()
                if approval_mode == "readonly":
                    return {
                        "ok": False,
                        "tool": name,
                        "error": f"Tool {name} is not allowed in readonly mode."
                    }
                elif approval_mode in ("ask", "shell-ask"):
                    # For shell-ask mode, we only ask for shell commands (run_command)
                    if approval_mode == "shell-ask" and name != "run_command":
                        # File edits are allowed automatically in shell-ask mode
                        pass
                    else:
                        return self._request_approval(name, args)
            
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
            elif name == "apply_patch":
                result = self._apply_patch(args)
            elif name == "run_command":
                result = self._run_command(args)
            else:
                raise ToolError(f"Unknown tool {name!r}")
            response = {"ok": True, "tool": name, "result": result}
            if approval_needed and self._approval_granted():
                response["approval_granted"] = True
            return response
        except Exception as exc:
            return {"ok": False, "tool": name, "error": str(exc)}

    def _is_approval_needed(self, name: str, args: dict[str, Any]) -> bool:
        """Determine if a tool requires approval based on current approval mode."""
        approval_mode = self._get_approval_mode()
        if approval_mode == "auto":
            return False
        if approval_mode == "readonly":
            # In readonly mode, we still need to know if it's mutating to block it
            return self._is_mutating_tool(name) or self._is_unsafe_shell_command(name, args)
        if approval_mode == "ask":
            return self._is_mutating_tool(name) or self._is_unsafe_shell_command(name, args)
        if approval_mode == "shell-ask":
            # In shell-ask mode, we need approval for all shell commands
            return name == "run_command"
        # Fallback
        return False

    def _get_approval_mode(self) -> str:
        value = _request_option(self.request, "approval_mode", self.config.approval_mode)
        if value not in ("auto", "ask", "readonly", "shell-ask"):
            value = self.config.approval_mode
        return value

    def _approval_granted(self) -> bool:
        value = _request_option(self.request, "approval_granted", False)
        if value is False:
            value = _request_option(self.request, "approved", False)
        return _truthy(value)

    def _is_mutating_tool(self, name: str) -> bool:
        return name in ("write_file", "replace_in_file", "apply_patch")

    def _is_unsafe_shell_command(self, name: str, args: dict[str, Any]) -> bool:
        if name != "run_command":
            return False
        command = args.get("command", "").lower()
        # Unsafe patterns that modify files/system state
        unsafe_patterns = [
            # File modification/deletion
            " rm ", " mv ", " cp ", " > ", " >> ", " dd ", " mkfs ", " fdisk ",
            " truncate ", " shred ", " wipe ",
            # Package managers
            " pip install ", " npm install ", " yarn add ", " apt-get install ",
            " yum install ", " pacman -S ", " brew install ",
            # Git modifying commands
            " git push ", " git commit ", " git merge ", " git rebase ",
            " git reset ", " git checkout . ", " git clean -fdx ",
            # Formatting tools (modify files)
            " black ", " autopep8 ", " prettier ", " gofmt ", " rustfmt ",
            # Other destructive
            " chmod ", " chown ", " kill ", " pkill ", " shutdown ", " reboot ",
            " systemctl ", " service ",""
        ]
        # Also consider commands that start with these (without leading space)
        starts_with_unsafe = [
            "rm(", "mv(", "cp(", "dd(", "mkfs(", "fdisk(",
            "pip install", "npm install", "yarn add", "apt-get install",
            "yum install", "pacman -S", "brew install",
            "git push", "git commit", "git merge", "git rebase",
            "git reset", "git checkout .", "git clean -fdx",
            "black ", "autopep8 ", "prettier ", "gofmt ", "rustfmt ",
            "chmod ", "chown ", "kill ", "pkill ", "shutdown ", "reboot ",
        ]
        for pattern in starts_with_unsafe:
            if command.startswith(pattern):
                return True
        for pattern in unsafe_patterns:
            if pattern in command:
                return True
        return False

    def _get_affected_files(self, name: str, args: dict[str, Any]) -> list[str]:
        if name == "write_file":
            return [args.get("path", "")]
        if name == "replace_in_file":
            return [args.get("path", "")]
        if name == "apply_patch":
            try:
                return [change["path"] for change in self._patch_plan(args)["changes"]]
            except ToolError:
                return []
        # For run_command, we cannot know for sure; return empty
        return []

    def _get_risk_summary(self, name: str, args: dict[str, Any]) -> str:
        if name == "write_file":
            return f"Will overwrite or create file: {args.get('path', '')}"
        if name == "replace_in_file":
            return f"Will replace text in file: {args.get('path', '')}"
        if name == "apply_patch":
            summary = args.get("summary")
            if isinstance(summary, str) and summary.strip():
                return summary.strip()
            files = self._get_affected_files(name, args)
            return f"Will apply a patch affecting {len(files)} file(s)."
        if name == "run_command":
            cmd = args.get('command', '')
            return f"Will execute shell command: {cmd[:100]}{'...' if len(cmd) > 100 else ''}"
        return "Unknown risk"

    def _request_approval(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Return an approval required result."""
        details = self._approval_details(name, args)
        return {
            "ok": False,
            "approval_required": True,
            "tool": name,
            "args": args,
            "affected_files": details["affected_files"],
            "risk": details["summary"],
            "summary": details["summary"],
            "patch_preview": details["patch_preview"],
            "commands": details["commands"],
            "validation_plan": details["validation_plan"],
            "message": "Approval required before applying changes.",
        }

    def _approval_details(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        commands = _string_list(args.get("commands"))
        validation_plan = str(args.get("validation_plan") or "").strip()
        if name == "apply_patch":
            try:
                plan = self._patch_plan(args)
            except ToolError as exc:
                return {
                    "affected_files": [],
                    "summary": f"Invalid patch: {exc}",
                    "patch_preview": "",
                    "commands": commands,
                    "validation_plan": validation_plan,
                }
            return {
                "affected_files": [change["path"] for change in plan["changes"]],
                "summary": plan["summary"],
                "patch_preview": plan["patch_preview"],
                "commands": commands,
                "validation_plan": validation_plan,
            }
        if name in {"write_file", "replace_in_file"}:
            try:
                preview = self._single_edit_preview(name, args)
            except ToolError as exc:
                preview = f"Invalid edit: {exc}"
            return {
                "affected_files": self._get_affected_files(name, args),
                "summary": self._get_risk_summary(name, args),
                "patch_preview": preview,
                "commands": commands,
                "validation_plan": validation_plan,
            }
        return {
            "affected_files": [],
            "summary": self._get_risk_summary(name, args),
            "patch_preview": "",
            "commands": [str(args.get("command", ""))] if name == "run_command" else commands,
            "validation_plan": validation_plan,
        }

    def _list_files(self, args: dict[str, Any]) -> dict[str, Any]:
        target = self._resolve_existing(args.get("path", "."))
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
        path = self._resolve_required_path(args, "path", existing=True)
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

        target = self._resolve_existing(args.get("path", "."))
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

    def _apply_patch(self, args: dict[str, Any]) -> dict[str, Any]:
        plan = self._patch_plan(args)
        originals: dict[Path, str | None] = {}
        paths = [change["absolute_path"] for change in plan["changes"]]
        try:
            for path in paths:
                originals[path] = path.read_text(encoding="utf-8") if path.exists() else None
            for change in plan["changes"]:
                path = change["absolute_path"]
                content = change["content"]
                if content is None:
                    if path.exists():
                        path.unlink()
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
        except Exception as exc:
            for path, original in originals.items():
                try:
                    if original is None:
                        if path.exists():
                            path.unlink()
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(original, encoding="utf-8")
                except OSError:
                    pass
            raise ToolError(f"Patch failed and was rolled back: {exc}") from exc
        return {
            "paths": [change["path"] for change in plan["changes"]],
            "changes": [
                {
                    "path": change["path"],
                    "action": change["action"],
                    "chars": 0 if change["content"] is None else len(change["content"]),
                }
                for change in plan["changes"]
            ],
            "summary": plan["summary"],
            "patch_preview": plan["patch_preview"],
        }

    def _patch_plan(self, args: dict[str, Any]) -> dict[str, Any]:
        summary = str(args.get("summary") or "Apply workspace patch.").strip()
        patch_text = args.get("patch")
        changes_arg = args.get("changes")
        if isinstance(patch_text, str) and patch_text.strip():
            if len(patch_text) > MAX_PATCH_CHARS:
                raise ToolError("apply_patch patch is too large")
            changes = self._changes_from_unified_diff(patch_text)
            patch_preview = patch_text
        elif isinstance(changes_arg, list) and changes_arg:
            changes = self._changes_from_structured_patch(changes_arg)
            patch_preview = self._structured_patch_preview(changes)
        else:
            raise ToolError("apply_patch requires a non-empty patch string or changes list")
        seen: set[Path] = set()
        for change in changes:
            path = change["absolute_path"]
            if path in seen:
                raise ToolError(f"Patch contains multiple changes for {change['path']}; combine them first")
            seen.add(path)
        return {
            "summary": summary,
            "changes": changes,
            "patch_preview": patch_preview[:MAX_PATCH_CHARS],
        }

    def _changes_from_structured_patch(self, changes_arg: list[Any]) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for index, item in enumerate(changes_arg, start=1):
            if not isinstance(item, dict):
                raise ToolError(f"Structured patch change {index} must be an object")
            if item.get("delete"):
                path = self._resolve_required_path(item, "path", existing=True)
                self._guard_edit_target(item.get("path"), path)
                relative = self._relative(path)
                if not path.exists():
                    raise ToolError(f"Cannot delete missing file: {relative}")
                changes.append({"path": relative, "absolute_path": path, "content": None, "action": "delete"})
                continue
            if "content" in item:
                path = self._resolve_required_path(item, "path")
                self._guard_edit_target(item.get("path"), path)
                relative = self._relative(path)
                content = item.get("content")
                if not isinstance(content, str):
                    raise ToolError(f"Structured patch change {index} content must be a string")
                if len(content) > MAX_PATCH_CHARS:
                    raise ToolError(f"Structured patch change {index} content is too large")
                changes.append(
                    {
                        "path": relative,
                        "absolute_path": path,
                        "content": content,
                        "action": "write",
                    }
                )
                continue
            path = self._resolve_required_path(item, "path", existing=True)
            self._guard_edit_target(item.get("path"), path)
            relative = self._relative(path)
            old = item.get("old")
            new = item.get("new")
            if not isinstance(old, str) or not old:
                raise ToolError(f"Structured patch change {index} requires non-empty old text")
            if not isinstance(new, str):
                raise ToolError(f"Structured patch change {index} requires string new text")
            if not path.exists() or not path.is_file():
                raise ToolError(f"Cannot replace text in missing file: {relative}")
            expected = _positive_int(item.get("expected_replacements", 1), default=1, maximum=100)
            text = path.read_text(encoding="utf-8", errors="replace")
            actual = text.count(old)
            if actual != expected:
                raise ToolError(
                    f"{relative}: expected {expected} replacement(s), found {actual}"
                )
            changes.append(
                {
                    "path": relative,
                    "absolute_path": path,
                    "content": text.replace(old, new, expected),
                    "action": "replace",
                }
            )
        return changes

    def _changes_from_unified_diff(self, patch_text: str) -> list[dict[str, Any]]:
        file_patches = _parse_unified_diff(patch_text)
        if not file_patches:
            raise ToolError("Unified diff did not contain any file changes")
        changes: list[dict[str, Any]] = []
        for file_patch in file_patches:
            raw_path = file_patch["new_path"] if file_patch["new_path"] != "/dev/null" else file_patch["old_path"]
            if not raw_path or raw_path == "/dev/null":
                raise ToolError("Unified diff file path is missing")
            path = self._resolve(raw_path)
            self._guard_edit_target(raw_path, path)
            relative = self._relative(path)
            old_path = file_patch["old_path"]
            new_path = file_patch["new_path"]
            if old_path != "/dev/null" and (not path.exists() or not path.is_file()):
                raise ToolError(f"Cannot patch missing file: {relative}")
            original = "" if old_path == "/dev/null" else path.read_text(encoding="utf-8", errors="replace")
            updated = _apply_unified_hunks(original, file_patch["hunks"], relative)
            content = None if new_path == "/dev/null" else updated
            changes.append(
                {
                    "path": relative,
                    "absolute_path": path,
                    "content": content,
                    "action": "delete" if content is None else ("create" if old_path == "/dev/null" else "patch"),
                }
            )
        return changes

    def _structured_patch_preview(self, changes: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for change in changes:
            path = change["absolute_path"]
            before = "" if not path.exists() else path.read_text(encoding="utf-8", errors="replace")
            after = "" if change["content"] is None else str(change["content"])
            lines.extend(_simple_unified_diff(before, after, change["path"]))
        return "".join(lines)[:MAX_PATCH_CHARS]

    def _single_edit_preview(self, name: str, args: dict[str, Any]) -> str:
        if name == "write_file":
            path = self._resolve_required_path(args, "path")
            before = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            content = args.get("content")
            if not isinstance(content, str):
                raise ToolError("write_file requires string content")
            after = before + content if bool(args.get("append", False)) else content
            return "".join(_simple_unified_diff(before, after, self._relative(path)))
        if name == "replace_in_file":
            path = self._resolve_required_path(args, "path", existing=True)
            before = path.read_text(encoding="utf-8", errors="replace")
            old = args.get("old")
            new = args.get("new")
            if not isinstance(old, str) or not old or not isinstance(new, str):
                raise ToolError("replace_in_file requires old and new strings")
            expected = _positive_int(args.get("expected_replacements", 1), default=1, maximum=100)
            after = before.replace(old, new, expected)
            return "".join(_simple_unified_diff(before, after, self._relative(path)))
        return ""

    def _write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_required_path(args, "path")
        self._guard_edit_target(args.get("path"), path)
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
        path = self._resolve_required_path(args, "path", existing=True)
        self._guard_edit_target(args.get("path"), path)
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
        if self.shell_command_policy == "deny":
            raise ToolError("run_command is disabled by shell_command_policy=deny.")
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ToolError("run_command requires a command string")

        cwd = self._resolve_command_cwd(args.get("cwd"))
        if not cwd.is_dir():
            raise ToolError(f"Command cwd is not a directory: {self._relative(cwd)}")
        timeout = _positive_int(
            args.get("timeout_seconds"),
            default=60,
            maximum=MAX_COMMAND_TIMEOUT_SECONDS,
        )
        self._check_shell_permission(command=command, cwd=cwd, timeout_seconds=timeout)
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

    def _check_shell_permission(self, *, command: str, cwd: Path, timeout_seconds: int) -> None:
        if self.shell_command_policy != "ask":
            return
        if self.shell_permission_callback is None:
            raise ToolError(
                "run_command requires user permission, but no shell permission prompt is available."
            )
        details = {
            "command": command,
            "cwd": self._relative(cwd),
            "absolute_cwd": str(cwd),
            "workspace": str(self.root),
            "timeout_seconds": timeout_seconds,
        }
        try:
            approved = self.shell_permission_callback(details)
        except Exception as exc:
            raise ToolError(f"Shell command permission prompt failed: {exc}") from exc
        if not approved:
            raise ToolError("User denied permission to run shell command.")

    def _resolve_required_path(
        self,
        args: dict[str, Any],
        key: str,
        *,
        existing: bool = False,
    ) -> Path:
        value = args.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ToolError(f"Missing required path argument: {key}")
        if existing:
            return self._resolve_existing(value)
        return self._resolve(value)

    def _resolve(self, value: Any) -> Path:
        raw = str(value or ".")
        path = Path(raw).expanduser()
        resolved = path.resolve() if path.is_absolute() else (self.root / path).resolve()
        if resolved != self.root and not resolved.is_relative_to(self.root):
            raise ToolError(f"Path escapes workspace: {raw}")
        return resolved

    def _resolve_existing(self, value: Any) -> Path:
        raw = str(value or ".")
        if _is_bare_filename(raw):
            context_match = self._context_workspace_match(raw)
            if context_match:
                return context_match
        resolved = self._resolve(raw)
        if resolved.exists():
            return resolved
        if _is_bare_filename(raw):
            match = self._unique_workspace_match(raw)
            if match:
                return match
        return resolved

    def _context_workspace_match(self, raw: str) -> Path | None:
        needle = raw.casefold()
        for path in self._request_context_paths():
            if path.name.casefold() == needle and path.exists():
                return path
        for directory in self._request_context_dirs():
            path = directory / raw
            if path.name.casefold() == needle and path.exists():
                return path
        return None

    def _request_context_paths(self) -> list[Path]:
        return self._request_context_entries(("Current file", "File", "Reference"))

    def _request_context_dirs(self) -> list[Path]:
        directories = self._request_context_entries(("Current folder", "Folder"))
        for path in self._request_context_paths():
            parent = path.parent
            if parent not in directories:
                directories.append(parent)
        return directories

    def _request_context_entries(self, labels: tuple[str, ...]) -> list[Path]:
        texts: list[str] = []
        if self.request.context:
            texts.append(str(self.request.context))
        for message in self.request.messages:
            content = message.get("content")
            if isinstance(content, str):
                texts.append(content)

        paths: list[Path] = []
        seen: set[Path] = set()
        label_pattern = "|".join(re.escape(label) for label in labels)
        for text in texts:
            for line in text.splitlines():
                match = re.match(
                    rf"\s*(?:{label_pattern}):\s*(.+?)\s*$",
                    line,
                    flags=re.IGNORECASE,
                )
                if not match:
                    continue
                raw_path = match.group(1).strip().strip("\"'")
                if not raw_path:
                    continue
                try:
                    path = self._resolve(raw_path)
                except ToolError:
                    continue
                if path not in seen:
                    seen.add(path)
                    paths.append(path)
        return paths

    def _resolve_command_cwd(self, value: Any) -> Path:
        if value is None:
            for directory in self._request_context_dirs():
                if directory.is_dir():
                    return directory
        return self._resolve("." if value is None else value)

    def _guard_edit_target(self, raw_value: Any, path: Path) -> None:
        relative = self._relative(path)
        if self._is_context_path(path) or self._request_mentions_path(raw_value, relative):
            return
        normalized = relative.replace("\\", "/").casefold()
        if normalized.startswith("vscode-extension/backend/"):
            raise ToolError(
                "Refusing to edit vscode-extension/backend/... because that duplicate workspace "
                "copy was not the active file or explicitly requested."
            )

    def _unique_workspace_match(self, raw: str) -> Path | None:
        needle = raw.casefold()
        matches: list[Path] = []
        pending = [self.root]
        while pending:
            directory = pending.pop()
            try:
                children = list(directory.iterdir())
            except OSError:
                continue
            for path in children:
                if self._is_skipped(path):
                    continue
                if path.name.casefold() == needle:
                    matches.append(path)
                    if len(matches) > MAX_PATH_HINTS:
                        break
                if path.is_dir():
                    pending.append(path)
            if len(matches) > MAX_PATH_HINTS:
                break

        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]

        hints = ", ".join(self._relative(path) for path in matches[:MAX_PATH_HINTS])
        extra = "" if len(matches) <= MAX_PATH_HINTS else ", ..."
        raise ToolError(f"Ambiguous path {raw!r}; use one of: {hints}{extra}")

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

    def _is_context_path(self, path: Path) -> bool:
        return any(path == candidate for candidate in self._request_context_paths())

    def _request_mentions_path(self, raw_value: Any, relative: str) -> bool:
        raw = str(raw_value or "").replace("\\", "/").strip()
        relative = relative.replace("\\", "/")
        needles = {raw, relative}
        if raw:
            needles.add(raw.lstrip("./"))
        needles = {needle.casefold() for needle in needles if needle}
        if not needles:
            return False

        texts: list[str] = []
        if self.request.task:
            texts.append(str(self.request.task))
        if self.request.context:
            texts.append(str(self.request.context))
        for message in self.request.messages:
            content = message.get("content")
            if isinstance(content, str):
                texts.append(content)
        haystack = "\n".join(texts).replace("\\", "/").casefold()
        return any(needle in haystack for needle in needles)


def _request_option(request: HubRequest, key: str, default: Any) -> Any:
    raw = request.raw or {}
    hub_options = raw.get("agent_hub")
    if isinstance(hub_options, dict) and key in hub_options:
        return hub_options[key]
    return raw.get(key, default)


def _parse_unified_diff(patch_text: str) -> list[dict[str, Any]]:
    lines = patch_text.splitlines(keepends=True)
    patches: list[dict[str, Any]] = []
    index = 0
    current: dict[str, Any] | None = None
    while index < len(lines):
        line = lines[index]
        if line.startswith("--- "):
            if current is not None:
                patches.append(current)
            old_path = _diff_path(line[4:].strip())
            index += 1
            if index >= len(lines) or not lines[index].startswith("+++ "):
                raise ToolError("Unified diff missing +++ path after --- path")
            new_path = _diff_path(lines[index][4:].strip())
            current = {"old_path": old_path, "new_path": new_path, "hunks": []}
        elif line.startswith("@@ "):
            if current is None:
                raise ToolError("Unified diff hunk appeared before file header")
            hunk_lines = [line]
            index += 1
            while index < len(lines) and not lines[index].startswith(("--- ", "@@ ")):
                hunk_lines.append(lines[index])
                index += 1
            current["hunks"].append(hunk_lines)
            continue
        index += 1
    if current is not None:
        patches.append(current)
    return patches


def _diff_path(value: str) -> str:
    path = value.split("\t", 1)[0].split(" ", 1)[0]
    if path in {"/dev/null", "dev/null"}:
        return "/dev/null"
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _apply_unified_hunks(original: str, hunks: list[list[str]], relative: str) -> str:
    original_lines = original.splitlines(keepends=True)
    output: list[str] = []
    source_index = 0
    for hunk in hunks:
        if not hunk:
            continue
        match = re.match(r"@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@", hunk[0])
        if not match:
            raise ToolError(f"{relative}: invalid unified diff hunk header")
        old_start = int(match.group("old"))
        target_index = max(0, old_start - 1)
        if target_index < source_index:
            raise ToolError(f"{relative}: overlapping unified diff hunks")
        output.extend(original_lines[source_index:target_index])
        source_index = target_index
        for line in hunk[1:]:
            if line.startswith("\\"):
                continue
            marker = line[:1]
            content = line[1:]
            if marker == " ":
                if source_index >= len(original_lines) or original_lines[source_index] != content:
                    raise ToolError(f"{relative}: unified diff context does not match")
                output.append(original_lines[source_index])
                source_index += 1
            elif marker == "-":
                if source_index >= len(original_lines) or original_lines[source_index] != content:
                    raise ToolError(f"{relative}: unified diff removal does not match")
                source_index += 1
            elif marker == "+":
                output.append(content)
            else:
                raise ToolError(f"{relative}: invalid unified diff line {line[:20]!r}")
    output.extend(original_lines[source_index:])
    return "".join(output)


def _simple_unified_diff(before: str, after: str, path: str) -> list[str]:
    return list(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "approved"}
    return bool(value)


def _shell_instruction(allow_shell: bool, policy: str) -> str:
    if not allow_shell:
        return "Shell tools are disabled; do not call run_command."
    if policy == "ask":
        return (
            "Use run_command only when it materially helps; the user will be asked "
            "for permission before each shell command runs."
        )
    if policy == "deny":
        return "Shell command execution is disabled by policy; do not call run_command."
    return "If shell tools are enabled, use run_command for fast inspection, builds, tests, and requested commands."


def _normalize_shell_policy(value: Any) -> str:
    text = str(value or "allow").strip().lower()
    if text in {"ask", "confirm", "prompt"}:
        return "ask"
    if text in {"deny", "disabled", "disable", "off", "false", "0"}:
        return "deny"
    return "allow"


def _is_bare_filename(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    if "/" in value or "\\" in value:
        return False
    path = Path(value)
    return not path.is_absolute() and len(path.parts) == 1


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
            "Continue with exactly one JSON object: another tool call or a final answer. "
            "If the tool failed, correct the arguments before retrying."
        ),
    }
