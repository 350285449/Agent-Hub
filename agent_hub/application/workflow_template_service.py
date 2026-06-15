from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..config import HubConfig
from ..plugins.discovery import discover_plugins
from ..workflows.planning import WorkflowPlanner
from ..workflows.selector import WORKFLOW_PATTERNS, WORKFLOW_PRESETS


_TEMPLATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


class WorkflowTemplateApplicationService:
    """Local workflow template catalog with built-in and user-defined entries."""

    def __init__(self, config: HubConfig) -> None:
        self.config = config

    def list_templates(self) -> dict[str, Any]:
        templates = self._builtin_templates()
        templates.update(self._plugin_templates())
        templates.update(self._load_local_templates())
        rows = [templates[key] for key in sorted(templates)]
        return {
            "object": "agent_hub.workflow_templates",
            "data": rows,
            "count": len(rows),
            "source": "builtin_and_local_state",
            "storage": str(self._template_path()),
        }

    def get_template(self, template_id: str) -> dict[str, Any]:
        template = self._templates_by_id().get(template_id)
        if template is None:
            raise WorkflowTemplateError(
                "workflow_template_not_found",
                f"Workflow template '{template_id}' is not configured.",
                status=404,
            )
        return {"object": "agent_hub.workflow_template", "data": template}

    def create_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        template = self._normalize_template(payload, source="local")
        templates = self._templates_by_id()
        if template["id"] in templates:
            raise WorkflowTemplateError(
                "workflow_template_exists",
                f"Workflow template '{template['id']}' already exists.",
                status=409,
            )
        local = self._load_local_templates()
        local[template["id"]] = template
        self._save_local_templates(local)
        return {"object": "agent_hub.workflow_template", "created": True, "data": template}

    def update_template(self, template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self._templates_by_id().get(template_id)
        if existing is None:
            raise WorkflowTemplateError(
                "workflow_template_not_found",
                f"Workflow template '{template_id}' is not configured.",
                status=404,
            )
        if existing.get("source") in {"builtin", "plugin"}:
            raise WorkflowTemplateError(
                "builtin_workflow_template_readonly",
                "Built-in and plugin workflow templates are read-only; create a local template with a new id.",
                status=409,
            )
        merged = {**existing, **payload, "id": template_id}
        template = self._normalize_template(merged, source="local")
        local = self._load_local_templates()
        local[template_id] = template
        self._save_local_templates(local)
        return {"object": "agent_hub.workflow_template", "updated": True, "data": template}

    def delete_template(self, template_id: str) -> dict[str, Any]:
        existing = self._templates_by_id().get(template_id)
        if existing is None:
            raise WorkflowTemplateError(
                "workflow_template_not_found",
                f"Workflow template '{template_id}' is not configured.",
                status=404,
            )
        if existing.get("source") in {"builtin", "plugin"}:
            raise WorkflowTemplateError(
                "builtin_workflow_template_readonly",
                "Built-in and plugin workflow templates are read-only.",
                status=409,
            )
        local = self._load_local_templates()
        local.pop(template_id, None)
        self._save_local_templates(local)
        return {"object": "agent_hub.workflow_template", "deleted": True, "id": template_id}

    def _templates_by_id(self) -> dict[str, dict[str, Any]]:
        templates = self._builtin_templates()
        templates.update(self._plugin_templates())
        templates.update(self._load_local_templates())
        return templates

    def _builtin_templates(self) -> dict[str, dict[str, Any]]:
        planner = WorkflowPlanner(self.config)
        templates: dict[str, dict[str, Any]] = {}
        for workflow in sorted(WorkflowPlanner.WORKFLOWS):
            stages = [asdict(stage) for stage in planner.stages(workflow)]
            templates[workflow] = {
                "id": workflow,
                "workflow": workflow,
                "pattern": "reviewed_worker",
                "description": f"Built-in {workflow} workflow.",
                "stages": stages,
                "enabled": True,
                "source": "builtin",
            }
        for preset_id, preset in sorted(WORKFLOW_PRESETS.items()):
            if not isinstance(preset, dict):
                continue
            pattern = str(preset.get("pattern") or "reviewed_worker")
            workflow = str(preset.get("workflow") or _workflow_for_preset(preset_id))
            templates[f"preset:{preset_id}"] = {
                "id": f"preset:{preset_id}",
                "preset": preset_id,
                "workflow": workflow,
                "pattern": pattern,
                "description": str(preset.get("description") or f"Built-in {preset_id} preset."),
                "routing_mode": preset.get("routing_mode"),
                "stages": [asdict(stage) for stage in planner.stages_for_pattern(workflow, pattern)],
                "enabled": True,
                "source": "builtin",
            }
        return templates

    def _plugin_templates(self) -> dict[str, dict[str, Any]]:
        templates: dict[str, dict[str, Any]] = {}
        for plugin in discover_plugins(self.config).plugins:
            if not plugin.registerable or plugin.manifest.type != "workflow":
                continue
            metadata = plugin.manifest.metadata if isinstance(plugin.manifest.metadata, dict) else {}
            try:
                template = self._normalize_template(
                    {
                        "id": metadata.get("template_id") or plugin.manifest.id,
                        "workflow": metadata.get("workflow", "code"),
                        "pattern": metadata.get("pattern", "reviewed_worker"),
                        "description": metadata.get("description") or plugin.manifest.description,
                        "routing_mode": metadata.get("routing_mode"),
                        "stages": metadata.get("stages"),
                    },
                    source="plugin",
                )
            except WorkflowTemplateError:
                continue
            template["plugin_id"] = plugin.manifest.id
            templates[template["id"]] = template
        return templates

    def _normalize_template(self, payload: dict[str, Any], *, source: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise WorkflowTemplateError("invalid_workflow_template", "Expected a workflow template object.", status=400)
        template_id = str(payload.get("id") or "").strip()
        if not _TEMPLATE_ID_RE.match(template_id):
            raise WorkflowTemplateError(
                "invalid_workflow_template_id",
                "Template id must be 1-80 characters and use letters, numbers, dots, underscores, or hyphens.",
                status=400,
            )
        workflow = _normalize_workflow(str(payload.get("workflow") or "code"))
        pattern = str(payload.get("pattern") or "reviewed_worker").strip().lower().replace("-", "_")
        if pattern not in WORKFLOW_PATTERNS:
            raise WorkflowTemplateError("invalid_workflow_pattern", f"Unknown workflow pattern '{pattern}'.", status=400)
        stages = payload.get("stages")
        normalized_stages = _normalize_stages(stages)
        if not normalized_stages:
            planner = WorkflowPlanner(self.config)
            normalized_stages = [asdict(stage) for stage in planner.stages_for_pattern(workflow, pattern)]
        template = {
            "id": template_id,
            "workflow": workflow,
            "pattern": pattern,
            "description": str(payload.get("description") or "").strip(),
            "routing_mode": _optional_string(payload.get("routing_mode")),
            "stages": normalized_stages,
            "enabled": _bool_with_default(payload.get("enabled"), True),
            "source": source,
        }
        return {key: value for key, value in template.items() if value is not None}

    def _load_local_templates(self) -> dict[str, dict[str, Any]]:
        path = self._template_path()
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        rows = raw.get("templates") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return {}
        templates: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                template = self._normalize_template(row, source="local")
            except WorkflowTemplateError:
                continue
            templates[template["id"]] = template
        return templates

    def _save_local_templates(self, templates: dict[str, dict[str, Any]]) -> None:
        path = self._template_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "object": "agent_hub.workflow_templates.local",
            "templates": [templates[key] for key in sorted(templates)],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _template_path(self) -> Path:
        return Path(self.config.state_dir) / "workflow_templates.json"


class WorkflowTemplateError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def to_response(self) -> dict[str, Any]:
        return {"error": {"type": self.code, "message": self.message}}


def _normalize_workflow(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    normalized = WorkflowPlanner.WORKFLOW_ALIASES.get(normalized, normalized)
    if normalized not in WorkflowPlanner.WORKFLOWS:
        raise WorkflowTemplateError("invalid_workflow", f"Unknown workflow '{value}'.", status=400)
    return normalized


def _normalize_stages(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    stages: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        role = str(item.get("role") or "").strip()
        preference = str(item.get("preference") or item.get("route") or "coding").strip()
        if name and role:
            stages.append({"name": name, "role": role, "preference": preference})
    return stages[:20]


def _workflow_for_preset(preset_id: str) -> str:
    lowered = preset_id.lower()
    if "security" in lowered or "architecture" in lowered:
        return "review"
    if "debug" in lowered or "bug" in lowered:
        return "debug"
    if "refactor" in lowered:
        return "refactor"
    return "code"


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _bool_with_default(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}
    return bool(value)


__all__ = ["WorkflowTemplateApplicationService", "WorkflowTemplateError"]
