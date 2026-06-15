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
from ..tracing import trace_event_fields
from ..permissions import (
    LOCAL,
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

        if getattr(self.config, "provider_privacy_mode_enabled", True):
            _apply_provider_privacy_policy(
                config=self.config,
                agent=agent,
                request=request,
                permission_request=permission_request,
                trust_level=trust_level,
            )

        explicit_approval = provider_approval_granted_from_request(request)
        compatibility = client_compatibility_mode_enabled(request, self.config)
        explicit_security_approval = _explicit_security_approval_required(permission_request)
        if (
            trust_level == TRUSTED_CLOUD
            and not explicit_approval
            and not explicit_security_approval
            and approval_mode == "auto"
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
                    "because approval_mode=auto is explicitly configured."
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
                "Provider requires approval from a trusted session. Trusted cloud "
                "providers may also be enabled explicitly with approval_mode=auto; "
                "unknown external endpoints always require trusted approval."
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
                **trace_event_fields(request),
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
                    and approval_mode == "auto"
                ),
                "category": permission_request.category,
                "risk_level": permission_request.risk_level,
                "resource": permission_request.resource,
                "data_categories": list(permission_request.details.get("data_categories") or [])
                if isinstance(permission_request.details, dict)
                else [],
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


def _apply_provider_privacy_policy(
    *,
    config: HubConfig,
    agent: AgentConfig,
    request: HubRequest,
    permission_request: PermissionRequest,
    trust_level: str,
) -> None:
    security = (
        permission_request.details.get("security")
        if isinstance(permission_request.details, dict)
        else None
    )
    if not isinstance(security, dict):
        return
    categories = _provider_data_categories(permission_request)
    data_policy = _merged_provider_data_policy(config, agent, request)
    policy_decision = _provider_data_policy_decision(categories, data_policy)
    security["data_categories"] = categories
    security["provider_data_policy"] = data_policy
    if isinstance(permission_request.details, dict):
        permission_request.details["data_categories"] = categories
        permission_request.details["provider_data_policy"] = data_policy
    sends_workspace = bool(
        permission_request.details.get("sends_workspace_content")
        if isinstance(permission_request.details, dict)
        else False
    )
    prepared = (
        permission_request.details.get("prepared_security_context")
        if isinstance(permission_request.details, dict)
        else None
    )
    prepared = prepared if isinstance(prepared, dict) else {}
    has_secrets = bool(
        prepared.get("has_unredacted_secrets")
        or (not prepared.get("redacted") and security.get("findings"))
    )
    if trust_level == LOCAL:
        return
    if policy_decision["action"] == "block":
        _block_security(security, str(policy_decision["reason"]))
        return
    if policy_decision["action"] == "approval":
        _require_security_approval(security, str(policy_decision["reason"]))
    if bool(getattr(agent, "local_only", False)):
        _block_security(
            security,
            "Provider privacy mode blocks this provider because it is marked local_only but is not local/private.",
        )
        return
    if sends_workspace and bool(getattr(agent, "never_send_workspace_files", False)):
        _block_security(
            security,
            "Provider privacy mode blocks workspace files for this provider.",
        )
        return
    if sends_workspace and not bool(getattr(agent, "safe_for_code", True)):
        _block_security(
            security,
            "Provider privacy mode blocks workspace code for providers not marked safe_for_code.",
        )
        return
    if has_secrets and not bool(getattr(agent, "safe_for_secrets", False)):
        _block_security(
            security,
            "Provider privacy mode blocks secrets or sensitive files from being sent to this provider.",
        )


def _block_security(security: dict[str, Any], reason: str) -> None:
    security["blocked"] = True
    security["explicit_approval_required"] = True
    security["risk_level"] = "critical"
    security["reason"] = reason


def _require_security_approval(security: dict[str, Any], reason: str) -> None:
    security["explicit_approval_required"] = True
    security["risk_level"] = "critical"
    security["reason"] = reason


def _provider_data_categories(permission_request: PermissionRequest) -> list[str]:
    details = permission_request.details if isinstance(permission_request.details, dict) else {}
    security = details.get("security") if isinstance(details.get("security"), dict) else {}
    prepared = (
        details.get("prepared_security_context")
        if isinstance(details.get("prepared_security_context"), dict)
        else {}
    )
    transparency = (
        details.get("cloud_transparency")
        if isinstance(details.get("cloud_transparency"), dict)
        else {}
    )
    categories: set[str] = {"prompt"}
    if bool(details.get("sends_workspace_content")):
        categories.add("workspace_context")
        categories.add("repository_files")
    sensitive_files = security.get("metadata", {}).get("sensitive_files") if isinstance(security.get("metadata"), dict) else []
    if sensitive_files or prepared.get("sensitive_files"):
        categories.add("sensitive_paths")
    if (
        prepared.get("has_secret_findings")
        or prepared.get("has_unredacted_secrets")
        or transparency.get("has_secret_findings")
        or security.get("findings")
    ):
        categories.add("secrets")
    metadata = security.get("metadata") if isinstance(security.get("metadata"), dict) else {}
    if metadata.get("prompt_injection_findings") or prepared.get("injection_findings"):
        categories.add("prompt_injection")
    if metadata.get("repo_files_untrusted") or prepared.get("repo_files_untrusted"):
        categories.add("untrusted_context")
    if bool(details.get("may_cost_money")):
        categories.add("billable_provider")
    return sorted(categories)


def _merged_provider_data_policy(
    config: HubConfig,
    agent: AgentConfig,
    request: HubRequest,
) -> dict[str, list[str]]:
    raw: list[Any] = [
        getattr(config, "provider_data_policy", {}),
        getattr(agent, "provider_data_policy", {}),
    ]
    hub = request.raw.get("agent_hub") if isinstance(request.raw, dict) else {}
    if isinstance(hub, dict):
        raw.append(hub.get("provider_data_policy"))
        raw.append(hub.get("data_policy"))
    result = {
        "allowed_categories": [],
        "blocked_categories": [],
        "require_approval_categories": [],
    }
    for item in raw:
        if not isinstance(item, dict):
            continue
        result["allowed_categories"] = _merge_category_list(
            result["allowed_categories"],
            item.get("allowed_categories", item.get("allow_categories")),
        )
        result["blocked_categories"] = _merge_category_list(
            result["blocked_categories"],
            item.get("blocked_categories", item.get("block_categories")),
        )
        result["require_approval_categories"] = _merge_category_list(
            result["require_approval_categories"],
            item.get("require_approval_categories", item.get("approval_categories")),
        )
    return result


def _provider_data_policy_decision(categories: list[str], policy: dict[str, list[str]]) -> dict[str, str]:
    category_set = set(categories)
    blocked = sorted(category_set & set(policy.get("blocked_categories") or []))
    if blocked:
        return {
            "action": "block",
            "reason": "Provider data policy blocks outbound categories: " + ", ".join(blocked) + ".",
        }
    allowed = set(policy.get("allowed_categories") or [])
    if allowed:
        disallowed = sorted(category_set - allowed)
        if disallowed:
            return {
                "action": "block",
                "reason": "Provider data policy allows only approved categories; blocked: " + ", ".join(disallowed) + ".",
            }
    approval = sorted(category_set & set(policy.get("require_approval_categories") or []))
    if approval:
        return {
            "action": "approval",
            "reason": "Provider data policy requires explicit approval for categories: " + ", ".join(approval) + ".",
        }
    return {"action": "allow", "reason": ""}


def _merge_category_list(existing: list[str], value: Any) -> list[str]:
    merged = list(existing)
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []
    for item in candidates:
        text = str(item).strip().lower().replace("-", "_")
        if text and text not in merged:
            merged.append(text)
    return merged


__all__ = ["ProviderPermissionPolicy"]
