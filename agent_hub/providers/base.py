from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from ..capabilities import agent_capabilities
from ..config import AgentConfig, is_free_agent
from ..models import HubRequest, ProviderResult


@dataclass(slots=True)
class ChatMessage:
    """Provider-neutral chat message used by provider adapters."""

    role: str
    content: Any
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ChatMessage":
        return cls(
            role=str(value.get("role", "user")),
            content=value.get("content", ""),
            name=value.get("name"),
            tool_call_id=value.get("tool_call_id") or value.get("tool_use_id"),
            tool_calls=list(value.get("tool_calls") or []),
            metadata={
                key: item
                for key, item in value.items()
                if key not in {"role", "content", "name", "tool_call_id", "tool_use_id", "tool_calls"}
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            data["name"] = self.name
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            data["tool_calls"] = list(self.tool_calls)
        data.update(self.metadata)
        return data


@dataclass(slots=True)
class ChatRequest:
    """Strict provider adapter input independent from HTTP/UI request shapes."""

    messages: list[ChatMessage]
    session_id: str = ""
    model: str | None = None
    provider: str | None = None
    task: str | None = None
    context: str | None = None
    route: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = False
    tools: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_hub_request(cls, request: HubRequest, *, model: str | None = None, provider: str | None = None) -> "ChatRequest":
        raw = request.raw if isinstance(request.raw, dict) else {}
        tools = raw.get("tools")
        return cls(
            messages=[ChatMessage.from_mapping(message) for message in request.messages],
            session_id=request.session_id,
            model=model or raw.get("model"),
            provider=provider,
            task=request.task,
            context=request.context,
            route=request.route,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            stream=request.stream,
            tools=list(tools) if isinstance(tools, list) else [],
            raw=raw,
            metadata=dict(request.metadata),
        )

    def to_hub_request(self, *, api_shape: str = "native", record_session: bool = False) -> HubRequest:
        return HubRequest(
            messages=[message.to_dict() for message in self.messages],
            session_id=self.session_id or "provider-adapter",
            task=self.task,
            context=self.context,
            route=self.route,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            stream=self.stream,
            record_session=record_session,
            api_shape=api_shape,
            raw=dict(self.raw),
            metadata=dict(self.metadata),
        )


@dataclass(slots=True)
class ChatResponse:
    """Strict provider adapter output normalized across providers."""

    text: str
    model: str
    provider: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None
    citations: list[str] = field(default_factory=list)
    search_results: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    related_questions: list[str] = field(default_factory=list)

    @classmethod
    def from_provider_result(cls, result: ProviderResult, *, provider: str | None = None) -> "ChatResponse":
        return cls(
            text=result.text,
            model=result.model,
            provider=provider,
            raw=dict(result.raw),
            usage=dict(result.usage),
            finish_reason=result.finish_reason,
            citations=list(result.citations),
            search_results=list(result.search_results),
            images=list(result.images),
            related_questions=list(result.related_questions),
        )

    def to_provider_result(self) -> ProviderResult:
        return ProviderResult(
            text=self.text,
            model=self.model,
            raw=dict(self.raw),
            usage=dict(self.usage),
            finish_reason=self.finish_reason,
            citations=list(self.citations),
            search_results=list(self.search_results),
            images=list(self.images),
            related_questions=list(self.related_questions),
        )


@dataclass(slots=True)
class StreamChunk:
    """Normalized streaming delta returned by streaming-capable adapters."""

    text: str = ""
    delta: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderHealth:
    """Lightweight live adapter health response."""

    name: str
    provider: str
    model: str
    available: bool
    status: str = "unknown"
    latency_ms: float | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ProviderAdapter(Protocol):
    """Strict interface every provider adapter exposes to the router."""

    agent: AgentConfig

    @property
    def name(self) -> str:
        ...

    @property
    def display_name(self) -> str:
        ...

    @property
    def models(self) -> list[str]:
        ...

    def chat(self, request: ChatRequest | HubRequest) -> ChatResponse:
        ...

    def stream(self, request: ChatRequest | HubRequest) -> Iterable["StreamChunk"]:
        ...

    def health_check(self) -> ProviderHealth:
        ...

    def supports_streaming(self) -> bool:
        ...

    def supports_tools(self) -> bool:
        ...

    def supports_vision(self) -> bool:
        ...

    def context_limit(self, model: str | None = None) -> int | None:
        ...

    def cost_estimate(self, input_tokens: int, output_tokens: int, model: str | None = None) -> float | None:
        ...

    def normalize_request(self, request: ChatRequest | HubRequest) -> ChatRequest:
        ...

    def normalize_response(self, response: ChatResponse | ProviderResult | dict[str, Any]) -> ChatResponse:
        ...


class BaseProviderAdapter:
    """Mixin for config-backed adapters that still expose the legacy complete API."""

    agent: AgentConfig

    @property
    def name(self) -> str:
        return self.agent.name

    @property
    def display_name(self) -> str:
        provider = self.agent.provider_type or self.agent.provider
        return f"{provider} / {self.agent.model}"

    @property
    def models(self) -> list[str]:
        return [self.agent.model]

    def chat(self, request: ChatRequest | HubRequest) -> ChatResponse:
        hub_request = (
            request
            if isinstance(request, HubRequest)
            else request.to_hub_request(api_shape="native", record_session=False)
        )
        result = self.complete(hub_request)
        return self.normalize_response(result)

    def stream(self, request: ChatRequest | HubRequest) -> Iterable[StreamChunk]:
        if not self.supports_streaming():
            raise NotImplementedError(f"{self.name} does not support streaming")
        raise NotImplementedError(f"{self.name} has not implemented native streaming yet")

    def complete(self, request: HubRequest) -> ProviderResult:
        raise NotImplementedError

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            provider=self.agent.provider,
            model=self.agent.model,
            available=bool(self.agent.enabled),
            status="configured" if self.agent.enabled else "disabled",
        )

    def supports_streaming(self) -> bool:
        return agent_capabilities(self.agent).supports_streaming

    def supports_tools(self) -> bool:
        return agent_capabilities(self.agent).tool_capable

    def supports_vision(self) -> bool:
        return agent_capabilities(self.agent).supports_vision

    def context_limit(self, model: str | None = None) -> int | None:
        if model is not None and model != self.agent.model:
            return None
        return agent_capabilities(self.agent).context_window

    def cost_estimate(self, input_tokens: int, output_tokens: int, model: str | None = None) -> float | None:
        if model is not None and model != self.agent.model:
            return None
        if is_free_agent(self.agent):
            return 0.0
        return None

    def normalize_request(self, request: ChatRequest | HubRequest) -> ChatRequest:
        if isinstance(request, ChatRequest):
            return request
        return ChatRequest.from_hub_request(
            request,
            model=self.agent.model,
            provider=self.agent.provider,
        )

    def normalize_response(self, response: ChatResponse | ProviderResult | dict[str, Any]) -> ChatResponse:
        if isinstance(response, ChatResponse):
            return response
        if isinstance(response, ProviderResult):
            return ChatResponse.from_provider_result(response, provider=self.agent.provider)
        return ChatResponse(
            text=str(response.get("text", "")),
            model=str(response.get("model") or self.agent.model),
            provider=self.agent.provider,
            raw=dict(response),
            usage=dict(response.get("usage") or {}),
            finish_reason=response.get("finish_reason"),
        )
