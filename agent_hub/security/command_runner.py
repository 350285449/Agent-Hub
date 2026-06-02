from __future__ import annotations

import shlex
import subprocess
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from . import classify_shell_command
from ..observability import record_event


DEFAULT_ALLOWED_EXECUTABLES = {
    "cat",
    "cargo",
    "cmake",
    "dotnet",
    "echo",
    "git",
    "go",
    "gradle",
    "grep",
    "java",
    "ls",
    "make",
    "mvn",
    "node",
    "npm",
    "npx",
    "pip",
    "pip3",
    "pnpm",
    "py",
    "pytest",
    "python",
    "python3",
    "rg",
    "type",
    "uv",
    "yarn",
}
BLOCKED_SHELL_EXECUTABLES = {
    "bash",
    "cmd",
    "fish",
    "iex",
    "invoke-expression",
    "powershell",
    "pwsh",
    "sh",
    "zsh",
}
SHELL_SYNTAX = ("&", "|", ";", "<", ">", "\n", "\r")


class CommandRunnerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CommandExecutionRequest:
    command: str | Sequence[str]
    workspace_dir: str | Path
    cwd: str | Path | None = None
    timeout_seconds: int = 60
    allowed_executables: set[str] = field(default_factory=lambda: set(DEFAULT_ALLOWED_EXECUTABLES))
    state_dir: str | Path | None = None
    source: str = "command_runner"


@dataclass(frozen=True, slots=True)
class CommandExecutionResult:
    command: str
    argv: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    timeout_seconds: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timeout_seconds": self.timeout_seconds,
        }


def run_workspace_command(request: CommandExecutionRequest) -> CommandExecutionResult:
    workspace = Path(request.workspace_dir).expanduser().resolve()
    cwd = _resolve_cwd(workspace, request.cwd)
    timeout = max(1, min(int(request.timeout_seconds or 60), 600))
    argv = _command_argv(request.command)
    _validate_command(argv, request.command, allowed=request.allowed_executables)
    display = _display_command(request.command, argv)
    _record_command_event(request, display, argv, cwd, result=None)
    completed = subprocess.run(
        argv,
        cwd=str(cwd),
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    result = CommandExecutionResult(
        command=display,
        argv=argv,
        cwd=_relative_or_absolute(workspace, cwd),
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        timeout_seconds=timeout,
    )
    _record_command_event(request, display, argv, cwd, result=result)
    return result


def parse_command(command: str | Sequence[str]) -> list[str]:
    return _command_argv(command)


def _command_argv(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        if _contains_shell_syntax(command):
            raise CommandRunnerError("Shell operators and command chains are not allowed.")
        try:
            argv = shlex.split(command, posix=os.name != "nt")
        except ValueError as exc:
            raise CommandRunnerError(f"Could not parse command safely: {exc}") from exc
    else:
        argv = [str(part) for part in command]
    argv = [_strip_wrapping_quotes(part) for part in argv if part]
    if not argv:
        raise CommandRunnerError("Command is empty.")
    return argv


def _validate_command(
    argv: list[str],
    original: str | Sequence[str],
    *,
    allowed: set[str],
) -> None:
    display = _display_command(original, argv)
    assessment = classify_shell_command(display)
    if assessment.blocked:
        raise CommandRunnerError(assessment.reason or "Command is blocked by security policy.")
    executable = _executable_name(argv[0])
    if executable in BLOCKED_SHELL_EXECUTABLES:
        raise CommandRunnerError(f"Shell executable {executable!r} is not allowed.")
    normalized_allowed = {_normalize_executable(name) for name in allowed}
    if executable not in normalized_allowed:
        raise CommandRunnerError(f"Command executable {executable!r} is not allowlisted.")


def _resolve_cwd(workspace: Path, cwd: str | Path | None) -> Path:
    raw = Path(cwd or ".").expanduser()
    path = raw.resolve() if raw.is_absolute() else (workspace / raw).resolve()
    try:
        path.relative_to(workspace)
    except ValueError as exc:
        raise CommandRunnerError("Command cwd must stay inside the workspace.") from exc
    if not path.is_dir():
        raise CommandRunnerError(f"Command cwd is not a directory: {_relative_or_absolute(workspace, path)}")
    return path


def _contains_shell_syntax(command: str) -> bool:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(command):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single or in_double:
            continue
        if char in SHELL_SYNTAX:
            return True
        if char == "`":
            return True
        if command[index : index + 2] == "$(":
            return True
    return "%comspec%" in command.lower()


def _display_command(command: str | Sequence[str], argv: list[str]) -> str:
    if isinstance(command, str):
        return command.strip()
    return subprocess.list2cmdline(argv)


def _executable_name(value: str) -> str:
    return _normalize_executable(Path(value).name)


def _normalize_executable(value: str) -> str:
    name = value.strip().lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _record_command_event(
    request: CommandExecutionRequest,
    command: str,
    argv: list[str],
    cwd: Path,
    *,
    result: CommandExecutionResult | None,
) -> None:
    if request.state_dir is None:
        return
    try:
        record_event(
            request.state_dir,
            "security_audit",
            {
                "type": "command_execution",
                "source": request.source,
                "command": command[:500],
                "argv": argv[:20],
                "cwd": str(cwd),
                "allowed": True,
                "returncode": result.returncode if result is not None else None,
            },
        )
    except Exception:
        return


def _relative_or_absolute(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except ValueError:
        return str(path)
