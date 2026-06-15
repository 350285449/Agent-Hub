from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from ..application.workflow_template_service import WorkflowTemplateApplicationService, WorkflowTemplateError


def handle_get(handler: object, path: str) -> bool:
    if path in {"/v1/workflow-templates", "/v1/workflow-presets"}:
        handler._send_json(WorkflowTemplateApplicationService(handler.server.config).list_templates())
        return True
    template_id = _template_id_from_path(path)
    if template_id is None:
        return False
    try:
        body = WorkflowTemplateApplicationService(handler.server.config).get_template(template_id)
    except WorkflowTemplateError as exc:
        handler._send_json(exc.to_response(), status=exc.status)
        return True
    handler._send_json(body)
    return True


def handle_post(handler: object, path: str, payload: dict[str, Any]) -> bool:
    service = WorkflowTemplateApplicationService(handler.server.config)
    try:
        if path == "/v1/workflow-templates":
            body = service.create_template(payload)
            handler.server.invalidate_diagnostics_cache("POST /v1/workflow-templates")
            handler._send_json(body, status=201)
            return True
        template_id = _template_id_from_path(path)
        if template_id is None:
            return False
        body = service.update_template(template_id, payload)
        handler.server.invalidate_diagnostics_cache(f"POST /v1/workflow-templates/{template_id}")
        handler._send_json(body)
        return True
    except WorkflowTemplateError as exc:
        handler._send_json(exc.to_response(), status=exc.status)
        return True


def handle_delete(handler: object, path: str) -> bool:
    template_id = _template_id_from_path(path)
    if template_id is None:
        return False
    try:
        body = WorkflowTemplateApplicationService(handler.server.config).delete_template(template_id)
    except WorkflowTemplateError as exc:
        handler._send_json(exc.to_response(), status=exc.status)
        return True
    handler.server.invalidate_diagnostics_cache(f"DELETE /v1/workflow-templates/{template_id}")
    handler._send_json(body)
    return True


def _template_id_from_path(path: str) -> str | None:
    prefix = "/v1/workflow-templates/"
    if not path.startswith(prefix):
        return None
    template_id = unquote(path[len(prefix) :]).strip()
    if not template_id or "/" in template_id:
        return None
    return template_id


__all__ = ["handle_delete", "handle_get", "handle_post"]
