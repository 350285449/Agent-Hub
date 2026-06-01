from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..config import AgentConfig
from ..models import HubRequest, ProviderResult
from ..payloads import content_to_text
from ..response_normalization import normalize_gemini_result
from .base import BaseProviderAdapter
from .errors import ProviderError
from .shared import (
    _append_extra_context,
    _copy_allowed,
    _gemini_tool_specs,
    _join_url,
    _message_extra_context_text,
    _post_json_with_output_retry,
    _provider_debug,
    _request_tool_specs,
)

class GeminiProvider(BaseProviderAdapter):
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
            url=self._url(),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
                **self.agent.headers,
            },
            payload=self._payload(request),
            timeout=self.agent.timeout_seconds,
            debug=_provider_debug(request, self.agent),
            request=request,
            agent=self.agent,
        )
        return normalize_gemini_result(raw, default_model=self.agent.model)

    def _url(self) -> str:
        base_url = self.agent.base_url or "https://generativelanguage.googleapis.com"
        model = self.agent.model
        model_path = model if model.startswith("models/") else f"models/{model}"
        return _join_url(base_url, f"/v1beta/{quote(model_path, safe='/')}:generateContent")

    def _payload(self, request: HubRequest) -> dict[str, Any]:
        payload = _copy_allowed(
            request.raw,
            {
                "cachedContent",
                "safetySettings",
                "tools",
                "toolConfig",
            },
        )
        agent_tools = _request_tool_specs(request)
        if agent_tools:
            payload["tools"] = _gemini_tool_specs(agent_tools)
        generation_config = dict(
            request.raw.get("generationConfig")
            or request.raw.get("generation_config")
            or {}
        )
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for message in request.messages:
            role = message.get("role", "user")
            text = _append_extra_context(
                content_to_text(message.get("content")),
                _message_extra_context_text(message),
            )
            if role in {"system", "developer"}:
                if text:
                    system_parts.append(text)
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": text}]})
            elif role == "tool":
                contents.append({"role": "user", "parts": [{"text": f"Tool result:\n{text}"}]})
            else:
                contents.append({"role": "user", "parts": [{"text": text}]})

        if not contents:
            contents.append({"role": "user", "parts": [{"text": ""}]})

        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        max_tokens = request.max_tokens or self.agent.max_tokens
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens

        payload["contents"] = contents
        if generation_config:
            payload["generationConfig"] = generation_config
        if system_parts:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}],
            }
        return payload


GeminiAdapter = GeminiProvider


__all__ = ["GeminiAdapter", "GeminiProvider"]
