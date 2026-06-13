from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..config import HubConfig
from ..models import HubRequest
from ..tools.workspace_tools import AgentToolbox


@dataclass(slots=True)
class WorkspaceActionResult:
    action: str
    ok: bool
    result: dict[str, Any]
    dry_run: bool = False
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "ok": self.ok,
            "dry_run": self.dry_run,
            "result": dict(self.result),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round((self.finished_at - self.started_at) * 1000, 2),
        }


class SafeWorkspaceService:
    """Permission-aware workspace boundary for workflow-owned file and shell actions."""

    def __init__(self, config: HubConfig) -> None:
        self.config = config

    def run_shell_command(
        self,
        request: HubRequest,
        command: str,
        *,
        cwd: str = ".",
        timeout_seconds: int | None = None,
        dry_run: bool = False,
    ) -> WorkspaceActionResult:
        return self.run_tool(
            request,
            "run_command",
            {
                "command": command,
                "cwd": cwd,
                **({"timeout_seconds": timeout_seconds} if timeout_seconds is not None else {}),
                **({"dry_run": True} if dry_run else {}),
            },
            dry_run=dry_run,
        )

    def apply_file_action(
        self,
        request: HubRequest,
        tool_name: str,
        args: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> WorkspaceActionResult:
        if tool_name not in {"write_file", "replace_in_file", "apply_patch"}:
            raise ValueError(f"Unsupported workflow file action {tool_name!r}")
        return self.run_tool(
            request,
            tool_name,
            {**args, **({"dry_run": True} if dry_run else {})},
            dry_run=dry_run,
        )

    def run_tool(
        self,
        request: HubRequest,
        tool_name: str,
        args: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> WorkspaceActionResult:
        started = time.time()
        result = AgentToolbox(self.config, request).run(tool_name, args)
        finished = time.time()
        return WorkspaceActionResult(
            action=tool_name,
            ok=bool(result.get("ok")),
            result=result,
            dry_run=bool(dry_run or result.get("dry_run")),
            started_at=started,
            finished_at=finished,
        )


__all__ = ["SafeWorkspaceService", "WorkspaceActionResult"]
