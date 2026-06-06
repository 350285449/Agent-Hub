from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import AgentConfig, HubConfig, _is_local_or_private_url, normalize_provider
from .enterprise import EnterprisePolicy
from .models import HubRequest
from .security import (
    RISK_ORDER,
    classify_tool_action,
    cloud_transparency_report,
)
from .token_budget import estimate_messages_tokens


APPROVAL_MODES = {"ask", "auto", "safe", "readonly", "shell-ask", "deny"}
LOCAL = "LOCAL"
TRUSTED_CLOUD = "TRUSTED_CLOUD"
UNTRUSTED_EXTERNAL = "UNTRUSTED_EXTERNAL"
TRUSTED_CLOUD_PROVIDER_TYPES = {
    "openai",
    "anthropic",
    "gemini",
    "openrouter",
    "groq",
    "ollama-cloud",
    "codex-cli",
}
KNOWN_IDE_CLIENT_MARKERS = {
    "cline",
    "continue",
    "claude-code",
    "claude_code",
    "vscode",
    "visual studio code",
    "agent hub",
    "agent-hub",
    "vscode-agent-hub-chat",
    "vscode-chat-participant",
}
SENSITIVE_CATEGORIES = {
    "config_edit",
    "external_download",
    "external_provider",
    "file_delete",
    "file_write",
    "model_download",
    "network_request",
    "package_install",
    "process_control",
    "secret_edit",
    "shell_command",
    "workspace_upload",
    "workspace_cloud",
}


PermissionCallback = Callable[[dict[str, Any]], bool]
_TRUSTED_APPROVAL_MARKER = object()


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
        enterprise_policy: EnterprisePolicy | None = None,
        enterprise_user_id: str = "",
        enterprise_workspace_id: str = "",
    ) -> None:
        self.mode = normalize_approval_mode(mode)
        self.approval_granted = approval_granted
        self.callback = callback
        self.enterprise_policy = enterprise_policy
        self.enterprise_user_id = enterprise_user_id
        self.enterprise_workspace_id = enterprise_workspace_id

    def check(self, request: PermissionRequest) -> PermissionDecision:
        security = request.details.get("security") if isinstance(request.details, dict) else None
        blocked = bool(isinstance(security, dict) and security.get("blocked"))
        explicit_approval_required = bool(
            isinstance(security, dict) and security.get("explicit_approval_required")
        )
        if blocked:
            return PermissionDecision(
                False,
                denied=True,
                reason=str(security.get("reason") or "Action blocked by Agent Hub security policy."),
                mode=self.mode,
                request=request,
            )

        if request.category not in SENSITIVE_CATEGORIES:
            return PermissionDecision(True, mode=self.mode, request=request)

        enterprise_decision = self.check_enterprise(request)
        if enterprise_decision is not None:
            return enterprise_decision

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

        if self.mode == "safe" and _risk_at_least(request.risk_level, "critical"):
            return PermissionDecision(
                False,
                denied=True,
                reason="Action blocked by safe mode because risk is critical.",
                mode=self.mode,
                request=request,
            )

        if self.approval_granted:
            return PermissionDecision(True, mode=self.mode, request=request)

        if self.mode == "auto":
            if explicit_approval_required:
                return PermissionDecision(
                    False,
                    requires_approval=True,
                    reason="Explicit approval is required for this high-risk action.",
                    mode=self.mode,
                    request=request,
                )
            return PermissionDecision(True, mode=self.mode, request=request)

        if self.mode == "safe":
            if _risk_at_least(request.risk_level, "medium") or explicit_approval_required:
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
                    reason="Safe mode requires approval for this action.",
                    mode=self.mode,
                    request=request,
                )
            return PermissionDecision(True, mode=self.mode, request=request)

        if self.mode == "shell-ask" and request.category != "shell_command":
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

    def check_enterprise(self, request: PermissionRequest) -> PermissionDecision | None:
        if self.enterprise_policy is None or not self.enterprise_policy.enabled:
            return None
        if request.category not in SENSITIVE_CATEGORIES:
            return None
        allowed, reason = self.enterprise_policy.allows(
            user_id=self.enterprise_user_id,
            workspace_id=self.enterprise_workspace_id,
            action=request.action,
            category=request.category,
            resource=request.resource,
        )
        if allowed:
            return None
        return PermissionDecision(
            False,
            denied=True,
            reason=reason,
            mode=self.mode,
            request=request,
        )


def normalize_approval_mode(value: Any) -> str:
    text = str(value or "ask").strip().lower()
    if text in {"auto", "allow", "always", "trusted"}:
        return "auto"
    if text in {"safe", "safe-mode", "safe_mode"}:
        return "safe"
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
    if not trusted_approval_session(request):
        return False
    for key in ("approval_granted", "approved"):
        value = _request_option(request, key, False)
        if _truthy(value):
            return True
    return False


def provider_approval_granted_from_request(request: HubRequest) -> bool:
    if not trusted_approval_session(request):
        return False
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


def trusted_approval_session(request: HubRequest | None) -> bool:
    if request is None:
        return False
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    return metadata.get("_agent_hub_trusted_approval") is _TRUSTED_APPROVAL_MARKER


def mark_trusted_approval(request: HubRequest, *, source: str) -> HubRequest:
    """Attach an in-process approval marker that cannot be forged through JSON."""

    from dataclasses import replace

    metadata = dict(request.metadata) if isinstance(request.metadata, dict) else {}
    metadata["_agent_hub_trusted_approval"] = _TRUSTED_APPROVAL_MARKER
    metadata["_agent_hub_trusted_approval_source"] = str(source or "trusted-session")
    return replace(request, metadata=metadata)


def approval_mode_from_request(request: HubRequest, default: str) -> str:
    return normalize_approval_mode(_request_option(request, "approval_mode", default))


def client_compatibility_mode_enabled(request: HubRequest, config: HubConfig) -> bool:
    """Return True when provider approval should be non-interactive for IDE clients."""

    if not getattr(config, "cline_compatibility_mode", True):
        return False
    raw = request.raw if isinstance(request.raw, dict) else {}
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    explicit = _first_present(
        raw,
        metadata,
        "cline_compatibility_mode",
        "continue_compatibility_mode",
        "ide_compatibility_mode",
        "preserve_structured_context",
    )
    if explicit is not None:
        return _truthy(explicit)
    if request.api_shape in {"openai-chat", "openai-responses", "anthropic-messages"}:
        return True
    client_text = " ".join(
        str(value or "").lower()
        for value in (
            raw.get("source"),
            raw.get("client"),
            raw.get("client_name"),
            metadata.get("source"),
            metadata.get("client"),
            metadata.get("client_name"),
            metadata.get("user_agent"),
            metadata.get("client_user_agent"),
        )
    )
    return any(marker in client_text for marker in KNOWN_IDE_CLIENT_MARKERS)


def tool_permission_request(tool_name: str, args: dict[str, Any]) -> PermissionRequest:
    security = classify_tool_action(tool_name, args).to_dict()
    if tool_name == "run_command":
        command = str(args.get("command") or "")
        category = str(security.get("category") or "shell_command")
        risk = str(security.get("risk_level") or "medium")
        return PermissionRequest(
            action="run_shell_command",
            category=category,
            description=f"Run shell command: {command[:160]}",
            resource=command,
            risk_level=risk,
            details={
                "command": command,
                "cwd": args.get("cwd") or ".",
                "timeout_seconds": args.get("timeout_seconds"),
                "security": security,
            },
        )
    if tool_name in {"write_file", "replace_in_file", "apply_patch"}:
        category = str(security.get("category") or "file_write")
        details = {"tool": tool_name, "args": args}
        resource = str(args.get("path") or "")
        if tool_name == "apply_patch":
            resource = "multiple files"
            details = {"tool": tool_name, "summary": args.get("summary"), "commands": args.get("commands")}
        details["security"] = security
        return PermissionRequest(
            action=tool_name,
            category=category,
            description=f"Modify workspace files with {tool_name}.",
            resource=resource,
            risk_level=str(security.get("risk_level") or "medium"),
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
    token_estimate = estimate_messages_tokens(request.messages)
    transparency = cloud_transparency_report(
        provider=agent.provider,
        model=agent.model,
        messages=request.messages,
        context=request.context,
        token_estimate=token_estimate,
    )
    prepared_security = _security_context_from_request(request)
    secret_findings = [
        *list(transparency.get("secret_findings") or []),
        *list(prepared_security.get("secret_findings") or []),
    ]
    sensitive_files = list(prepared_security.get("sensitive_files") or [])
    injection_findings = list(prepared_security.get("injection_findings") or [])
    if prepared_security.get("has_secret_findings"):
        transparency["secret_findings"] = secret_findings[:20]
        transparency["has_secret_findings"] = True
    category = "workspace_cloud"
    sends_workspace_content = request_text_has_workspace_context(request)
    if not sends_workspace_content:
        category = "external_provider"
    risk_level = "high" if agent.resolved_api_key or not agent.free else "medium"
    explicit_approval_required = bool(
        transparency["has_secret_findings"]
        or prepared_security.get("has_secret_findings")
        or prepared_security.get("has_unredacted_secrets")
        or sensitive_files
    )
    security = {
        "category": category,
        "risk_level": "critical" if explicit_approval_required else risk_level,
        "reason": (
            "Request content appears to include secrets."
            if explicit_approval_required
            else "External provider call can transmit prompt or workspace context."
        ),
        "blocked": False,
        "explicit_approval_required": explicit_approval_required,
        "findings": secret_findings[:20],
        "metadata": {
            "token_estimate": token_estimate,
            "sensitive_files": sensitive_files[:20],
            "prompt_injection_findings": injection_findings[:20],
            "repo_files_untrusted": bool(prepared_security.get("repo_files_untrusted")),
        },
    }
    return PermissionRequest(
        action="call_external_provider",
        category=category,
        description=(
            f"Send request content to external provider {agent.provider} "
            f"using model {agent.model}."
        ),
        resource=f"{agent.provider}/{agent.model}",
        risk_level=str(security["risk_level"]),
        details={
            "agent": agent.name,
            "provider": agent.provider,
            "provider_type": agent.provider_type,
            "model": agent.model,
            "may_cost_money": bool(agent.resolved_api_key or not agent.free),
            "sends_workspace_content": sends_workspace_content,
            "preview": text_preview[:1000],
            "cloud_transparency": transparency,
            "prepared_security_context": prepared_security,
            "security": security,
        },
    )


def provider_requires_permission(agent: AgentConfig) -> bool:
    if provider_trust_level(agent) == LOCAL:
        return False
    return True


def provider_trust_level(agent: AgentConfig) -> str:
    provider = normalize_provider(agent.provider)
    provider_type = str(agent.provider_type or "").lower()
    if provider in {"echo", "local-research"}:
        return LOCAL
    if provider_type in TRUSTED_CLOUD_PROVIDER_TYPES:
        return TRUSTED_CLOUD
    if (provider == "ollama" or provider_type == "ollama") and (
        not agent.base_url or _is_local_or_private_url(agent.base_url)
    ):
        return LOCAL
    if provider == "openai-compatible" and _is_local_or_private_url(agent.base_url):
        return LOCAL
    if provider in TRUSTED_CLOUD_PROVIDER_TYPES:
        return TRUSTED_CLOUD
    return UNTRUSTED_EXTERNAL


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


def _security_context_from_request(request: HubRequest) -> dict[str, Any]:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub_options = raw.get("agent_hub")
    if isinstance(hub_options, dict):
        security = hub_options.get("security_context")
        if isinstance(security, dict):
            return security
    return {}


def _first_present(raw: dict[str, Any], metadata: dict[str, Any], *keys: str) -> Any:
    hub_options = raw.get("agent_hub")
    for source in (raw, metadata, hub_options if isinstance(hub_options, dict) else {}):
        for key in keys:
            if key in source:
                return source[key]
    return None


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


def _risk_at_least(value: str, threshold: str) -> bool:
    return RISK_ORDER.get(str(value or "low").lower(), 0) >= RISK_ORDER.get(threshold, 0)
