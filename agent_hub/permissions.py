from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import AgentConfig, _is_local_or_private_url, normalize_provider
from .models import HubRequest


APPROVAL_MODES = {"ask", "auto", "readonly", "shell-ask", "deny"}
SENSITIVE_CATEGORIES = {
    "config_edit",
    "external_provider",
    "file_delete",
    "file_write",
    "model_download",
    "network_request",
    "package_install",
    "process_control",
    "shell_command",
    "workspace_cloud",
}


PermissionCallback = Callable[[dict[str, Any]], bool]


@dataclass(slots=True)
class PermissionRequest:
    action: str
    category: str
    description: str
    resource: str = ""
    risk_level: str = "medium"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "action": self.action,
            "category": self.category,
            "description": self.description,
            "resource": self.resource,
            "risk_level": self.risk_level,
            "details": self.details,
        }
        for key, value in self.details.items():
            data.setdefault(str(key), value)
        return data


@dataclass(slots=True)
class PermissionDecision:
    allowed: bool
    requires_approval: bool = False
    denied: bool = False
    reason: str = ""
    mode: str = "ask"
    request: PermissionRequest | None = None

    @property
    def sensitive(self) -> bool:
        return bool(self.request and self.request.category in SENSITIVE_CATEGORIES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "denied": self.denied,
            "reason": self.reason,
            "mode": self.mode,
            "request": self.request.to_dict() if self.request else None,
        }


class PermissionManager:
    """Central decision point for privileged Agent Hub actions."""

    def __init__(
        self,
        mode: str = "ask",
        *,
        approval_granted: bool = False,
        callback: PermissionCallback | None = None,
    ) -> None:
        self.mode = normalize_approval_mode(mode)
        self.approval_granted = approval_granted
        self.callback = callback

    def check(self, request: PermissionRequest) -> PermissionDecision:
        if request.category not in SENSITIVE_CATEGORIES:
            return PermissionDecision(True, mode=self.mode, request=request)

        if self.mode == "auto":
            return PermissionDecision(True, mode=self.mode, request=request)

        if self.mode == "readonly":
            return PermissionDecision(
                False,
                denied=True,
                reason="Permission denied because approval_mode is readonly.",
                mode=self.mode,
                request=request,
            )

        if self.mode == "deny":
            return PermissionDecision(
                False,
                denied=True,
                reason="Permission denied by approval_mode=deny.",
                mode=self.mode,
                request=request,
            )

        if self.mode == "shell-ask" and request.category != "shell_command":
            return PermissionDecision(True, mode=self.mode, request=request)

        if self.approval_granted:
            return PermissionDecision(True, mode=self.mode, request=request)

        if self.callback is not None:
            try:
                allowed = bool(self.callback(request.to_dict()))
            except Exception as exc:
                return PermissionDecision(
                    False,
                    denied=True,
                    reason=f"Permission prompt failed: {exc}",
                    mode=self.mode,
                    request=request,
                )
            return PermissionDecision(
                allowed,
                denied=not allowed,
                reason="" if allowed else "User denied permission.",
                mode=self.mode,
                request=request,
            )

        return PermissionDecision(
            False,
            requires_approval=True,
            reason="User approval is required before this action can continue.",
            mode=self.mode,
            request=request,
        )


def normalize_approval_mode(value: Any) -> str:
    text = str(value or "ask").strip().lower()
    if text in {"auto", "allow", "always", "trusted"}:
        return "auto"
    if text in {"ask", "confirm", "prompt"}:
        return "ask"
    if text in {"readonly", "read-only", "read_only"}:
        return "readonly"
    if text in {"shell-ask", "shell_ask", "shell"}:
        return "shell-ask"
    if text in {"deny", "never", "off", "disabled"}:
        return "deny"
    return "ask"


def approval_granted_from_request(request: HubRequest) -> bool:
    for key in ("approval_granted", "approved"):
        value = _request_option(request, key, False)
        if _truthy(value):
            return True
    return False


def provider_approval_granted_from_request(request: HubRequest) -> bool:
    for key in (
        "provider_approval_granted",
        "cloud_approval_granted",
        "external_provider_approved",
        "approval_granted",
        "approved",
    ):
        value = _request_option(request, key, False)
        if _truthy(value):
            return True
    return False


def approval_mode_from_request(request: HubRequest, default: str) -> str:
    return normalize_approval_mode(_request_option(request, "approval_mode", default))


def tool_permission_request(tool_name: str, args: dict[str, Any]) -> PermissionRequest:
    if tool_name == "run_command":
        command = str(args.get("command") or "")
        category = "package_install" if _looks_like_package_install(command) else "shell_command"
        risk = "high" if _looks_like_dangerous_command(command) or category == "package_install" else "medium"
        return PermissionRequest(
            action="run_shell_command",
            category=category,
            description=f"Run shell command: {command[:160]}",
            resource=command,
            risk_level=risk,
            details={"command": command, "cwd": args.get("cwd") or ".", "timeout_seconds": args.get("timeout_seconds")},
        )
    if tool_name in {"write_file", "replace_in_file", "apply_patch"}:
        category = "file_write"
        details = {"tool": tool_name, "args": args}
        resource = str(args.get("path") or "")
        if tool_name == "apply_patch":
            resource = "multiple files"
            details = {"tool": tool_name, "summary": args.get("summary"), "commands": args.get("commands")}
        return PermissionRequest(
            action=tool_name,
            category=category,
            description=f"Modify workspace files with {tool_name}.",
            resource=resource,
            risk_level="medium",
            details=details,
        )
    return PermissionRequest(
        action=tool_name,
        category="read",
        description=f"Run read-only tool {tool_name}.",
        details={"tool": tool_name, "args": args},
        risk_level="low",
    )


def provider_permission_request(agent: AgentConfig, request: HubRequest) -> PermissionRequest | None:
    if not provider_requires_permission(agent):
        return None
    text_preview = "\n".join(
        str(message.get("content") or "")[:500]
        for message in request.messages[:3]
        if isinstance(message, dict)
    )
    category = "workspace_cloud"
    if not request_text_has_workspace_context(request):
        category = "external_provider"
    return PermissionRequest(
        action="call_external_provider",
        category=category,
        description=(
            f"Send request content to external provider {agent.provider} "
            f"using model {agent.model}."
        ),
        resource=f"{agent.provider}/{agent.model}",
        risk_level="high" if agent.resolved_api_key or not agent.free else "medium",
        details={
            "agent": agent.name,
            "provider": agent.provider,
            "provider_type": agent.provider_type,
            "model": agent.model,
            "may_cost_money": bool(agent.resolved_api_key or not agent.free),
            "sends_workspace_content": bool(text_preview),
            "preview": text_preview[:1000],
        },
    )


def provider_requires_permission(agent: AgentConfig) -> bool:
    provider = normalize_provider(agent.provider)
    provider_type = str(agent.provider_type or "").lower()
    if provider in {"echo", "local-research"}:
        return False
    if "cloud" in provider_type:
        return True
    if agent.api_key_env or agent.resolved_api_key:
        return True
    if provider in {"openai", "anthropic", "gemini"}:
        return True
    if provider == "openai-compatible":
        return not _is_local_or_private_url(agent.base_url)
    return provider not in {"echo", "local-research"}


def request_text_has_workspace_context(request: HubRequest) -> bool:
    if request.context:
        return True
    raw = request.raw if isinstance(request.raw, dict) else {}
    if raw.get("workspace_dir") or raw.get("agent_hub_tools"):
        return True
    return any(
        isinstance(message, dict)
        and isinstance(message.get("content"), str)
        and any(marker in message["content"] for marker in ("Current file:", "Current folder:", "File:"))
        for message in request.messages
    )


def _request_option(request: HubRequest, key: str, default: Any) -> Any:
    raw = request.raw or {}
    hub_options = raw.get("agent_hub")
    if isinstance(hub_options, dict) and key in hub_options:
        return hub_options[key]
    return raw.get(key, default)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "approved"}
    return bool(value)


def _looks_like_package_install(command: str) -> bool:
    normalized = f" {command.lower()} "
    return any(
        token in normalized
        for token in (
            " npm install ",
            " npm i ",
            " yarn add ",
            " pnpm add ",
            " pip install ",
            " pip3 install ",
            " poetry add ",
            " uv add ",
            " apt-get install ",
            " brew install ",
        )
    )


def _looks_like_dangerous_command(command: str) -> bool:
    normalized = f" {command.lower()} "
    return any(
        token in normalized
        for token in (
            " rm ",
            " del ",
            " rmdir ",
            " git reset ",
            " git clean ",
            " git checkout . ",
            " chmod ",
            " chown ",
            " kill ",
            " pkill ",
            " shutdown ",
            " reboot ",
            " > ",
            " >> ",
        )
    )
