from __future__ import annotations

from typing import Any, Iterator

from ..config import AgentConfig, normalize_provider
from ..models import HubRequest, ProviderResult
from .base import BaseProviderAdapter, StreamChunk
from .errors import ProviderError
from .shared import (
    _agent_hub_tool_specs,
    _chat_completions_url,
    _copy_allowed,
    _facade_callable,
    _normalize_chat_result_for_agent,
    _openai_messages,
    _openai_tool_choice,
    _openai_tool_specs,
    _post_json_with_output_retry,
    _post_stream_json,
    _provider_debug,
    _request_tool_specs,
    _stream_chunk_from_openai_data,
    provider_headers,
)


class OpenAIChatProvider(BaseProviderAdapter):
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        api_key = self.agent.resolved_api_key
        if not api_key and normalize_provider(self.agent.provider) == "openai":
            raise ProviderError(
                f"{self.agent.name} is missing API key env {self.agent.api_key_env}",
                retryable=True,
                error_type="configuration",
            )

        payload = self._payload(request)
        headers = provider_headers(self.agent, api_key)

        raw = _post_json_with_output_retry(
            url=_chat_completions_url(self.agent),
            headers=headers,
            payload=payload,
            timeout=self.agent.timeout_seconds,
            debug=_provider_debug(request, self.agent),
            request=request,
            agent=self.agent,
        )
        return _normalize_chat_result_for_agent(raw, self.agent)

    def stream(self, request: HubRequest) -> Iterator[StreamChunk]:
        if not self.supports_streaming():
            raise NotImplementedError(f"{self.name} does not support native streaming")
        api_key = self.agent.resolved_api_key
        if not api_key and normalize_provider(self.agent.provider) == "openai":
            raise ProviderError(
                f"{self.agent.name} is missing API key env {self.agent.api_key_env}",
                retryable=True,
                error_type="configuration",
            )

        payload = self._payload(request)
        payload["stream"] = True
        headers = provider_headers(self.agent, api_key)
        post_stream_json = _facade_callable("_post_stream_json", _post_stream_json)
        for data in post_stream_json(
            url=_chat_completions_url(self.agent),
            headers=headers,
            payload=payload,
            timeout=self.agent.timeout_seconds,
            debug=_provider_debug(request, self.agent),
        ):
            chunk = _stream_chunk_from_openai_data(data, default_model=self.agent.model)
            if chunk is not None:
                yield chunk

    def _payload(self, request: HubRequest) -> dict[str, Any]:
        payload = _copy_allowed(
            request.raw,
            {
                "frequency_penalty",
                "function_call",
                "functions",
                "logit_bias",
                "logprobs",
                "metadata",
                "modalities",
                "n",
                "parallel_tool_calls",
                "presence_penalty",
                "reasoning_effort",
                "response_format",
                "seed",
                "service_tier",
                "stop",
                "store",
                "stream_options",
                "temperature",
                "tool_choice",
                "tools",
                "top_logprobs",
                "top_p",
                "user",
            },
        )
        agent_tools = _request_tool_specs(request)
        legacy_functions = (
            not _agent_hub_tool_specs(request)
            and "tools" not in request.raw
            and isinstance(request.raw.get("functions"), list)
        )
        if agent_tools and not legacy_functions:
            payload["tools"] = _openai_tool_specs(agent_tools)
            converted_choice = _openai_tool_choice(
                request.raw.get("tool_choice", request.raw.get("function_call"))
            )
            if converted_choice is not None:
                payload["tool_choice"] = converted_choice
            else:
                payload.setdefault("tool_choice", "auto")
        payload["model"] = self.agent.model
        payload["messages"] = _openai_messages(request.messages)
        if request.max_tokens is not None:
            if "max_completion_tokens" in request.raw:
                payload["max_completion_tokens"] = request.max_tokens
            else:
                payload["max_tokens"] = request.max_tokens
        elif self.agent.max_tokens is not None:
            payload["max_tokens"] = self.agent.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        return payload


OpenAIChatAdapter = OpenAIChatProvider


__all__ = ["OpenAIChatAdapter", "OpenAIChatProvider"]
