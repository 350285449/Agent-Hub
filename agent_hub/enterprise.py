from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .observability import record_event
from .security.secrets import redact_secrets


DEFAULT_ENTERPRISE_ROLES = {
    "viewer": ["read", "dashboard:view", "audit:view"],
    "developer": ["read", "route", "benchmark:run", "settings:view"],
    "admin": ["*", "settings:change", "policy:change", "audit:view"],
}


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
    never_use_external_models: bool = False
    never_use_premium_models: bool = False
    only_local_models: bool = False

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
        for name, permissions in DEFAULT_ENTERPRISE_ROLES.items():
            roles.setdefault(name, RoleDefinition(name=name, permissions=list(permissions)))
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
            never_use_external_models=bool(getattr(config, "enterprise_never_use_external_models", False)),
            never_use_premium_models=bool(getattr(config, "enterprise_never_use_premium_models", False)),
            only_local_models=bool(getattr(config, "enterprise_only_local_models", False)),
        )

    def allows_model(self, agent: Any) -> tuple[bool, str]:
        provider = str(getattr(agent, "provider", "") or "")
        local = bool(getattr(agent, "local_only", False)) or provider in {"ollama", "local-research"} or "local" in provider
        premium = bool(getattr(agent, "free", None) is False)
        if self.only_local_models and not local:
            return False, "Enterprise policy allows only local models."
        if self.never_use_external_models and not local:
            return False, "Enterprise policy blocks external models."
        if self.never_use_premium_models and premium:
            return False, "Enterprise policy blocks premium models."
        return True, ""

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


def enterprise_audit_events(
    state_dir: str | Path,
    *,
    limit: int = 100,
    user: str | None = None,
    workspace: str | None = None,
    action: str | None = None,
    allowed: bool | None = None,
    start_at: Any = None,
    end_at: Any = None,
    retention_days: int | None = None,
    now: float | None = None,
) -> list[dict[str, Any]]:
    return export_enterprise_audit(
        state_dir,
        limit=limit,
        user=user,
        workspace=workspace,
        action=action,
        allowed=allowed,
        start_at=start_at,
        end_at=end_at,
        retention_days=retention_days,
        now=now,
    )["events"]


def export_enterprise_audit(
    state_dir: str | Path,
    *,
    limit: int = 100,
    user: str | None = None,
    workspace: str | None = None,
    action: str | None = None,
    allowed: bool | None = None,
    start_at: Any = None,
    end_at: Any = None,
    retention_days: int | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    events = _enterprise_audit_jsonl_events(state_dir)
    events = _filter_enterprise_audit_events(
        events,
        user=user,
        workspace=workspace,
        action=action,
        allowed=allowed,
        start_at=start_at,
        end_at=end_at,
        retention_days=retention_days,
        now=now,
    )
    try:
        limit = int(limit or 100)
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 1000))
    events = events[-limit:]
    return redact_secrets(
        {
            "object": "agent_hub.enterprise_audit_export",
            "count": len(events),
            "events": events,
            "filters": {
                "user": user or "",
                "workspace": workspace or "",
                "action": action or "",
                "allowed": allowed,
                "start_at": start_at,
                "end_at": end_at,
                "retention_days": retention_days,
                "limit": limit,
            },
        }
    )


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


def _enterprise_audit_jsonl_events(state_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(state_dir) / "enterprise_audit.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _filter_enterprise_audit_events(
    events: list[dict[str, Any]],
    *,
    user: str | None,
    workspace: str | None,
    action: str | None,
    allowed: bool | None,
    start_at: Any,
    end_at: Any,
    retention_days: int | None,
    now: float | None,
) -> list[dict[str, Any]]:
    start = _parse_audit_timestamp(start_at)
    end = _parse_audit_timestamp(end_at)
    cutoff = _retention_cutoff(retention_days, now=now)
    filtered: list[dict[str, Any]] = []
    for event in events:
        timestamp = _event_timestamp(event)
        if cutoff is not None and (timestamp is None or timestamp < cutoff):
            continue
        if start is not None and (timestamp is None or timestamp < start):
            continue
        if end is not None and (timestamp is None or timestamp > end):
            continue
        if user and str(event.get("user") or event.get("actor_id") or "") != user:
            continue
        if workspace and str(event.get("workspace") or event.get("workspace_id") or "") != workspace:
            continue
        if action and str(event.get("action") or "") != action:
            continue
        if allowed is not None and bool(event.get("allowed")) is not allowed:
            continue
        filtered.append(event)
    return filtered


def _retention_cutoff(retention_days: int | None, *, now: float | None) -> float | None:
    if retention_days is None:
        return None
    try:
        days = int(retention_days)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return (now if now is not None else time.time()) - (days * 24 * 60 * 60)


def _event_timestamp(event: dict[str, Any]) -> float | None:
    for key in ("created_at", "timestamp", "time"):
        parsed = _parse_audit_timestamp(event.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_audit_timestamp(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


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
    "DEFAULT_ENTERPRISE_ROLES",
    "EnterpriseAuditEvent",
    "EnterprisePolicy",
    "PermissionGrant",
    "RoleDefinition",
    "UserIdentity",
    "WorkspaceRef",
    "enterprise_subject_from_request",
    "enterprise_audit_events",
    "export_enterprise_audit",
    "enterprise_workspace_from_request",
]
