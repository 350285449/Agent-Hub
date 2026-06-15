from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import AgentConfig, HubConfig
from ..models import HubRequest
from ..permissions import (
    PermissionDecision,
    PermissionManager,
    PermissionRequest,
    approval_mode_from_request,
    tool_permission_request,
)
from .provider_permissions import ProviderPermissionPolicy


@dataclass(slots=True)
class PolicyService:
    """Central facade for provider, tool, and future plugin policy decisions."""

    config: HubConfig

    def check_provider(self, agent: AgentConfig, request: HubRequest) -> PermissionDecision | None:
        return ProviderPermissionPolicy(self.config).check(agent, request)

    def check_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        request: HubRequest | None = None,
        *,
        approval_granted: bool = False,
        callback: Any = None,
    ) -> PermissionDecision:
        permission_request = tool_permission_request(tool_name, args)
        mode = approval_mode_from_request(request, self.config.approval_mode) if request else self.config.approval_mode
        return PermissionManager(
            mode,
            approval_granted=approval_granted,
            callback=callback,
        ).check(permission_request)

    def check_action(
        self,
        permission_request: PermissionRequest,
        request: HubRequest | None = None,
        *,
        approval_granted: bool = False,
        callback: Any = None,
    ) -> PermissionDecision:
        mode = approval_mode_from_request(request, self.config.approval_mode) if request else self.config.approval_mode
        return PermissionManager(
            mode,
            approval_granted=approval_granted,
            callback=callback,
        ).check(permission_request)

    def summary(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.policy_service",
            "approval_mode": self.config.approval_mode,
            "provider_privacy_mode_enabled": bool(getattr(self.config, "provider_privacy_mode_enabled", True)),
            "provider_data_policy": _provider_data_policy_summary(getattr(self.config, "provider_data_policy", {})),
            "provider_data_categories": [
                "billable_provider",
                "prompt",
                "prompt_injection",
                "repository_files",
                "secrets",
                "sensitive_paths",
                "untrusted_context",
                "workspace_context",
            ],
            "secret_scanning_enabled": bool(getattr(self.config, "secret_scanning_enabled", True)),
            "prompt_injection_defense_enabled": bool(getattr(self.config, "prompt_injection_defense_enabled", True)),
            "plugin_execution_enabled": bool(getattr(self.config, "plugin_execution_enabled", False)),
            "mcp_execution_enabled": bool(getattr(self.config, "mcp_execution_enabled", False)),
            "workspace_trusted": bool(getattr(self.config, "workspace_trusted", True)),
            "boundaries": ["provider", "tool", "plugin", "mcp", "workspace"],
        }


def _provider_data_policy_summary(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    summary: dict[str, list[str]] = {}
    for key in ("allowed_categories", "blocked_categories", "require_approval_categories"):
        items = value.get(key)
        if isinstance(items, str):
            summary[key] = [items]
        elif isinstance(items, list):
            summary[key] = [str(item) for item in items if str(item).strip()]
    return summary


__all__ = ["PolicyService"]
