from __future__ import annotations

from dataclasses import replace

from ..config import AgentConfig
from .base import (
    BaseProviderAdapter,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ProviderAdapter,
    ProviderHealth,
    StreamChunk,
)
from .descriptors import (
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderPricing,
    builtin_provider_descriptors,
    descriptor_from_metadata,
)
from .openai_chat import OpenAIChatProvider


class SimpleOpenAICompatibleProvider(OpenAIChatProvider):
    """Provider SDK base for chat-completions-compatible integrations."""

    descriptor: ProviderDescriptor

    def __init__(self, agent: AgentConfig) -> None:
        descriptor = getattr(self, "descriptor", None)
        if descriptor is None:
            raise TypeError(
                f"{self.__class__.__name__} must define a ProviderDescriptor"
            )
        super().__init__(_agent_with_descriptor_defaults(agent, descriptor))


def _agent_with_descriptor_defaults(
    agent: AgentConfig,
    descriptor: ProviderDescriptor,
) -> AgentConfig:
    headers = {**descriptor.headers, **agent.headers}
    return replace(
        agent,
        provider=agent.provider or descriptor.provider,
        provider_type=agent.provider_type or descriptor.provider_type,
        api_key_env=agent.api_key_env or descriptor.api_key_env,
        base_url=agent.base_url or descriptor.base_url,
        chat_completions_path=(
            agent.chat_completions_path or descriptor.chat_completions_path
        ),
        headers=headers,
        free=agent.free if agent.free is not None else descriptor.default_free,
        context_window=agent.context_window or descriptor.capabilities.context_window,
        supports_tools=_first_not_none(
            agent.supports_tools,
            descriptor.capabilities.supports_tools,
        ),
        supports_json=_first_not_none(
            agent.supports_json,
            descriptor.capabilities.supports_json,
        ),
        supports_streaming=_first_not_none(
            agent.supports_streaming,
            descriptor.capabilities.supports_streaming,
        ),
        supports_vision=_first_not_none(
            agent.supports_vision,
            descriptor.capabilities.supports_vision,
        ),
        supports_function_calling=_first_not_none(
            agent.supports_function_calling,
            descriptor.capabilities.supports_function_calling,
        ),
        cost_per_million_input=_first_not_none(
            agent.cost_per_million_input,
            descriptor.pricing.cost_per_million_input,
        ),
        cost_per_million_output=_first_not_none(
            agent.cost_per_million_output,
            descriptor.pricing.cost_per_million_output,
        ),
    )


def _first_not_none(*values: object) -> object:
    for value in values:
        if value is not None:
            return value
    return None


__all__ = [
    "BaseProviderAdapter",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ProviderAdapter",
    "ProviderCapabilities",
    "ProviderDescriptor",
    "ProviderHealth",
    "ProviderPricing",
    "SimpleOpenAICompatibleProvider",
    "StreamChunk",
    "builtin_provider_descriptors",
    "descriptor_from_metadata",
]
