from __future__ import annotations

from typing import Any

from .chat import handle_post as handle_chat_post
from .config import handle_get as handle_config_get
from .health import handle_get as handle_health_get
from .providers import handle_get as handle_provider_get


def handle_get(handler: object, path: str) -> bool:
    return (
        handle_config_get(handler, path)
        or handle_health_get(handler, path)
        or handle_provider_get(handler, path)
    )


def handle_post(handler: object, path: str, payload: dict[str, Any]) -> bool:
    return handle_chat_post(handler, path, payload)


__all__ = ["handle_get", "handle_post"]
