from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


Message = dict[str, Any]


class ErrorCategory:
    """Stable internal error categories for recovery and user messages."""

    PROVIDER = "provider"
    NETWORK = "network"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    CONTEXT_LIMIT = "context_limit"
    CONFIGURATION = "configuration"
    PERMISSION = "permission"
    TOOL = "tool"
    STREAM = "stream"
    VALIDATION = "validation"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class StructuredError:
    """Provider-neutral error payload used by routers, providers, and tools."""

    category: str
    code: str
    message: str
    retryable: bool = False
    user_message: str = ""
    status_code: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "category": self.category,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "user_message": self.user_message or self.message,
        }
        if self.status_code is not None:
            data["status_code"] = self.status_code
        if self.details:
            data["details"] = self.details
        return data


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
    citations: list[str] = field(default_factory=list)
    search_results: list[dict[str, Any]] = field(default_factory=list)
    related_questions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FailoverEvent:
    agent: str
    provider: str
    model: str
    reason: str
    status_code: int | None = None
    retryable: bool = True
    error_type: str | None = None
    unavailable_until: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "agent": self.agent,
            "provider": self.provider,
            "model": self.model,
            "reason": self.reason,
            "status_code": self.status_code,
            "retryable": self.retryable,
        }
        if self.error_type:
            data["error_type"] = self.error_type
        if self.unavailable_until is not None:
            data["unavailable_until"] = self.unavailable_until
        if self.metadata:
            data["metadata"] = self.metadata
        return data


@dataclass(slots=True)
class HubResponse:
    """Provider-neutral result returned by the router."""

    request_id: str
    session_id: str
    agent: str
    provider: str
    model: str
    text: str
    public_model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None
    failover: list[FailoverEvent] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    search_results: list[dict[str, Any]] = field(default_factory=list)
    related_questions: list[str] = field(default_factory=list)

    def to_native_dict(
        self,
        include_raw: bool = False,
        include_routing_details: bool = False,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.request_id,
            "request_id": self.request_id,
            "object": "agent_hub.response",
            "session_id": self.session_id,
            "model": self.public_model or self.model,
            "message": {
                "role": "assistant",
                "content": self.text,
            },
            "finish_reason": self.finish_reason,
            "usage": self.usage,
        }
        if include_routing_details:
            data["agent"] = {
                "name": self.agent,
                "provider": self.provider,
                "model": self.model,
            }
            data["failover"] = [event.to_dict() for event in self.failover]
            agent_metadata = self.raw.get("agent_hub")
            if isinstance(agent_metadata, dict):
                data["agent_hub"] = agent_metadata
        if include_raw:
            data["raw"] = self.raw
        if self.citations:
            data["citations"] = self.citations
        if self.search_results:
            data["search_results"] = self.search_results
        if self.related_questions:
            data["related_questions"] = self.related_questions
        return data
