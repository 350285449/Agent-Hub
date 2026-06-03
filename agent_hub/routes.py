from __future__ import annotations

from typing import Any

from .routes_chat import handle_post as handle_chat_post
from .routes_config import handle_get as handle_config_get
from .routes_health import handle_get as handle_health_get
from .routes_providers import handle_get as handle_provider_get


def handle_get(handler: object, path: str) -> bool:
    return (
        handle_config_get(handler, path)
        or handle_health_get(handler, path)
        or handle_provider_get(handler, path)
    )


def handle_post(handler: object, path: str, payload: dict[str, Any]) -> bool:
    return handle_chat_post(handler, path, payload)
