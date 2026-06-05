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
    _gemini_message_parts,
    _gemini_tool_choice,
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
            converted_choice = _gemini_tool_choice(
                request.raw.get("tool_choice", request.raw.get("function_call"))
            )
            if converted_choice is not None:
                payload["toolConfig"] = converted_choice
        generation_config = dict(
            request.raw.get("generationConfig")
            or request.raw.get("generation_config")
            or {}
        )
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        call_names: dict[str, str] = {}
        for original_message in request.messages:
            message = _message_with_tool_names(original_message, call_names)
            role = message.get("role", "user")
            if role in {"system", "developer"}:
                text = _append_extra_context(
                    content_to_text(message.get("content")),
                    _message_extra_context_text(message),
                )
                if text:
                    system_parts.append(text)
            elif role == "assistant":
                contents.append({"role": "model", "parts": _gemini_message_parts(message)})
            else:
                contents.append({"role": "user", "parts": _gemini_message_parts(message)})

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


def _message_with_tool_names(
    message: dict[str, Any],
    call_names: dict[str, str],
) -> dict[str, Any]:
    copied = dict(message)
    raw_calls = copied.get("tool_calls")
    if isinstance(raw_calls, list):
        for call in raw_calls:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict) or not isinstance(function.get("name"), str):
                continue
            call_names[str(call.get("id") or "call_0")] = function["name"]

    content = copied.get("content")
    if isinstance(content, list):
        next_content: list[Any] = []
        for item in content:
            if not isinstance(item, dict):
                next_content.append(item)
                continue
            block = dict(item)
            block_type = block.get("type")
            call_id = str(
                block.get("call_id")
                or block.get("tool_use_id")
                or block.get("id")
                or "call_0"
            )
            if block_type in {"tool_use", "function_call"} and isinstance(block.get("name"), str):
                call_names[call_id] = block["name"]
            elif block_type in {"tool_result", "function_call_output"} and not block.get("name"):
                block["name"] = call_names.get(call_id, "tool")
            next_content.append(block)
        copied["content"] = next_content

    if copied.get("role") == "tool" and not copied.get("name"):
        call_id = str(copied.get("tool_call_id") or copied.get("tool_use_id") or "call_0")
        copied["name"] = call_names.get(call_id, "tool")
    return copied


GeminiAdapter = GeminiProvider


__all__ = ["GeminiAdapter", "GeminiProvider"]
