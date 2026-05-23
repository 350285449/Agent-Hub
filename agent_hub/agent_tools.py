from __future__ import annotations

import json
import os
import re
import ast
import shutil
import subprocess
import tempfile
import time
import uuid
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import HubConfig
from .models import HubRequest


SKIPPED_DIRS = {".agent-hub", ".git", ".hg", ".svn", ".venv", "__pycache__", "node_modules"}
RUNTIME_DIR_OPTIONS = ("state_dir", "inbox_dir", "outbox_dir", "archive_dir")
MAX_FILE_CHARS = 80_000
MAX_TOOL_OUTPUT_CHARS = 20_000
MAX_REPLACE_CHARS = 200_000
MAX_PATCH_CHARS = 1_000_000
MAX_PATH_HINTS = 10
MAX_COMMAND_TIMEOUT_SECONDS = 600
MAX_CHECKPOINT_RETENTION = 100
MAX_REPO_MAP_FILES = 80
MAX_SYMBOLS_PER_FILE = 20

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
        "name": "repo_map",
        "description": "Build a lightweight repository map with related files, tests, configs, and symbols before editing.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative focus path."},
                "target": {"type": "string", "description": "File, module, or symbol to prioritize."},
                "limit": {"type": "integer", "description": "Maximum files to return."},
            },
        },
    },
    {
        "name": "write_file",
        "description": "Create, overwrite, or append to one workspace text file. Prefer apply_patch for coordinated or repair edits.",
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
        "description": "Replace exact text in one workspace text file. Prefer apply_patch for multi-file or validation-repair edits.",
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
        "description": "Apply a validated grouped patch across one or more files, with checkpoint rollback support.",
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


def create_workspace_checkpoint(
    root: str | Path,
    paths: list[str | Path],
    *,
    state_dir: str | Path | None = None,
    retention: int = 5,
    reason: str = "",
) -> dict[str, Any]:
    """Persist a small pre-edit snapshot for files inside the workspace."""

    workspace = Path(root).expanduser().resolve()
    unique_paths = _unique_checkpoint_paths(workspace, paths)
    if not unique_paths:
        raise ToolError("Cannot create a checkpoint without workspace paths")

    checkpoints_dir = _checkpoint_base_dir(workspace, state_dir)
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{checkpoint_id}.", dir=checkpoints_dir))
    files_dir = temp_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "id": checkpoint_id,
        "created_at": time.time(),
        "root": str(workspace),
        "reason": reason,
        "files": [],
    }
    try:
        for path in unique_paths:
            relative = _relative_to_workspace(workspace, path)
            entry: dict[str, Any] = {"path": relative, "exists": path.exists()}
            if path.exists():
                if not path.is_file():
                    raise ToolError(f"Cannot checkpoint non-file path: {relative}")
                snapshot_name = f"{len(manifest['files']):04d}.bin"
                shutil.copy2(path, files_dir / snapshot_name)
                entry["snapshot"] = f"files/{snapshot_name}"
                entry["size"] = path.stat().st_size
            manifest["files"].append(entry)

        (temp_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        checkpoint_dir = checkpoints_dir / checkpoint_id
        temp_dir.rename(checkpoint_dir)
        _prune_workspace_checkpoints(checkpoints_dir, retention)
        return _checkpoint_public_manifest(manifest, checkpoint_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def restore_workspace_checkpoint(
    checkpoint: dict[str, Any] | str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Restore files captured by create_workspace_checkpoint."""

    manifest, checkpoint_dir = _load_checkpoint_manifest(checkpoint)
    workspace = Path(root or manifest.get("root") or ".").expanduser().resolve()
    restored: list[str] = []
    removed: list[str] = []
    errors: list[dict[str, str]] = []
    for entry in manifest.get("files", []):
        if not isinstance(entry, dict):
            continue
        relative = str(entry.get("path") or "")
        try:
            target = _canonical_workspace_path(workspace, relative, allow_missing=True)
            if entry.get("exists"):
                snapshot = entry.get("snapshot")
                if not isinstance(snapshot, str) or not snapshot:
                    raise ToolError(f"Checkpoint entry for {relative} is missing a snapshot")
                target.parent.mkdir(parents=True, exist_ok=True)
                _atomic_copy_file(checkpoint_dir / snapshot, target)
                restored.append(relative)
            else:
                if target.exists():
                    if not target.is_file():
                        raise ToolError(f"Refusing to remove non-file path during restore: {relative}")
                    target.unlink()
                    removed.append(relative)
        except Exception as exc:
            errors.append({"path": relative, "error": str(exc)})
    return {
        "ok": not errors,
        "checkpoint_id": str(manifest.get("id") or ""),
        "restored_files": restored,
        "removed_files": removed,
        "errors": errors,
    }


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
            "repo_map": 'repo_map args: {"path":".","target":"module_or_file","limit":80}',
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
            "repo_map",
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
        prefer_patches = _truthy(
            _request_option(
                self.request,
                "prefer_multi_file_patches",
                self.config.prefer_multi_file_patches,
            )
        )
        context_bar_mode = str(
            _request_option(
                self.request,
                "context_change_bar_mode",
                self.config.context_change_bar_mode,
            )
            or "light"
        ).strip().lower()
        if context_bar_mode not in {"off", "light", "strict"}:
            context_bar_mode = "light"
        context_bar_enabled = (
            _truthy(
                _request_option(
                    self.request,
                    "context_change_bar_enabled",
                    self.config.context_change_bar_enabled,
                )
            )
            and context_bar_mode != "off"
        )
        try:
            context_bar_threshold = int(
                _request_option(
                    self.request,
                    "context_change_bar_threshold",
                    self.config.context_change_bar_threshold,
                )
            )
        except (TypeError, ValueError):
            context_bar_threshold = 3
        context_bar_threshold = max(0, min(context_bar_threshold, 50))
        patch_mode = (
            "PATCH-FIRST MODE is enabled: inspect broadly, batch related edits, and use apply_patch for multi-file work and all validation repairs."
            if prefer_patches
            else "Patch batching is available: use apply_patch when it keeps the change safer or clearer."
        )
        context_bar = (
            f"CONTEXT CHANGE BAR is enabled ({context_bar_mode}, threshold {context_bar_threshold} changed files): refresh repository context with repo_map, search_files, or read_file before edits when context is stale or the task spans files/modules/tests/config/docs."
            if context_bar_enabled
            else "CONTEXT CHANGE BAR is off for this run."
        )
        repository_snapshot = self._repository_snapshot()

        return "\n".join(
            [
                "You are an autonomous local coding agent running inside the user's workspace.",
                "Work like a professional code reviewer and implementer: inspect thoroughly, plan multi-file changes, and validate thoroughly.",
                "Use tools for file inspection, file creation, and coordinated edits. Do not invent file contents you have not inspected.",
                patch_mode,
                context_bar,
                "",
                "REPOSITORY-AWARE PLANNING:",
                "- Start non-trivial coding tasks with repo_map or list/search/read calls before editing.",
                "- Inspect active files, neighboring files, imports/usages, related tests, configs, and public interfaces.",
                "- Build one mental edit plan before applying changes; avoid serial one-line edits when a grouped patch is clearer.",
                "- If a task touches behavior, look for matching tests or examples before editing.",
                "",
                "MULTI-FILE EDITING WORKFLOW (PREFERRED for most tasks):",
                "1. Inspect all relevant files before planning edits.",
                "2. If more than one file needs changes, use apply_patch with all changes together.",
                "3. Group related changes: implementation, tests, configs, docs in one patch.",
                "4. Include a validation plan with the patch (tests, linting, compile checks).",
                "5. Minimize approval prompts by preparing one coherent grouped patch.",
                "6. If validation fails, repair from the restored checkpoint with apply_patch.",
                "",
                "SINGLE-FILE EDITS (only for specific cases):",
                "- Creating brand-new files (when content is provided or fully specified)",
                "- Full file rewrites (when you've read and need to completely replace entire file)",
                "- Tiny surgical edits (3-5 line changes in already-inspected files)",
                "- AVOID: Stop using single-file edits after validation failures - use apply_patch for repairs",
                "",
                "FILE CHANGE CONSIDERATIONS:",
                "- When fixing a bug, also update related tests and documentation",
                "- When implementing a feature, check for config files, setup files, and examples",
                "- When refactoring code, ensure validation runs (lint, tests, compile checks)",
                "- Multi-file consistency is more important than single-file speed",
                "",
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
                "Repository snapshot:",
                repository_snapshot,
                "Available tools:",
                *[f"- {tool}" for tool in tools],
            ]
        )

    def run(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        checkpoint: dict[str, Any] | None = None
        rollback_result: dict[str, Any] | None = None
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
            
            if self._is_mutating_tool(name):
                checkpoint = self._create_edit_checkpoint(name, args)
            try:
                if name == "list_files":
                    result = self._list_files(args)
                elif name == "read_file":
                    result = self._read_file(args)
                elif name == "search_files":
                    result = self._search_files(args)
                elif name == "repo_map":
                    result = self._repo_map(args)
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
            except BaseException:
                if checkpoint is not None:
                    rollback_result = self._restore_checkpoint_safely(checkpoint)
                raise
            response = {"ok": True, "tool": name, "result": result}
            if checkpoint is not None:
                response["checkpoint"] = checkpoint
            if approval_needed and self._approval_granted():
                response["approval_granted"] = True
            return response
        except Exception as exc:
            response = {"ok": False, "tool": name, "error": str(exc)}
            if checkpoint is not None:
                response["checkpoint"] = checkpoint
            if rollback_result is not None:
                response["rollback"] = rollback_result
            return response

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

    def _create_edit_checkpoint(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        paths = self._checkpoint_paths_for_edit(name, args)
        retention = _positive_int(
            _request_option(
                self.request,
                "workspace_checkpoint_retention",
                self.config.workspace_checkpoint_retention,
            ),
            default=self.config.workspace_checkpoint_retention,
            maximum=MAX_CHECKPOINT_RETENTION,
        )
        return create_workspace_checkpoint(
            self.root,
            paths,
            state_dir=self._checkpoint_state_dir(),
            retention=retention,
            reason=f"before {name}",
        )

    def _checkpoint_paths_for_edit(self, name: str, args: dict[str, Any]) -> list[Path]:
        if name == "write_file":
            path = self._resolve_required_path(args, "path")
            self._guard_edit_target(args.get("path"), path)
            return [path]
        if name == "replace_in_file":
            path = self._resolve_required_path(args, "path", existing=True)
            self._guard_edit_target(args.get("path"), path)
            return [path]
        if name == "apply_patch":
            return [change["absolute_path"] for change in self._patch_plan(args)["changes"]]
        return []

    def _checkpoint_state_dir(self) -> Path:
        value = _request_option(self.request, "state_dir", self.config.state_dir)
        path = Path(value).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (self.root / path).resolve()

    def _restore_checkpoint_safely(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        try:
            return restore_workspace_checkpoint(checkpoint, root=self.root)
        except Exception as exc:
            return {
                "ok": False,
                "checkpoint_id": str(checkpoint.get("id") or ""),
                "restored_files": [],
                "removed_files": [],
                "errors": [{"path": "", "error": str(exc)}],
            }

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
            "risk_level": details["risk_level"],
            "summary": details["summary"],
            "impact": details["impact"],
            "estimated_impact": details["estimated_impact"],
            "file_groups": details["file_groups"],
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
                    **_approval_intelligence(name, [], "", commands),
                }
            return {
                "affected_files": [change["path"] for change in plan["changes"]],
                "summary": plan["summary"],
                "patch_preview": plan["patch_preview"],
                "commands": commands,
                "validation_plan": validation_plan,
                **_approval_intelligence(
                    name,
                    [change["path"] for change in plan["changes"]],
                    plan["patch_preview"],
                    commands,
                ),
            }
        if name in {"write_file", "replace_in_file"}:
            try:
                preview = self._single_edit_preview(name, args)
            except ToolError as exc:
                preview = f"Invalid edit: {exc}"
            affected_files = self._get_affected_files(name, args)
            return {
                "affected_files": affected_files,
                "summary": self._get_risk_summary(name, args),
                "patch_preview": preview,
                "commands": commands,
                "validation_plan": validation_plan,
                **_approval_intelligence(name, affected_files, preview, commands),
            }
        affected_files: list[str] = []
        shell_commands = [str(args.get("command", ""))] if name == "run_command" else commands
        return {
            "affected_files": affected_files,
            "summary": self._get_risk_summary(name, args),
            "patch_preview": "",
            "commands": shell_commands,
            "validation_plan": validation_plan,
            **_approval_intelligence(name, affected_files, "", shell_commands),
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
            if self._is_skipped(item) or not self._is_safe_workspace_path(item):
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
            if self._is_skipped(path) or not self._is_safe_workspace_path(path) or not path.is_file():
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

    def _repo_map(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _positive_int(args.get("limit"), default=MAX_REPO_MAP_FILES, maximum=300)
        focus = self._repo_map_focus(args)
        files = self._workspace_text_files(limit=max(limit * 4, MAX_REPO_MAP_FILES))
        active = [self._relative(path) for path in self._request_context_paths() if path.is_file()]
        mentioned = [
            self._relative(path)
            for path in self._request_mentioned_paths()
            if path.is_file()
        ]
        configs = [_relative for path in files if (_relative := self._relative(path)) and _is_config_file(path)]
        tests = [_relative for path in files if (_relative := self._relative(path)) and _is_test_file(path)]
        related = self._related_repo_files(files, focus=focus, active_paths=[*active, *mentioned], limit=limit)
        dependency_map, dependency_files, import_hints = _repo_dependency_map(
            self.root,
            related[: min(limit, 30)],
        )
        reverse_dependency_map = _reverse_dependency_map(
            self.root,
            [self._relative(path) for path in files[: min(len(files), 200)]],
        )
        if dependency_files:
            related = _dedupe([*related, *dependency_files])[:limit]
        symbol_index = _symbol_index(self.root, related[:limit])
        symbols = {path: value for path, value in list(symbol_index.items())[:12] if value}
        validation_targets = _repo_validation_targets(related, tests, reverse_dependency_map, dependency_files)
        return {
            "root": str(self.root),
            "focus": focus,
            "active_files": active,
            "mentioned_files": mentioned,
            "key_files": _dedupe([*configs[:20], *tests[:20]])[:40],
            "related_files": related[:limit],
            "test_files": tests[:limit],
            "dependency_files": dependency_files[:limit],
            "dependency_map": dependency_map,
            "reverse_dependency_map": {
                path: dependents
                for path, dependents in reverse_dependency_map.items()
                if path in related or path in dependency_files
            },
            "symbols": symbols,
            "symbol_index": symbol_index,
            "reference_hints": _reference_hints(focus, symbol_index, reverse_dependency_map),
            "validation_targets": validation_targets,
            "search_hints": _dedupe([*_repo_search_hints(focus, related), *import_hints])[:12],
            "edit_guidance": (
                "Inspect related files, then use one grouped apply_patch for coordinated edits. "
                "Use write_file only for new generated files."
            ),
        }

    def _repository_snapshot(self) -> str:
        try:
            files = self._workspace_text_files(limit=MAX_REPO_MAP_FILES)
        except Exception:
            return "- Repository map unavailable; use repo_map or list_files to inspect."
        active = [self._relative(path) for path in self._request_context_paths() if path.exists()]
        configs = [self._relative(path) for path in files if _is_config_file(path)][:10]
        tests = [self._relative(path) for path in files if _is_test_file(path)][:10]
        top_level = [self._relative(path) for path in files if len(path.relative_to(self.root).parts) == 1][:12]
        lines = [
            f"- Active files: {', '.join(active) if active else 'none'}",
            f"- Key configs: {', '.join(configs) if configs else 'none detected'}",
            f"- Tests: {', '.join(tests) if tests else 'none detected'}",
            f"- Top-level files: {', '.join(top_level) if top_level else 'none detected'}",
            "- Use repo_map with a target before non-trivial edits to find related files and tests.",
        ]
        return "\n".join(lines)

    def _repo_map_focus(self, args: dict[str, Any]) -> str:
        target = str(args.get("target") or "").strip()
        path_value = str(args.get("path") or "").strip()
        if target:
            return target
        if path_value and path_value != ".":
            return path_value
        paths = self._request_context_paths() or self._request_mentioned_paths()
        if paths:
            return self._relative(paths[0])
        return _short_task_focus(self.request)

    def _workspace_text_files(self, *, limit: int) -> list[Path]:
        files: list[Path] = []
        pending = [self.root]
        while pending and len(files) < limit:
            directory = pending.pop(0)
            try:
                children = sorted(directory.iterdir(), key=lambda path: (path.is_file(), path.name.lower()))
            except OSError:
                continue
            for path in children:
                if self._is_skipped(path) or not self._is_safe_workspace_path(path):
                    continue
                if path.is_dir():
                    pending.append(path)
                    continue
                if _is_probably_text_file(path):
                    files.append(path)
                    if len(files) >= limit:
                        break
        return files

    def _request_mentioned_paths(self) -> list[Path]:
        paths: list[Path] = []
        seen: set[Path] = set()
        for token in _path_like_tokens(_request_text_for_paths(self.request)):
            try:
                path = self._resolve_existing(token)
            except ToolError:
                continue
            if path.exists() and path not in seen:
                seen.add(path)
                paths.append(path)
        return paths

    def _related_repo_files(
        self,
        files: list[Path],
        *,
        focus: str,
        active_paths: list[str],
        limit: int,
    ) -> list[str]:
        scores: dict[str, float] = {}
        focus_path = Path(focus.replace("\\", "/"))
        focus_stem = focus_path.stem.lower() if focus_path.name else focus.lower()
        focus_tokens = {token for token in re.split(r"[^A-Za-z0-9_]+", focus.lower()) if len(token) >= 3}
        active_dirs = {str(Path(path).parent).replace("\\", "/") for path in active_paths}
        for path in files:
            relative = self._relative(path)
            lowered = relative.lower()
            name = path.name.lower()
            score = 0.0
            if relative in active_paths:
                score += 12.0
            if focus and focus.lower() in lowered:
                score += 8.0
            if focus_stem and focus_stem in path.stem.lower():
                score += 7.0
            if Path(relative).parent.as_posix() in active_dirs:
                score += 4.0
            if _is_test_file(path):
                score += 3.0 if focus_stem and focus_stem in name else 1.0
            if _is_config_file(path):
                score += 2.0
            if any(token in lowered for token in focus_tokens):
                score += 2.0
            if score <= 0 and len(scores) < max(20, limit // 3):
                score = 0.1
            if score > 0:
                scores[relative] = score
        return [
            path
            for path, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        ][:limit]

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
                _atomic_write_text(path, content)
        except Exception as exc:
            for path, original in originals.items():
                try:
                    if original is None:
                        if path.exists():
                            path.unlink()
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        _atomic_write_text(path, original)
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
            before = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            _atomic_write_text(path, before + content)
        else:
            _atomic_write_text(path, content)
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
        _atomic_write_text(path, updated)
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
                if self._is_skipped(path) or not self._is_safe_workspace_path(path):
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
        if any(part in SKIPPED_DIRS for part in parts):
            return True
        return self._is_runtime_path(path)

    def _is_safe_workspace_path(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        return resolved == self.root or resolved.is_relative_to(self.root)

    def _is_runtime_path(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        for runtime_root in self._runtime_roots():
            if resolved == runtime_root or resolved.is_relative_to(runtime_root):
                return True
        return False

    def _runtime_roots(self) -> list[Path]:
        roots: list[Path] = []
        for key in RUNTIME_DIR_OPTIONS:
            default = getattr(self.config, key)
            value = _request_option(self.request, key, default)
            root = _workspace_relative_config_path(self.root, value)
            if root is not None:
                roots.append(root)
        return _dedupe_paths(roots)

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


def _checkpoint_base_dir(root: Path, state_dir: str | Path | None) -> Path:
    if state_dir is None:
        base = root / ".agent-hub" / "state"
    else:
        base = Path(state_dir).expanduser()
        if not base.is_absolute():
            base = root / base
    return base.resolve() / "workspace-checkpoints"


def _unique_checkpoint_paths(root: Path, paths: list[str | Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for value in paths:
        path = _canonical_workspace_path(root, value, allow_missing=True)
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _canonical_workspace_path(
    root: Path,
    value: str | Path,
    *,
    allow_missing: bool,
) -> Path:
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else root / raw
    try:
        resolved = candidate.resolve()
    except OSError:
        if not allow_missing:
            raise
        resolved = candidate.parent.resolve() / candidate.name
    if resolved != root and not resolved.is_relative_to(root):
        raise ToolError(f"Path escapes workspace: {value}")
    return resolved


def _relative_to_workspace(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except ValueError:
        raise ToolError(f"Path escapes workspace: {path}") from None


def _workspace_relative_config_path(root: Path, value: Any) -> Path | None:
    if value is None:
        return None
    try:
        path = Path(value).expanduser()
        resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    except (OSError, TypeError, ValueError):
        return None
    return resolved if resolved == root or resolved.is_relative_to(root) else None


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _checkpoint_public_manifest(manifest: dict[str, Any], checkpoint_dir: Path) -> dict[str, Any]:
    files = manifest.get("files", [])
    paths = [
        str(entry.get("path"))
        for entry in files
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    ]
    return {
        "id": str(manifest.get("id") or ""),
        "created_at": manifest.get("created_at"),
        "root": str(manifest.get("root") or ""),
        "reason": str(manifest.get("reason") or ""),
        "paths": paths,
        "checkpoint_dir": str(checkpoint_dir),
    }


def _load_checkpoint_manifest(
    checkpoint: dict[str, Any] | str | Path,
) -> tuple[dict[str, Any], Path]:
    if isinstance(checkpoint, dict):
        checkpoint_dir_value = checkpoint.get("checkpoint_dir") or checkpoint.get("path")
        if not isinstance(checkpoint_dir_value, str) or not checkpoint_dir_value:
            raise ToolError("Checkpoint metadata is missing checkpoint_dir")
        checkpoint_dir = Path(checkpoint_dir_value).expanduser().resolve()
    else:
        checkpoint_dir = Path(checkpoint).expanduser().resolve()
    manifest_path = checkpoint_dir / "manifest.json"
    if not manifest_path.exists():
        raise ToolError(f"Checkpoint manifest does not exist: {checkpoint_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8")), checkpoint_dir


def _prune_workspace_checkpoints(checkpoints_dir: Path, retention: int) -> None:
    keep = _positive_int(retention, default=5, maximum=MAX_CHECKPOINT_RETENTION)
    manifests: list[tuple[float, Path]] = []
    for child in checkpoints_dir.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        manifest_path = child / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            created_at = float(manifest.get("created_at", 0.0))
        except Exception:
            created_at = child.stat().st_mtime
        manifests.append((created_at, child))
    for _, child in sorted(manifests, reverse=True)[keep:]:
        shutil.rmtree(child, ignore_errors=True)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _atomic_copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            delete=False,
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        ) as handle:
            temp_name = handle.name
            with source.open("rb") as source_handle:
                shutil.copyfileobj(source_handle, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def _request_text_for_paths(request: HubRequest) -> str:
    parts: list[str] = []
    if request.task:
        parts.append(str(request.task))
    if request.context:
        parts.append(str(request.context))
    for message in request.messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def _short_task_focus(request: HubRequest) -> str:
    text = _request_text_for_paths(request)
    words = [word for word in re.split(r"\s+", text.strip()) if word]
    return " ".join(words[:12])[:160] or "workspace"


def _path_like_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    pattern = re.compile(
        r"(?<![A-Za-z0-9_./\\-])"
        r"([A-Za-z0-9_.-]+(?:[/\\][A-Za-z0-9_.-]+)+|[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8})"
    )
    for match in pattern.finditer(text):
        token = match.group(1).strip().strip(".,:;()[]{}\"'")
        if token and token not in {".", ".."} and token not in tokens:
            tokens.append(token)
    return tokens[:30]


def _is_probably_text_file(path: Path) -> bool:
    if path.name.lower() in {
        "makefile",
        "dockerfile",
        "license",
        "readme",
    }:
        return True
    return path.suffix.lower() in {
        ".bat",
        ".cfg",
        ".css",
        ".env",
        ".go",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".ps1",
        ".py",
        ".rs",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }


def _is_config_file(path: Path) -> bool:
    lowered = path.name.lower()
    if lowered in {
        "package.json",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "tox.ini",
        "tsconfig.json",
        "eslint.config.js",
        "vite.config.js",
        "webpack.config.js",
        "agent-hub.config.json",
    }:
        return True
    return path.suffix.lower() in {".toml", ".yaml", ".yml", ".ini", ".cfg"}


def _is_test_file(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return (
        "tests" in parts
        or "test" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.js")
        or name.endswith(".spec.js")
        or name.endswith(".test.ts")
        or name.endswith(".spec.ts")
    )


def _file_symbols(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    symbols: list[str] = []
    patterns = [
        re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE),
        re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.MULTILINE),
        re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", re.MULTILINE),
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=", re.MULTILINE),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text):
            symbol = match.group(1)
            if symbol not in symbols:
                symbols.append(symbol)
            if len(symbols) >= MAX_SYMBOLS_PER_FILE:
                return symbols
    return symbols


def _repo_dependency_map(root: Path, related_files: list[str]) -> tuple[dict[str, list[str]], list[str], list[str]]:
    dependency_map: dict[str, list[str]] = {}
    dependency_files: list[str] = []
    import_hints: list[str] = []
    for relative in related_files:
        source = root / relative
        dependencies = _file_dependencies(source)
        resolved: list[str] = []
        for dependency in dependencies:
            resolved.extend(_resolve_dependency_files(root, relative, dependency))
        resolved = _dedupe(resolved)
        if resolved:
            dependency_map[relative] = resolved
            dependency_files.extend(resolved)
        for dependency in dependencies[:4]:
            hint = dependency.lstrip(".")
            if hint and not hint.startswith(("/", "\\")):
                import_hints.append(f"search_files query: {hint.split('.')[-1]}")
    return dependency_map, _dedupe(dependency_files), _dedupe(import_hints)


def _reverse_dependency_map(root: Path, files: list[str]) -> dict[str, list[str]]:
    reverse: dict[str, list[str]] = {}
    for relative in files:
        dependencies = _file_dependencies(root / relative)
        for dependency in dependencies:
            for resolved in _resolve_dependency_files(root, relative, dependency):
                reverse.setdefault(resolved, []).append(relative)
    return {
        path: _dedupe(dependents)[:MAX_REPO_MAP_FILES]
        for path, dependents in reverse.items()
        if dependents
    }


def _symbol_index(root: Path, files: list[str]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for relative in files[:MAX_REPO_MAP_FILES]:
        path = root / relative
        if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".jsx"}:
            continue
        symbols = _file_symbols(path)
        if symbols:
            index[relative] = symbols
    return index


def _reference_hints(
    focus: str,
    symbol_index: dict[str, list[str]],
    reverse_dependency_map: dict[str, list[str]],
) -> list[str]:
    hints: list[str] = []
    focus_stem = Path(focus.replace("\\", "/")).stem
    if focus_stem:
        hints.append(f"search_files query: {focus_stem}")
    for path, symbols in list(symbol_index.items())[:8]:
        for symbol in symbols[:4]:
            hints.append(f"search_files query: {symbol}")
        if path in reverse_dependency_map:
            hints.extend(f"read_file path: {dependent}" for dependent in reverse_dependency_map[path][:4])
    return _dedupe(hints)[:12]


def _repo_validation_targets(
    related: list[str],
    tests: list[str],
    reverse_dependency_map: dict[str, list[str]],
    dependency_files: list[str],
) -> list[str]:
    targets: list[str] = []
    related_names = {Path(path).stem.lower().removeprefix("test_") for path in related[:20]}
    for test in tests:
        stem = Path(test).stem.lower().removeprefix("test_")
        if stem in related_names or any(name and name in stem for name in related_names):
            targets.append(test)
    for path in [*related[:10], *dependency_files[:10]]:
        targets.extend(reverse_dependency_map.get(path, []))
    targets.extend(path for path in related[:10] if _is_test_file(rootless_path(path)))
    return _dedupe(targets)[:MAX_REPO_MAP_FILES]


def rootless_path(path: str) -> Path:
    return Path(path.replace("\\", "/"))


def _file_dependencies(path: Path) -> list[str]:
    if path.suffix.lower() == ".py":
        return _python_dependencies(path)
    if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
        return _javascript_dependencies(path)
    return []


def _python_dependencies(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    dependencies: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        patterns = [
            re.compile(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_.]*)", re.MULTILINE),
            re.compile(r"^\s*from\s+(\.*[A-Za-z_][A-Za-z0-9_.]*)\s+import\s+", re.MULTILINE),
        ]
        for pattern in patterns:
            dependencies.extend(match.group(1) for match in pattern.finditer(text))
        return _dedupe(dependencies)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            dependencies.extend(alias.name for alias in node.names if alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            prefix = "." * int(node.level or 0)
            if module:
                dependencies.append(prefix + module)
            else:
                dependencies.extend(prefix + alias.name for alias in node.names if alias.name)
    return _dedupe(dependencies)


def _javascript_dependencies(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    patterns = [
        re.compile(r"\bfrom\s+['\"]([^'\"]+)['\"]"),
        re.compile(r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"),
        re.compile(r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"),
    ]
    dependencies: list[str] = []
    for pattern in patterns:
        dependencies.extend(match.group(1) for match in pattern.finditer(text))
    return _dedupe(dependencies)


def _resolve_dependency_files(root: Path, source_relative: str, dependency: str) -> list[str]:
    dependency = dependency.strip()
    if not dependency:
        return []
    if dependency.startswith("."):
        return _resolve_relative_dependency(root, source_relative, dependency)
    if dependency.startswith(("/", "\\")):
        return []
    module_path = dependency.replace(".", "/")
    return _existing_dependency_candidates(
        root,
        [
            module_path,
            f"{module_path}.py",
            f"{module_path}/__init__.py",
            f"{module_path}.js",
            f"{module_path}.ts",
            f"{module_path}.tsx",
            f"{module_path}.jsx",
        ],
    )


def _resolve_relative_dependency(root: Path, source_relative: str, dependency: str) -> list[str]:
    source_dir = Path(source_relative.replace("\\", "/")).parent
    if dependency.startswith(("./", "../")):
        base = source_dir / dependency
    else:
        level = len(dependency) - len(dependency.lstrip("."))
        remainder = dependency[level:].replace(".", "/")
        base = source_dir
        for _ in range(max(0, level - 1)):
            base = base.parent
        if remainder:
            base = base / remainder
    normalized = str(base).replace("\\", "/")
    return _existing_dependency_candidates(
        root,
        [
            normalized,
            f"{normalized}.py",
            f"{normalized}/__init__.py",
            f"{normalized}.js",
            f"{normalized}.ts",
            f"{normalized}.tsx",
            f"{normalized}.jsx",
            f"{normalized}/index.js",
            f"{normalized}/index.ts",
            f"{normalized}/index.tsx",
        ],
    )


def _existing_dependency_candidates(root: Path, candidates: list[str]) -> list[str]:
    resolved: list[str] = []
    for candidate in candidates:
        path = (root / candidate).resolve()
        try:
            if path != root and not path.is_relative_to(root):
                continue
        except ValueError:
            continue
        if path.is_file():
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            resolved.append(relative)
    return _dedupe(resolved)


def _repo_search_hints(focus: str, related_files: list[str]) -> list[str]:
    hints: list[str] = []
    focus_stem = Path(focus.replace("\\", "/")).stem
    if focus_stem:
        hints.append(f"search_files query: {focus_stem}")
    for path in related_files[:5]:
        stem = Path(path).stem
        if stem and stem != focus_stem:
            hints.append(f"search_files query: {stem}")
    return _dedupe(hints)[:8]


def _approval_intelligence(
    tool_name: str,
    affected_files: list[str],
    patch_preview: str,
    commands: list[str],
) -> dict[str, Any]:
    additions = sum(1 for line in patch_preview.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in patch_preview.splitlines() if line.startswith("-") and not line.startswith("---"))
    file_groups = _file_groups(affected_files)
    risk_level = _risk_level(tool_name, affected_files, additions, deletions, commands)
    impact_bits: list[str] = []
    if affected_files:
        impact_bits.append(f"{len(affected_files)} file(s)")
    if additions or deletions:
        impact_bits.append(f"+{additions}/-{deletions} line(s)")
    if commands:
        impact_bits.append(f"{len(commands)} planned command(s)")
    if file_groups:
        impact_bits.append("groups: " + ", ".join(group["group"] for group in file_groups[:4]))
    return {
        "risk_level": risk_level,
        "impact": ", ".join(impact_bits) if impact_bits else "No file changes detected.",
        "estimated_impact": {
            "files": len(affected_files),
            "additions": additions,
            "deletions": deletions,
            "commands": len(commands),
        },
        "file_groups": file_groups,
    }


def _file_groups(paths: list[str]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for path in paths:
        lowered = path.lower()
        if "/test" in lowered or lowered.startswith("test") or "\\test" in lowered:
            group = "tests"
        elif lowered.endswith((".md", ".txt", ".rst")):
            group = "docs"
        elif lowered.endswith((".json", ".toml", ".yaml", ".yml", ".ini", ".cfg")):
            group = "config"
        elif lowered.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs")):
            group = "implementation"
        else:
            group = "other"
        groups.setdefault(group, []).append(path)
    return [
        {"group": group, "files": files}
        for group, files in sorted(groups.items(), key=lambda item: item[0])
    ]


def _risk_level(
    tool_name: str,
    affected_files: list[str],
    additions: int,
    deletions: int,
    commands: list[str],
) -> str:
    total_lines = additions + deletions
    command_text = " ".join(commands).lower()
    if tool_name == "run_command" and any(token in command_text for token in (" rm ", "git reset", "delete", "del ")):
        return "high"
    if len(affected_files) >= 8 or total_lines > 600:
        return "high"
    if len(affected_files) >= 3 or total_lines > 120 or commands:
        return "medium"
    return "low"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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
