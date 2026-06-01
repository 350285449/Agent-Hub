from __future__ import annotations

from importlib import import_module
from typing import Any, Protocol

from ..config import AgentConfig
from ..models import HubRequest, ProviderResult
from .base import (
    BaseProviderAdapter,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ProviderAdapter,
    ProviderHealth,
    StreamChunk,
)
from .errors import (
    AUTH_TEXT_MARKERS,
    CONTEXT_LIMIT_TEXT_MARKERS,
    ERROR_TYPE_ALIASES,
    FAILOVER_STATUSES,
    FAILOVER_TEXT_MARKERS,
    OUTPUT_LIMIT_TEXT_MARKERS,
    PASS_THROUGH_ERROR_TYPES,
    ProviderError,
    QUOTA_TEXT_MARKERS,
    RATE_LIMIT_TEXT_MARKERS,
    RETRYABLE_ERROR_TYPES,
    TEMPORARY_TEXT_MARKERS,
    UNSUPPORTED_TEXT_MARKERS,
    classify_provider_error,
    extract_error_message,
    provider_error_category,
    provider_error_from_http,
    provider_error_from_payload,
    provider_user_message,
)
from .quota import metadata_cooldown_seconds, quota_metadata_from_headers
from .registry import ProviderRegistry, provider_registry_key
from .shared import (
    _get_url_text,
    _post_json,
    _post_stream_json,
    _search_with_duckduckgo,
    provider_headers,
)
from .transport import (
    looks_like_timeout,
    post_json,
    post_stream_json,
    provider_request_id_from_headers,
)


_classify_provider_error = classify_provider_error
_extract_error_message = extract_error_message
_metadata_cooldown_seconds = metadata_cooldown_seconds
_provider_error_category = provider_error_category
_provider_error_from_http = provider_error_from_http
_provider_error_from_payload = provider_error_from_payload
_provider_request_id = provider_request_id_from_headers
_provider_user_message = provider_user_message
_quota_metadata_from_headers = quota_metadata_from_headers
_looks_like_timeout = looks_like_timeout


class Provider(ProviderAdapter, Protocol):
    agent: AgentConfig

    def complete(self, request: HubRequest) -> ProviderResult:
        ...


_PROVIDER_EXPORTS = {
    "EchoProvider": ("echo", "EchoProvider"),
    "OpenAIChatProvider": ("openai_chat", "OpenAIChatProvider"),
    "LocalResearchProvider": ("local_research", "LocalResearchProvider"),
    "AnthropicMessagesProvider": ("anthropic", "AnthropicMessagesProvider"),
    "GeminiProvider": ("gemini", "GeminiProvider"),
    "ProviderCapabilities": ("descriptors", "ProviderCapabilities"),
    "ProviderDescriptor": ("descriptors", "ProviderDescriptor"),
    "ProviderPricing": ("descriptors", "ProviderPricing"),
    "SimpleOpenAICompatibleProvider": ("sdk", "SimpleOpenAICompatibleProvider"),
    "builtin_provider_descriptors": ("descriptors", "builtin_provider_descriptors"),
    "descriptor_from_metadata": ("descriptors", "descriptor_from_metadata"),
}


def _load_provider_export(name: str) -> Any:
    target = _PROVIDER_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, export_name = target
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, export_name)
    globals()[name] = value
    return value


def __getattr__(name: str) -> Any:
    if name in _PROVIDER_EXPORTS:
        return _load_provider_export(name)
    if name.startswith("_"):
        shared = import_module(f"{__name__}.shared")
        if hasattr(shared, name):
            value = getattr(shared, name)
            globals()[name] = value
            return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *_PROVIDER_EXPORTS})


def create_provider(agent: AgentConfig) -> Provider:
    registry = _provider_registry()
    try:
        return registry.create(agent)
    except KeyError as exc:
        raise ProviderError(
            f"Unsupported provider {agent.provider!r}",
            retryable=False,
            error_type="configuration",
        ) from exc


def _provider_registry() -> ProviderRegistry[Provider]:
    registry = ProviderRegistry[Provider]()
    registry.register("ollama", _create_ollama_provider)
    registry.register("groq", _create_groq_provider)
    registry.register("openrouter", _create_openrouter_provider)
    registry.register("openai-chat", _load_provider_export("OpenAIChatProvider"))
    registry.register("local-research", _load_provider_export("LocalResearchProvider"))
    registry.register("anthropic", _load_provider_export("AnthropicMessagesProvider"))
    registry.register("gemini", _load_provider_export("GeminiProvider"))
    registry.register("echo", _load_provider_export("EchoProvider"))
    return registry


def _create_ollama_provider(agent: AgentConfig) -> Provider:
    provider = getattr(import_module(f"{__name__}.ollama"), "OllamaProvider")
    return provider(agent)


def _create_groq_provider(agent: AgentConfig) -> Provider:
    provider = getattr(import_module(f"{__name__}.groq"), "GroqProvider")
    return provider(agent)


def _create_openrouter_provider(agent: AgentConfig) -> Provider:
    provider = getattr(import_module(f"{__name__}.openrouter"), "OpenRouterProvider")
    return provider(agent)


__all__ = [
    "AUTH_TEXT_MARKERS",
    "AnthropicMessagesProvider",
    "BaseProviderAdapter",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "CONTEXT_LIMIT_TEXT_MARKERS",
    "ERROR_TYPE_ALIASES",
    "EchoProvider",
    "FAILOVER_STATUSES",
    "FAILOVER_TEXT_MARKERS",
    "GeminiProvider",
    "LocalResearchProvider",
    "OpenAIChatProvider",
    "OUTPUT_LIMIT_TEXT_MARKERS",
    "PASS_THROUGH_ERROR_TYPES",
    "Provider",
    "ProviderAdapter",
    "ProviderCapabilities",
    "ProviderDescriptor",
    "ProviderError",
    "ProviderHealth",
    "ProviderPricing",
    "QUOTA_TEXT_MARKERS",
    "RATE_LIMIT_TEXT_MARKERS",
    "RETRYABLE_ERROR_TYPES",
    "StreamChunk",
    "SimpleOpenAICompatibleProvider",
    "TEMPORARY_TEXT_MARKERS",
    "UNSUPPORTED_TEXT_MARKERS",
    "classify_provider_error",
    "create_provider",
    "builtin_provider_descriptors",
    "descriptor_from_metadata",
    "extract_error_message",
    "looks_like_timeout",
    "metadata_cooldown_seconds",
    "post_json",
    "post_stream_json",
    "provider_error_category",
    "provider_error_from_http",
    "provider_error_from_payload",
    "provider_headers",
    "provider_registry_key",
    "provider_request_id_from_headers",
    "provider_user_message",
    "quota_metadata_from_headers",
]
