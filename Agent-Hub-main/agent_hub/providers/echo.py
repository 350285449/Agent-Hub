from __future__ import annotations

from ..config import AgentConfig
from ..models import HubRequest, ProviderResult
from ..payloads import content_to_text
from .base import BaseProviderAdapter
from .shared import _rough_tokens

class EchoProvider(BaseProviderAdapter):
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        last = ""
        for message in reversed(request.messages):
            if message.get("role") == "user":
                last = content_to_text(message.get("content"))
                break
        text = f"[{self.agent.name}] {last}".strip()
        return ProviderResult(
            text=text,
            model=self.agent.model,
            raw={"echo": True},
            usage={
                "input_tokens": _rough_tokens(request),
                "output_tokens": max(1, len(text) // 4),
            },
            finish_reason="stop",
        )


EchoAdapter = EchoProvider


__all__ = ["EchoAdapter", "EchoProvider"]
