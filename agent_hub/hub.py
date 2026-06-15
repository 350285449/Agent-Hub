from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import HubConfig, load_config
from .core.router import AgentRouter
from .models import HubRequest, HubResponse, Message


class AgentHub:
    """Small library-mode facade over the local routing runtime."""

    def __init__(self, config: HubConfig, router: AgentRouter | None = None) -> None:
        self.config = config
        self.router = router or AgentRouter(config)

    @classmethod
    def load(
        cls,
        path: str | Path = "agent-hub.config.json",
        *,
        create_if_missing: bool = True,
        auto_detect: bool = True,
    ) -> "AgentHub":
        config = load_config(path, create_if_missing=create_if_missing, auto_detect=auto_detect)
        return cls(config)

    def route(
        self,
        prompt: str | Sequence[Message],
        *,
        session_id: str | None = None,
        task: str | None = None,
        route: str | None = None,
        context: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> HubResponse:
        request = HubRequest(
            messages=_messages_from_prompt(prompt),
            session_id=session_id or f"lib-{uuid4().hex}",
            task=task,
            route=route,
            context=context,
            api_shape="library",
            metadata=dict(metadata or {}),
        )
        return self.router.route(request)


def _messages_from_prompt(prompt: str | Sequence[Message]) -> list[Message]:
    if isinstance(prompt, str):
        return [{"role": "user", "content": prompt}]
    return [dict(message) for message in prompt]


__all__ = ["AgentHub"]
