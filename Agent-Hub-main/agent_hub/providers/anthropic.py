from __future__ import annotations

from typing import Any

from ..config import AgentConfig
from ..models import HubRequest, ProviderResult
from ..payloads import content_to_text
from ..response_normalization import normalize_anthropic_result
from .base import BaseProviderAdapter
from .errors import ProviderError
from .shared import (
    _anthropic_append_text_block,
    _anthropic_assistant_content,
    _anthropic_tool_choice,
    _anthropic_tool_specs,
    _anthropic_user_content,
    _append_extra_context,
    _copy_allowed,
    _join_url,
    _message_extra_context_text,
    _post_json_with_output_retry,
    _provider_debug,
    _request_tool_specs,
    _required_provider_max_tokens,
)

class AnthropicMessagesProvider(BaseProviderAdapter):
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        api_key = self.agent.resolved_api_key
        if not api_key:
            raise ProviderError(
                f"{self.agent.name} is missing API key env {self.agent.api_key_env}",
                retryable=True,
                error_type="configuration",
            )

        raw = _post_json_with_output_retry(
            url=_join_url(self.agent.base_url or "https://api.anthropic.com", "/v1/messages"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": self.agent.headers.get(
                    "anthropic-version", "2023-06-01"
                ),
                **{
                    key: value
                    for key, value in self.agent.headers.items()
                    if key.lower() != "anthropic-version"
                },
            },
            payload=self._payload(request),
            timeout=self.agent.timeout_seconds,
            debug=_provider_debug(request, self.agent),
            request=request,
            agent=self.agent,
        )
        return normalize_anthropic_result(raw, default_model=self.agent.model)

    def _payload(self, request: HubRequest) -> dict[str, Any]:
        raw = request.raw if isinstance(request.raw, dict) else {}
        payload = _copy_allowed(
            raw,
            {
                "metadata",
                "service_tier",
                "stop_sequences",
                "temperature",
                "thinking",
                "tool_choice",
                "tools",
                "top_k",
                "top_p",
            },
        )
        agent_tools = _request_tool_specs(request)
        if agent_tools:
            payload["tools"] = _anthropic_tool_specs(agent_tools)
            converted_choice = _anthropic_tool_choice(
                raw.get("tool_choice", raw.get("function_call"))
            )
            if converted_choice is not None:
                payload["tool_choice"] = converted_choice
        system_parts: list[str] = []
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            extra_context = _message_extra_context_text(message)
            if role in {"system", "developer"}:
                text = _append_extra_context(content_to_text(content), extra_context)
                if text:
                    system_parts.append(text)
            elif role == "assistant":
                assistant_content = _anthropic_assistant_content(message)
                if extra_context:
                    assistant_content = _anthropic_append_text_block(assistant_content, extra_context)
                messages.append({"role": "assistant", "content": assistant_content})
            elif role == "user":
                user_content = _anthropic_user_content(content)
                if extra_context:
                    user_content = _anthropic_append_text_block(user_content, extra_context)
                messages.append({"role": "user", "content": user_content})
            elif role == "tool":
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": str(
                                    message.get("tool_call_id")
                                    or message.get("tool_use_id")
                                    or message.get("name")
                                    or "call_0"
                                ),
                                "content": content_to_text(content),
                            }
                        ],
                    }
                )
        if not messages:
            messages.append({"role": "user", "content": ""})
        payload["model"] = self.agent.model
        payload["messages"] = messages
        payload["max_tokens"] = _required_provider_max_tokens(request, self.agent)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        elif "system" in raw:
            payload["system"] = raw["system"]
        return payload


AnthropicMessagesAdapter = AnthropicMessagesProvider


__all__ = ["AnthropicMessagesAdapter", "AnthropicMessagesProvider"]
