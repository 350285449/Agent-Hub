from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


Message = dict[str, Any]


@dataclass(slots=True)
class HubRequest:
    """Provider-neutral request used inside the hub."""

    messages: list[Message]
    session_id: str
    task: str | None = None
    context: str | None = None
    route: str | None = None
    preferred_agent: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = False
    use_session_history: bool = False
    record_session: bool = True
    api_shape: str = "native"
    raw: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderResult:
    """Normalized provider response."""

    text: str
    model: str
    raw: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None


@dataclass(slots=True)
class FailoverEvent:
    agent: str
    provider: str
    model: str
    reason: str
    status_code: int | None = None
    retryable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "provider": self.provider,
            "model": self.model,
            "reason": self.reason,
            "status_code": self.status_code,
            "retryable": self.retryable,
        }


@dataclass(slots=True)
class HubResponse:
    """Provider-neutral result returned by the router."""

    request_id: str
    session_id: str
    agent: str
    provider: str
    model: str
    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None
    failover: list[FailoverEvent] = field(default_factory=list)

    def to_native_dict(self, include_raw: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.request_id,
            "object": "agent_hub.response",
            "session_id": self.session_id,
            "agent": {
                "name": self.agent,
                "provider": self.provider,
                "model": self.model,
            },
            "message": {
                "role": "assistant",
                "content": self.text,
            },
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "failover": [event.to_dict() for event in self.failover],
        }
        if include_raw:
            data["raw"] = self.raw
        return data
