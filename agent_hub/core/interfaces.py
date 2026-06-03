from __future__ import annotations

from typing import Any, Protocol

from ..config import AgentConfig
from ..models import HubRequest, HubResponse, ProviderResult


class RoutingPolicy(Protocol):
    def decide(self, request: HubRequest) -> Any:
        ...


class ContextEngineBoundary(Protocol):
    def prepare(self, request: HubRequest, *, include_tools: bool = True) -> HubRequest:
        ...


class ProviderExecutor(Protocol):
    def chat(self, agent_or_name: AgentConfig | str, request: HubRequest) -> ProviderResult:
        ...

    def stream(self, agent_or_name: AgentConfig | str, request: HubRequest) -> Any:
        ...


class ToolPermissionBoundary(Protocol):
    def check(self, tool: Any, call: Any) -> Any:
        ...


class WorkflowOrchestrator(Protocol):
    def execute(self, kind: str, request: HubRequest, **kwargs: Any) -> Any:
        ...


class RouterBoundary(Protocol):
    """Router contract: select provider/model and return a provider response."""

    def decide(self, request: HubRequest) -> Any:
        ...

    def route(self, request: HubRequest) -> HubResponse:
        ...


__all__ = [
    "ContextEngineBoundary",
    "ProviderExecutor",
    "RouterBoundary",
    "RoutingPolicy",
    "ToolPermissionBoundary",
    "WorkflowOrchestrator",
]
