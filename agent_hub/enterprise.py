from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


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
            "actor_id": self.actor_id,
            "action": self.action,
            "workspace_id": self.workspace_id,
            "target": self.target,
            "allowed": self.allowed,
            "reason": self.reason,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }


__all__ = [
    "EnterpriseAuditEvent",
    "PermissionGrant",
    "RoleDefinition",
    "UserIdentity",
    "WorkspaceRef",
]
