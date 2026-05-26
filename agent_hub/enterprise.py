from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .observability import recent_events, record_event
from .security.secrets import redact_secrets


@dataclass(slots=True)
class UserIdentity:
    id: str
    display_name: str = ""
    email: str = ""
    roles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "email": self.email,
            "roles": list(self.roles),
        }


@dataclass(slots=True)
class WorkspaceRef:
    id: str
    path: str
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "path": self.path}


@dataclass(slots=True)
class RoleDefinition:
    name: str
    permissions: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "permissions": list(self.permissions),
        }


@dataclass(slots=True)
class PermissionGrant:
    subject_id: str
    workspace_id: str
    permission: str
    granted_by: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "workspace_id": self.workspace_id,
            "permission": self.permission,
            "granted_by": self.granted_by,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class EnterpriseAuditEvent:
    actor_id: str
    action: str
    workspace_id: str = ""
    target: str = ""
    allowed: bool = True
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "enterprise_permission_decision",
            "actor_id": self.actor_id,
            "user": self.actor_id,
            "action": self.action,
            "workspace_id": self.workspace_id,
            "workspace": self.workspace_id,
            "target": self.target,
            "resource": self.target,
            "allowed": self.allowed,
            "deny": not self.allowed,
            "reason": self.reason,
            "metadata": dict(self.metadata),
            "timestamp": self.created_at,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class EnterprisePolicy:
    enabled: bool = False
    users: dict[str, UserIdentity] = field(default_factory=dict)
    workspaces: dict[str, WorkspaceRef] = field(default_factory=dict)
    roles: dict[str, RoleDefinition] = field(default_factory=dict)
    grants: list[PermissionGrant] = field(default_factory=list)
    default_workspace_id: str = "default"
    state_dir: Path | None = None

    @classmethod
    def from_config(cls, config: Any) -> "EnterprisePolicy":
        enabled = bool(getattr(config, "enterprise_mode_enabled", False))
        users = {
            user.id: user
            for user in (_user_from_dict(item) for item in getattr(config, "enterprise_users", []) or [])
            if user.id
        }
        workspaces = {
            workspace.id: workspace
            for workspace in (
                _workspace_from_dict(item)
                for item in getattr(config, "enterprise_workspaces", []) or []
            )
            if workspace.id
        }
        roles = {
            role.name: role
            for role in (_role_from_dict(item) for item in getattr(config, "enterprise_roles", []) or [])
            if role.name
        }
        grants = [
            grant
            for grant in (
                _grant_from_dict(item)
                for item in getattr(config, "enterprise_permission_grants", []) or []
            )
            if grant.subject_id and grant.permission
        ]
        return cls(
            enabled=enabled,
            users=users,
            workspaces=workspaces,
            roles=roles,
            grants=grants,
            default_workspace_id=str(
                getattr(config, "enterprise_default_workspace_id", "default") or "default"
            ),
            state_dir=Path(getattr(config, "state_dir", ".agent-hub/state")),
        )

    def allows(
        self,
        *,
        user_id: str,
        workspace_id: str,
        action: str,
        category: str,
        resource: str = "",
    ) -> tuple[bool, str]:
        if not self.enabled:
            return True, ""
        user_id = str(user_id or "").strip()
        workspace_id = str(workspace_id or self.default_workspace_id or "default").strip()
        if not user_id:
            return self._decision(
                user_id=user_id,
                workspace_id=workspace_id,
                action=action,
                category=category,
                resource=resource,
                allowed=False,
                reason="Enterprise mode requires a user_id for sensitive actions.",
            )
        user = self.users.get(user_id)
        if user is None:
            return self._decision(
                user_id=user_id,
                workspace_id=workspace_id,
                action=action,
                category=category,
                resource=resource,
                allowed=False,
                reason=f"Enterprise user {user_id!r} is not configured.",
            )
        permissions = set()
        for role_name in user.roles:
            role = self.roles.get(role_name)
            if role:
                permissions.update(role.permissions)
        for grant in self.grants:
            if grant.workspace_id not in {"*", workspace_id}:
                continue
            if grant.subject_id == user_id or grant.subject_id in {f"user:{user_id}", *[f"role:{role}" for role in user.roles]}:
                permissions.add(grant.permission)
        needed = _permission_names(action=action, category=category)
        if _permission_allowed(permissions, needed):
            return self._decision(
                user_id=user_id,
                workspace_id=workspace_id,
                action=action,
                category=category,
                resource=resource,
                allowed=True,
                reason="enterprise_policy_allowed",
            )
        return self._decision(
            user_id=user_id,
            workspace_id=workspace_id,
            action=action,
            category=category,
            resource=resource,
            allowed=False,
            reason=(
                "Enterprise policy denied this action; missing permission "
                f"for {category or action}."
            ),
        )

    def _decision(
        self,
        *,
        user_id: str,
        workspace_id: str,
        action: str,
        category: str,
        resource: str,
        allowed: bool,
        reason: str,
    ) -> tuple[bool, str]:
        if self.state_dir is not None:
            event = EnterpriseAuditEvent(
                actor_id=user_id,
                workspace_id=workspace_id,
                action=action,
                target=resource,
                allowed=allowed,
                reason=reason,
                metadata={"category": category},
            ).to_dict()
            record_event(self.state_dir, "enterprise_audit", redact_secrets(event))
        return allowed, "" if allowed else reason


def enterprise_audit_events(state_dir: str | Path, *, limit: int = 100) -> list[dict[str, Any]]:
    return redact_secrets(recent_events(state_dir, "enterprise_audit", limit=limit))


def enterprise_subject_from_request(request: Any) -> str:
    raw = getattr(request, "raw", {}) or {}
    metadata = getattr(request, "metadata", {}) or {}
    hub = raw.get("agent_hub") if isinstance(raw, dict) else None
    for source in (hub if isinstance(hub, dict) else {}, metadata if isinstance(metadata, dict) else {}, raw if isinstance(raw, dict) else {}):
        for key in ("user_id", "enterprise_user_id", "actor_id", "subject_id"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def enterprise_workspace_from_request(config: Any, request: Any) -> str:
    raw = getattr(request, "raw", {}) or {}
    metadata = getattr(request, "metadata", {}) or {}
    hub = raw.get("agent_hub") if isinstance(raw, dict) else None
    for source in (hub if isinstance(hub, dict) else {}, metadata if isinstance(metadata, dict) else {}, raw if isinstance(raw, dict) else {}):
        for key in ("workspace_id", "enterprise_workspace_id"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(getattr(config, "enterprise_default_workspace_id", "default") or "default")


def _permission_names(*, action: str, category: str) -> set[str]:
    values = {"*", "all"}
    if action:
        values.add(action)
        values.add(f"action:{action}")
    if category:
        values.add(category)
        values.add(f"category:{category}")
        values.add(f"workspace:{category}")
    return values


def _permission_allowed(permissions: set[str], needed: set[str]) -> bool:
    normalized = {permission.strip().lower() for permission in permissions if permission}
    if normalized & {"*", "all", "workspace:*"}:
        return True
    return bool(normalized & {item.lower() for item in needed})


def _user_from_dict(data: dict[str, Any]) -> UserIdentity:
    return UserIdentity(
        id=str(data.get("id") or data.get("user_id") or ""),
        display_name=str(data.get("display_name") or data.get("name") or ""),
        email=str(data.get("email") or ""),
        roles=[str(item) for item in data.get("roles", []) if isinstance(item, str)],
    )


def _workspace_from_dict(data: dict[str, Any]) -> WorkspaceRef:
    return WorkspaceRef(
        id=str(data.get("id") or data.get("workspace_id") or ""),
        path=str(data.get("path") or ""),
        name=str(data.get("name") or ""),
    )


def _role_from_dict(data: dict[str, Any]) -> RoleDefinition:
    return RoleDefinition(
        name=str(data.get("name") or data.get("id") or ""),
        permissions=[str(item) for item in data.get("permissions", []) if isinstance(item, str)],
        description=str(data.get("description") or ""),
    )


def _grant_from_dict(data: dict[str, Any]) -> PermissionGrant:
    return PermissionGrant(
        subject_id=str(data.get("subject_id") or data.get("user_id") or data.get("role_id") or ""),
        workspace_id=str(data.get("workspace_id") or "*"),
        permission=str(data.get("permission") or ""),
        granted_by=str(data.get("granted_by") or ""),
        created_at=float(data.get("created_at") or time.time()),
    )


__all__ = [
    "EnterpriseAuditEvent",
    "EnterprisePolicy",
    "PermissionGrant",
    "RoleDefinition",
    "UserIdentity",
    "WorkspaceRef",
    "enterprise_subject_from_request",
    "enterprise_audit_events",
    "enterprise_workspace_from_request",
]
