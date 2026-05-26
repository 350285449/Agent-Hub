from __future__ import annotations

from dataclasses import dataclass

from ..config import HubConfig
from ..models import HubRequest
from ..permissions import PermissionManager, tool_permission_request
from .types import Tool, ToolCall, ToolResult


@dataclass(slots=True)
class ToolPermissionLayer:
    config: HubConfig
    request: HubRequest | None = None

    def check(self, tool: Tool, call: ToolCall) -> ToolResult | None:
        if tool.name == "shell_execute":
            denied = self._check_shell_policy(call)
            if denied is not None:
                return denied
        request = tool_permission_request(_legacy_tool_name(tool.name), call.arguments)
        decision = PermissionManager(
            getattr(self.config, "approval_mode", "ask"),
            approval_granted=_approval_granted(self.request),
        ).check(request)
        if decision.allowed:
            return None
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=False,
            error=decision.reason or "Tool execution denied by permission policy.",
            metadata={"permission": decision.to_dict()},
        )

    def _check_shell_policy(self, call: ToolCall) -> ToolResult | None:
        command = str(call.arguments.get("command") or "")
        if not getattr(self.config, "allow_shell_tools", False):
            return _denied_shell_result(call, "Shell tools are disabled by allow_shell_tools=false.", command)
        policy = str(getattr(self.config, "shell_command_policy", "deny") or "deny").lower()
        if policy in {"deny", "disabled", "off", "false", "0"}:
            return _denied_shell_result(call, "Shell command execution is denied by shell_command_policy.", command)
        if policy in {"ask", "confirm", "prompt"} and not _approval_granted(self.request):
            return _denied_shell_result(
                call,
                "Shell command execution requires approval by shell_command_policy=ask.",
                command,
                requires_approval=True,
            )
        return None


def _approval_granted(request: HubRequest | None) -> bool:
    raw = request.raw if request is not None and isinstance(request.raw, dict) else {}
    value = raw.get("tool_approval_granted") or raw.get("approval_granted")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "approved"}
    return False


def _legacy_tool_name(name: str) -> str:
    return {
        "file_read": "read_file",
        "file_write": "write_file",
        "shell_execute": "run_command",
        "search_repo": "search_files",
    }.get(name, name)


def _denied_shell_result(
    call: ToolCall,
    reason: str,
    command: str,
    *,
    requires_approval: bool = False,
) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=False,
        error=reason,
        metadata={
            "permission": {
                "allowed": False,
                "requires_approval": requires_approval,
                "denied": not requires_approval,
                "reason": reason,
                "request": {
                    "action": "run_shell_command",
                    "category": "shell_command",
                    "resource": command,
                },
            },
            "denied_command": command[:240],
        },
    )
