from __future__ import annotations

from typing import Any

from .agents import handle_delete as handle_agent_delete
from .agents import handle_get as handle_agent_get
from .agents import handle_post as handle_agent_post
from .chat import handle_post as handle_chat_post
from .config import handle_get as handle_config_get
from .config import handle_post as handle_config_post
from .health import handle_get as handle_health_get
from .providers import handle_get as handle_provider_get
from .routing_profiles import handle_delete as handle_routing_profile_delete
from .routing_profiles import handle_get as handle_routing_profile_get
from .routing_profiles import handle_post as handle_routing_profile_post
from .workflow_templates import handle_delete as handle_workflow_template_delete
from .workflow_templates import handle_get as handle_workflow_template_get
from .workflow_templates import handle_post as handle_workflow_template_post


def handle_get(handler: object, path: str) -> bool:
    return (
        handle_agent_get(handler, path)
        or handle_routing_profile_get(handler, path)
        or handle_workflow_template_get(handler, path)
        or handle_config_get(handler, path)
        or handle_health_get(handler, path)
        or handle_provider_get(handler, path)
    )


def handle_post(handler: object, path: str, payload: dict[str, Any]) -> bool:
    return (
        handle_agent_post(handler, path, payload)
        or handle_routing_profile_post(handler, path, payload)
        or handle_workflow_template_post(handler, path, payload)
        or handle_config_post(handler, path, payload)
        or handle_chat_post(handler, path, payload)
    )


def handle_delete(handler: object, path: str) -> bool:
    return (
        handle_agent_delete(handler, path)
        or handle_routing_profile_delete(handler, path)
        or handle_workflow_template_delete(handler, path)
    )


__all__ = ["handle_delete", "handle_get", "handle_post"]
