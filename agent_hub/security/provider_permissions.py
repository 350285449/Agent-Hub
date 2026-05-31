from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import AgentConfig, HubConfig
from ..enterprise import (
    EnterprisePolicy,
    enterprise_subject_from_request,
    enterprise_workspace_from_request,
)
from ..models import HubRequest
from ..observability import record_event
from ..permissions import (
    TRUSTED_CLOUD,
    UNTRUSTED_EXTERNAL,
    PermissionDecision,
    PermissionManager,
    PermissionRequest,
    approval_mode_from_request,
    client_compatibility_mode_enabled,
    provider_approval_granted_from_request,
    provider_permission_request,
    provider_trust_level,
)
from .audit import record_provider_audit


@dataclass(slots=True)
class ProviderPermissionPolicy:
    """Security boundary for deciding whether a provider call is allowed."""

    config: HubConfig

    def check(self, agent: AgentConfig, request: HubRequest) -> PermissionDecision | None:
        permission_request = provider_permission_request(agent, request)
        trust_level = self.trust_level(agent)
        approval_mode = approval_mode_from_request(request, self.config.approval_mode)
        if permission_request is None:
            record_provider_audit(
                self.config.state_dir,
                request=request,
                agent=agent,
                trust_level=trust_level,
                allowed=True,
                reason="Provider is local or does not require interactive approval.",
                approval_mode=approval_mode,
                interactive_approval_required=False,
            )
            return None

        explicit_approval = provider_approval_granted_from_request(request)
        compatibility = client_compatibility_mode_enabled(request, self.config)
        explicit_security_approval = _explicit_security_approval_required(permission_request)
        if (
            trust_level == TRUSTED_CLOUD
            and not explicit_approval
            and not explicit_security_approval
            and (approval_mode == "auto" or compatibility)
        ):
            enterprise_decision = self.check_enterprise(
                permission_request,
                request,
                approval_mode,
            )
            if enterprise_decision is not None:
                decision = enterprise_decision
            else:
                reason = (
                    "Allowed trusted cloud provider without interactive approval "
                    "because approval_mode=auto or IDE compatibility mode is enabled."
                )
                decision = PermissionDecision(
                    True,
                    requires_approval=False,
                    denied=False,
                    reason=reason,
                    mode=approval_mode,
                    request=permission_request,
                )
        elif trust_level == UNTRUSTED_EXTERNAL and not explicit_approval:
            reason = (
                "Provider requires approval. Set approval_mode=auto or enable "
                "cline_compatibility_mode for trusted providers; unknown external "
                "endpoints require explicit approval."
            )
            decision = PermissionDecision(
                False,
                requires_approval=True,
                denied=False,
                reason=reason,
                mode=approval_mode,
                request=permission_request,
            )
        else:
            decision = self._manager(
                request,
                approval_mode,
                explicit_approval=explicit_approval,
            ).check(permission_request)

        self._record_permission_event(
            agent=agent,
            request=request,
            permission_request=permission_request,
            decision=decision,
            trust_level=trust_level,
            approval_mode=approval_mode,
            compatibility=compatibility,
        )
        record_provider_audit(
            self.config.state_dir,
            request=request,
            agent=agent,
            trust_level=trust_level,
            allowed=decision.allowed,
            reason=decision.reason,
            approval_mode=approval_mode,
            interactive_approval_required=not decision.allowed and decision.requires_approval,
            permission=decision.to_dict(),
        )
        return decision

    def check_enterprise(
        self,
        permission_request: PermissionRequest,
        request: HubRequest,
        approval_mode: str,
    ) -> PermissionDecision | None:
        return self._manager(request, approval_mode).check_enterprise(permission_request)

    def trust_level(self, agent: AgentConfig) -> str:
        return provider_trust_level(agent)

    def _manager(
        self,
        request: HubRequest,
        approval_mode: str,
        *,
        explicit_approval: bool = False,
    ) -> PermissionManager:
        return PermissionManager(
            approval_mode,
            approval_granted=explicit_approval,
            enterprise_policy=EnterprisePolicy.from_config(self.config),
            enterprise_user_id=enterprise_subject_from_request(request),
            enterprise_workspace_id=enterprise_workspace_from_request(self.config, request),
        )

    def _record_permission_event(
        self,
        *,
        agent: AgentConfig,
        request: HubRequest,
        permission_request: PermissionRequest,
        decision: PermissionDecision,
        trust_level: str,
        approval_mode: str,
        compatibility: bool,
    ) -> None:
        record_event(
            self.config.state_dir,
            "permissions",
            {
                "type": "provider_permission",
                "session_id": request.session_id,
                "agent": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "allowed": decision.allowed,
                "requires_approval": decision.requires_approval,
                "denied": decision.denied,
                "reason": decision.reason,
                "mode": decision.mode,
                "trust_level": trust_level,
                "compatibility_bypass": bool(
                    decision.allowed
                    and trust_level == TRUSTED_CLOUD
                    and (approval_mode == "auto" or compatibility)
                ),
                "category": permission_request.category,
                "risk_level": permission_request.risk_level,
                "resource": permission_request.resource,
            },
        )


def _explicit_security_approval_required(permission_request: PermissionRequest) -> bool:
    security = (
        permission_request.details.get("security")
        if isinstance(permission_request.details, dict)
        else None
    )
    return bool(
        isinstance(security, dict)
        and (security.get("blocked") or security.get("explicit_approval_required"))
    )


__all__ = ["ProviderPermissionPolicy"]
