from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from ..application.agent_service import AgentApplicationService, AgentServiceError
from ..security.secrets import redact_secrets


def handle_get(handler: object, path: str) -> bool:
    if path == "/v1/agents":
        handler._send_json(redact_secrets(AgentApplicationService(handler.server.config).list_agents()))
        return True
    name = _agent_name_from_path(path)
    if name is None:
        return False
    try:
        body = AgentApplicationService(handler.server.config).get_agent(name)
    except AgentServiceError as exc:
        handler._send_json(exc.to_response(), status=exc.status)
        return True
    handler._send_json(redact_secrets(body))
    return True


def handle_post(handler: object, path: str, payload: dict[str, Any]) -> bool:
    service = AgentApplicationService(handler.server.config)
    try:
        if path == "/v1/agents":
            body = service.create_agent(payload)
            handler.server.invalidate_diagnostics_cache("POST /v1/agents")
            handler._send_json(redact_secrets(body), status=201)
            return True
        name = _agent_name_from_path(path)
        if name is None:
            return False
        body = service.update_agent(name, payload)
        handler.server.invalidate_diagnostics_cache(f"POST /v1/agents/{name}")
        handler._send_json(redact_secrets(body))
        return True
    except AgentServiceError as exc:
        handler._send_json(exc.to_response(), status=exc.status)
        return True


def handle_delete(handler: object, path: str) -> bool:
    name = _agent_name_from_path(path)
    if name is None:
        return False
    try:
        body = AgentApplicationService(handler.server.config).delete_agent(name)
    except AgentServiceError as exc:
        handler._send_json(exc.to_response(), status=exc.status)
        return True
    handler.server.invalidate_diagnostics_cache(f"DELETE /v1/agents/{name}")
    handler._send_json(body)
    return True


def _agent_name_from_path(path: str) -> str | None:
    prefix = "/v1/agents/"
    if not path.startswith(prefix):
        return None
    name = unquote(path[len(prefix) :]).strip()
    if not name or "/" in name:
        return None
    return name


__all__ = ["handle_delete", "handle_get", "handle_post"]
