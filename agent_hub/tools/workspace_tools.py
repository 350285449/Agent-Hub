"""Workspace tool orchestration layer.

AgentToolbox remains the single runtime boundary for provider-facing workspace
operations, while schemas, patch parsing, repository search helpers, checkpoint
state, and safety utilities live in smaller sibling modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import HubConfig
from ..enterprise import EnterprisePolicy, enterprise_subject_from_request, enterprise_workspace_from_request
from ..models import HubRequest
from ..observability import record_event
from ..permissions import (
    PermissionDecision,
    PermissionManager,
    PermissionRequest,
    approval_granted_from_request,
    approval_mode_from_request,
    tool_permission_request,
)
from ..security.command_runner import CommandExecutionRequest, run_workspace_command
from ..agent_tool_dispatch import MUTATING_AGENT_TOOLS, dispatch_agent_tool
from .workspace_files import (
    AGENT_TOOL_DEFINITIONS,
    RUN_COMMAND_TOOL_DEFINITION,
    agent_tool_definitions,
)
from .workspace_patch import (
    _apply_unified_hunks,
    _diff_path,
    _parse_unified_diff,
    _simple_unified_diff,
)
from .workspace_safety import (
    MAX_CHECKPOINT_RETENTION,
    MAX_COMMAND_TIMEOUT_SECONDS,
    MAX_FILE_CHARS,
    MAX_PATCH_CHARS,
    MAX_PATH_HINTS,
    MAX_REPLACE_CHARS,
    MAX_REPO_MAP_FILES,
    MAX_SYMBOLS_PER_FILE,
    MAX_TOOL_OUTPUT_CHARS,
    RUNTIME_DIR_OPTIONS,
    SKIPPED_DIRS,
    ShellPermissionCallback,
    ToolError,
    _approval_intelligence,
    _dedupe,
    _file_groups,
    _is_bare_filename,
    _matches_repo_ignore,
    _normalize_shell_policy,
    _positive_int,
    _request_option,
    _risk_level,
    _shell_instruction,
    _string_list,
    _truthy,
    tool_result_message,
)
from .workspace_search import (
    _existing_dependency_candidates,
    _file_dependencies,
    _file_symbols,
    _is_config_file,
    _is_probably_text_file,
    _is_test_file,
    _javascript_dependencies,
    _path_like_tokens,
    _python_dependencies,
    _reference_hints,
    _repo_dependency_map,
    _repo_search_hints,
    _repo_validation_targets,
    _request_text_for_paths,
    _resolve_dependency_files,
    _resolve_relative_dependency,
    _reverse_dependency_map,
    _short_task_focus,
    _symbol_index,
    rootless_path,
)
from .workspace_state import (
    _atomic_copy_file,
    _atomic_write_text,
    _canonical_workspace_path,
    _checkpoint_base_dir,
    _checkpoint_public_manifest,
    _dedupe_paths,
    _load_checkpoint_manifest,
    _prune_workspace_checkpoints,
    _relative_to_workspace,
    _unique_checkpoint_paths,
    _workspace_relative_config_path,
    create_workspace_checkpoint,
    restore_workspace_checkpoint,
)


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
        decision: PermissionDecision | None = None
        try:
            allowed = self.allowed_tool_names
            if allowed is not None and name not in allowed:
                raise ToolError(f"Tool {name!r} is not available for this agent stage")
            
            decision = self._permission_decision(name, args)
            self._record_permission_event(name, args, decision)
            if decision.requires_approval:
                return self._request_approval(name, args, decision)
            if not decision.allowed:
                return {
                    "ok": False,
                    "tool": name,
                    "permission_denied": True,
                    "permission": decision.to_dict(),
                    "error": decision.reason or f"Permission denied for tool {name}.",
                }
            
            if self._is_mutating_tool(name):
                checkpoint = self._create_edit_checkpoint(name, args)
            try:
                result = dispatch_agent_tool(self, name, args)
            except BaseException:
                if checkpoint is not None:
                    rollback_result = self._restore_checkpoint_safely(checkpoint)
                raise
            response = {"ok": True, "tool": name, "result": result}
            if checkpoint is not None:
                response["checkpoint"] = checkpoint
            if decision.sensitive and self._approval_granted():
                response["approval_granted"] = True
            self._record_tool_event(name, args, response)
            return response
        except Exception as exc:
            response = {"ok": False, "tool": name, "error": str(exc)}
            if checkpoint is not None:
                response["checkpoint"] = checkpoint
            if rollback_result is not None:
                response["rollback"] = rollback_result
            if decision is not None:
                self._record_tool_event(name, args, response)
            return response

    def _permission_decision(self, name: str, args: dict[str, Any]) -> PermissionDecision:
        return PermissionManager(
            self._get_approval_mode(),
            approval_granted=self._approval_granted(),
            callback=self.shell_permission_callback,
            enterprise_policy=EnterprisePolicy.from_config(self.config),
            enterprise_user_id=enterprise_subject_from_request(self.request),
            enterprise_workspace_id=enterprise_workspace_from_request(self.config, self.request),
        ).check(tool_permission_request(name, args))

    def _is_approval_needed(self, name: str, args: dict[str, Any]) -> bool:
        """Determine if a tool requires approval based on the centralized manager."""

        decision = self._permission_decision(name, args)
        return decision.requires_approval

    def _get_approval_mode(self) -> str:
        return approval_mode_from_request(self.request, self.config.approval_mode)

    def _approval_granted(self) -> bool:
        return approval_granted_from_request(self.request)

    def _record_permission_event(
        self,
        name: str,
        args: dict[str, Any],
        decision: PermissionDecision,
    ) -> None:
        try:
            record_event(
                self.config.state_dir,
                "permissions",
                {
                    "type": "tool_permission",
                    "session_id": self.request.session_id,
                    "tool": name,
                    "allowed": decision.allowed,
                    "requires_approval": decision.requires_approval,
                    "denied": decision.denied,
                    "reason": decision.reason,
                    "mode": decision.mode,
                    "category": decision.request.category if decision.request else "",
                    "risk_level": decision.request.risk_level if decision.request else "",
                    "resource": decision.request.resource if decision.request else "",
                },
            )
        except Exception:
            return

    def _record_tool_event(self, name: str, args: dict[str, Any], response: dict[str, Any]) -> None:
        try:
            record_event(
                self.config.state_dir,
                "tools",
                {
                    "type": "tool_execution",
                    "session_id": self.request.session_id,
                    "tool": name,
                    "ok": response.get("ok") is not False,
                    "approval_required": bool(response.get("approval_required")),
                    "permission_denied": bool(response.get("permission_denied")),
                    "error": response.get("error", ""),
                    "paths": self._get_affected_files(name, args),
                },
            )
        except Exception:
            return

    def _is_mutating_tool(self, name: str) -> bool:
        return name in MUTATING_AGENT_TOOLS

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

    def _request_approval(
        self,
        name: str,
        args: dict[str, Any],
        decision: PermissionDecision | None = None,
    ) -> dict[str, Any]:
        """Return an approval required result."""
        details = self._approval_details(name, args)
        permission = decision.to_dict() if decision else PermissionDecision(
            allowed=False,
            requires_approval=True,
            mode=self._get_approval_mode(),
            request=tool_permission_request(name, args),
        ).to_dict()
        return {
            "ok": False,
            "approval_required": True,
            "permission_required": True,
            "permission": permission,
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
        completed = run_workspace_command(
            CommandExecutionRequest(
                command=command,
                workspace_dir=self.root,
                cwd=cwd,
                timeout_seconds=timeout,
                state_dir=self.config.state_dir,
                source="agent_toolbox.run_command",
            )
        )
        return {
            "command": command,
            "cwd": completed.cwd,
            "returncode": completed.returncode,
            "stdout": completed.stdout[:MAX_TOOL_OUTPUT_CHARS],
            "stderr": completed.stderr[:MAX_TOOL_OUTPUT_CHARS],
            "stdout_truncated": len(completed.stdout) > MAX_TOOL_OUTPUT_CHARS,
            "stderr_truncated": len(completed.stderr) > MAX_TOOL_OUTPUT_CHARS,
        }

    def _check_shell_permission(self, *, command: str, cwd: Path, timeout_seconds: int) -> None:
        if self.shell_command_policy != "ask":
            return
        if self._approval_granted() or self._get_approval_mode() in {"ask", "safe", "shell-ask"}:
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
            relative = path.relative_to(self.root).as_posix()
        except ValueError:
            parts = path.parts
            relative = path.as_posix()
        if any(part in SKIPPED_DIRS for part in parts):
            return True
        if _matches_repo_ignore(relative, getattr(self.config, "repo_ignore_patterns", [])):
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


__all__ = [
    "SKIPPED_DIRS",
    "RUNTIME_DIR_OPTIONS",
    "MAX_FILE_CHARS",
    "MAX_TOOL_OUTPUT_CHARS",
    "MAX_REPLACE_CHARS",
    "MAX_PATCH_CHARS",
    "MAX_PATH_HINTS",
    "MAX_COMMAND_TIMEOUT_SECONDS",
    "MAX_CHECKPOINT_RETENTION",
    "MAX_REPO_MAP_FILES",
    "MAX_SYMBOLS_PER_FILE",
    "AGENT_TOOL_DEFINITIONS",
    "RUN_COMMAND_TOOL_DEFINITION",
    "ToolError",
    "ShellPermissionCallback",
    "agent_tool_definitions",
    "create_workspace_checkpoint",
    "restore_workspace_checkpoint",
    "AgentToolbox",
    "_checkpoint_base_dir",
    "_unique_checkpoint_paths",
    "_canonical_workspace_path",
    "_relative_to_workspace",
    "_workspace_relative_config_path",
    "_dedupe_paths",
    "_checkpoint_public_manifest",
    "_load_checkpoint_manifest",
    "_prune_workspace_checkpoints",
    "_atomic_write_text",
    "_atomic_copy_file",
    "_request_text_for_paths",
    "_short_task_focus",
    "_path_like_tokens",
    "_is_probably_text_file",
    "_is_config_file",
    "_is_test_file",
    "_file_symbols",
    "_repo_dependency_map",
    "_reverse_dependency_map",
    "_symbol_index",
    "_reference_hints",
    "_repo_validation_targets",
    "rootless_path",
    "_file_dependencies",
    "_python_dependencies",
    "_javascript_dependencies",
    "_resolve_dependency_files",
    "_resolve_relative_dependency",
    "_existing_dependency_candidates",
    "_repo_search_hints",
    "_approval_intelligence",
    "_file_groups",
    "_risk_level",
    "_dedupe",
    "_matches_repo_ignore",
    "_request_option",
    "_parse_unified_diff",
    "_diff_path",
    "_apply_unified_hunks",
    "_simple_unified_diff",
    "_string_list",
    "_truthy",
    "_shell_instruction",
    "_normalize_shell_policy",
    "_is_bare_filename",
    "_positive_int",
    "tool_result_message",
]
