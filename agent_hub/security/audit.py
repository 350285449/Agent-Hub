from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import HubRequest
from ..observability import record_event


def record_provider_audit(
    state_dir: str | Path,
    *,
    request: HubRequest,
    agent: Any,
    trust_level: str,
    allowed: bool,
    reason: str,
    approval_mode: str,
    interactive_approval_required: bool,
    permission: dict[str, Any] | None = None,
) -> None:
    """Persist a provider-routing audit event without logging prompt content."""

    record_event(
        state_dir,
        "security_audit",
        {
            "type": "provider_routing_audit",
            "session_id": request.session_id,
            "route": request.route,
            "preferred_agent": request.preferred_agent,
            "api_shape": request.api_shape,
            "agent": getattr(agent, "name", ""),
            "provider": getattr(agent, "provider", ""),
            "provider_type": getattr(agent, "provider_type", None),
            "model": getattr(agent, "model", ""),
            "trust_level": trust_level,
            "allowed": allowed,
            "reason": reason,
            "approval_mode": approval_mode,
            "interactive_approval_required": interactive_approval_required,
            "workspace_content_sent": _workspace_content_sent(request),
            "client": _client_metadata(request),
            "permission": _sanitize_permission(permission),
        },
    )


def _workspace_content_sent(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    if request.context or raw.get("workspace_dir") or raw.get("agent_hub_tools"):
        return True
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    context_state = metadata.get("context_state") if isinstance(metadata.get("context_state"), dict) else {}
    if context_state:
        return True
    markers = ("Current file:", "Current folder:", "File:", "Repository evidence")
    return any(
        isinstance(message, dict)
        and isinstance(message.get("content"), str)
        and any(marker in message["content"] for marker in markers)
        for message in request.messages
    )


def _client_metadata(request: HubRequest) -> dict[str, Any]:
    raw = request.raw if isinstance(request.raw, dict) else {}
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    return {
        "source": metadata.get("source") or raw.get("source"),
        "client": metadata.get("client") or metadata.get("client_name") or raw.get("client"),
        "user_agent": metadata.get("user_agent") or metadata.get("client_user_agent"),
        "cline_compatibility_mode": metadata.get("cline_compatibility_mode") or raw.get("cline_compatibility_mode"),
    }


def _sanitize_permission(permission: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(permission, dict):
        return {}
    request = permission.get("request") if isinstance(permission.get("request"), dict) else {}
    details = request.get("details") if isinstance(request.get("details"), dict) else {}
    security = details.get("security") if isinstance(details.get("security"), dict) else {}
    transparency = (
        details.get("cloud_transparency")
        if isinstance(details.get("cloud_transparency"), dict)
        else {}
    )
    sanitized_request = {
        key: request.get(key)
        for key in ("action", "category", "resource", "risk_level")
        if key in request
    }
    sanitized_details = {
        key: details.get(key)
        for key in (
            "agent",
            "provider",
            "provider_type",
            "model",
            "may_cost_money",
            "sends_workspace_content",
            "data_categories",
            "provider_data_policy",
        )
        if key in details
    }
    if security:
        sanitized_details["security"] = {
            key: security.get(key)
            for key in (
                "category",
                "risk_level",
                "reason",
                "blocked",
                "explicit_approval_required",
                "data_categories",
                "provider_data_policy",
                "findings",
                "metadata",
            )
            if key in security
        }
    if transparency:
        sanitized_details["cloud_transparency"] = {
            key: transparency.get(key)
            for key in (
                "provider",
                "model",
                "token_estimate",
                "estimated_cost_usd",
                "has_secret_findings",
                "secret_findings",
            )
            if key in transparency
        }
    if sanitized_details:
        sanitized_request["details"] = sanitized_details
    return {
        key: permission.get(key)
        for key in ("allowed", "requires_approval", "denied", "reason", "mode")
        if key in permission
    } | ({"request": sanitized_request} if sanitized_request else {})
