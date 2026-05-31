from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import AgentConfig


@dataclass(frozen=True, slots=True)
class AgentCapabilities:
    """Normalized capability view for routing, providers, and diagnostics."""

    supports_tools: bool = False
    supports_json: bool = False
    supports_streaming: bool = False
    supports_vision: bool = False
    supports_function_calling: bool = False
    context_window: int | None = None
    max_output_tokens: int | None = None

    @property
    def tool_capable(self) -> bool:
        return self.supports_tools or self.supports_function_calling

    def to_graph_dict(self) -> dict[str, Any]:
        return {
            "tools": self.tool_capable,
            "json": self.supports_json,
            "streaming": self.supports_streaming,
            "vision": self.supports_vision,
            "context_window": self.context_window,
        }

    def to_model_info_dict(self) -> dict[str, Any]:
        return {
            "context_window": self.context_window,
            "supports_streaming": self.supports_streaming,
            "supports_tools": self.tool_capable,
            "supports_vision": self.supports_vision,
        }

    def to_health_fields(self) -> dict[str, Any]:
        return {
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supports_streaming": self.supports_streaming,
            "supports_tools": self.tool_capable,
            "supports_json": self.supports_json,
            "supports_function_calling": self.supports_function_calling,
        }


def agent_capabilities(agent: AgentConfig) -> AgentCapabilities:
    """Return capability defaults with current AgentConfig truthiness semantics."""

    return AgentCapabilities(
        supports_tools=bool(agent.supports_tools),
        supports_json=bool(agent.supports_json),
        supports_streaming=bool(agent.supports_streaming),
        supports_vision=bool(agent.supports_vision),
        supports_function_calling=bool(agent.supports_function_calling),
        context_window=agent.context_window,
        max_output_tokens=agent.max_tokens,
    )


def agent_supports_tools(agent: AgentConfig) -> bool:
    return agent_capabilities(agent).tool_capable


__all__ = ["AgentCapabilities", "agent_capabilities", "agent_supports_tools"]
