from __future__ import annotations

import html
import json
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlencode, urlparse
from typing import Any, Iterator, Protocol

from ..config import AgentConfig, normalize_provider
from ..debug import log_provider_debug_event
from ..models import HubRequest, ProviderResult
from ..payloads import content_to_text
from ..provider_presets import (
    chat_completions_path_for_agent,
    default_headers_for_agent,
    provider_kind_for_agent,
)
from ..response_normalization import (
    normalize_anthropic_result,
    normalize_gemini_result,
    normalize_groq_openrouter_result,
    normalize_ollama_result,
    normalize_openai_compatible_result,
    normalize_openai_stream_data,
)
from .base import BaseProviderAdapter, ProviderAdapter, StreamChunk


FAILOVER_STATUSES = {401, 402, 403, 404, 408, 409, 429, 500, 502, 503}
QUOTA_TEXT_MARKERS = (
    "account limit",
    "billing",
    "credit",
    "credits exhausted",
    "daily limit",
    "exceeded your quota",
    "free quota",
    "free tier",
    "free-tier",
    "free usage",
    "insufficient balance",
    "insufficient_quota",
    "monthly limit",
    "payment required",
    "quota",
    "quota exceeded",
    "quotaexceeded",
    "resource exhausted",
    "resource_exhausted",
    "tokens exhausted",
    "usage limit",
)
RATE_LIMIT_TEXT_MARKERS = (
    "rate limit",
    "rate_limit",
    "rate-limit",
    "rate limited",
    "rate_limit_error",
    "rate_limit_exceeded",
    "requests per day",
    "requests per minute",
    "rpm",
    "too_many_requests",
    "tokens per minute",
    "tpm",
)
CONTEXT_LIMIT_TEXT_MARKERS = (
    "context length",
    "context_length",
    "context window",
    "input is too long",
    "maximum context",
    "max tokens",
    "too many tokens",
    "token limit",
)
TEMPORARY_TEXT_MARKERS = (
    "capacity",
    "overloaded",
    "temporarily overloaded",
    "temporarily unavailable",
    "try again later",
    "server error",
    "service unavailable",
)
AUTH_TEXT_MARKERS = (
    "api key",
    "authentication",
    "authorization",
    "invalid api key",
    "permission denied",
    "unauthorized",
)
FAILOVER_TEXT_MARKERS = (
    *QUOTA_TEXT_MARKERS,
    *RATE_LIMIT_TEXT_MARKERS,
    *CONTEXT_LIMIT_TEXT_MARKERS,
    *TEMPORARY_TEXT_MARKERS,
    *AUTH_TEXT_MARKERS,
)
RETRYABLE_ERROR_TYPES = {
    "quota_exhausted",
    "rate_limited",
    "context_limit",
    "temporary_unavailable",
    "authentication",
    "model_unavailable",
    "network",
    "timeout",
}


@dataclass(slots=True)
class ProviderError(Exception):
    message: str
    status_code: int | None = None
    retryable: bool = True
    error_type: str = "provider_error"
    cooldown_seconds: float | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.error_type == "provider_error":
            self.error_type = _classify_provider_error(self.message, status_code=self.status_code)

    def __str__(self) -> str:
        return self.message


class Provider(ProviderAdapter, Protocol):
    agent: AgentConfig

    def complete(self, request: HubRequest) -> ProviderResult:
        ...


class EchoProvider(BaseProviderAdapter):
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        last = ""
        for message in reversed(request.messages):
            if message.get("role") == "user":
                last = content_to_text(message.get("content"))
                break
        text = f"[{self.agent.name}] {last}".strip()
        return ProviderResult(
            text=text,
            model=self.agent.model,
            raw={"echo": True},
            usage={
                "input_tokens": _rough_tokens(request),
                "output_tokens": max(1, len(text) // 4),
            },
            finish_reason="stop",
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

        raw = _post_json(
            url=_chat_completions_url(self.agent),
            headers=headers,
            payload=payload,
            timeout=self.agent.timeout_seconds,
            debug=_provider_debug(request, self.agent),
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
        for data in _post_stream_json(
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


class LocalResearchProvider(BaseProviderAdapter):
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        query = _research_query(request)
        if not query:
            text = "Local research needs a question or topic to search for."
            return ProviderResult(
                text=text,
                model=self.agent.model,
                raw={"local_research": True, "query": query},
                usage={"input_tokens": _rough_tokens(request), "output_tokens": len(text) // 4},
                finish_reason="stop",
            )

        max_sources = _request_int(request, "max_sources", default=5, minimum=1, maximum=10)
        try:
            hits = self._search(query, max_sources=max_sources)
        except ProviderError as exc:
            text = (
                "Local research could not reach public web search from this machine.\n\n"
                f"Reason: {exc}"
            )
            return ProviderResult(
                text=text,
                model=self.agent.model,
                raw={"local_research": True, "query": query, "error": str(exc)},
                usage={"input_tokens": _rough_tokens(request), "output_tokens": len(text) // 4},
                finish_reason="stop",
            )

        documents: list[dict[str, Any]] = []
        for hit in hits[:max_sources]:
            text = self._fetch(hit["url"])
            snippet = _best_snippet(query, text) if text else hit.get("snippet", "")
            if not snippet:
                continue
            documents.append(
                {
                    "title": hit.get("title") or hit["url"],
                    "url": hit["url"],
                    "snippet": snippet,
                }
            )

        if not documents:
            documents = [
                {
                    "title": hit.get("title") or hit["url"],
                    "url": hit["url"],
                    "snippet": hit.get("snippet", ""),
                }
                for hit in hits[:max_sources]
                if hit.get("url")
            ]

        answer = _research_answer(query, documents)
        return ProviderResult(
            text=answer,
            model=self.agent.model,
            raw={
                "local_research": True,
                "query": query,
                "source_count": len(documents),
            },
            usage={
                "input_tokens": _rough_tokens(request),
                "output_tokens": max(1, len(answer) // 4),
            },
            finish_reason="stop",
            citations=[doc["url"] for doc in documents if doc.get("url")],
            search_results=documents,
        )

    def _search(self, query: str, max_sources: int) -> list[dict[str, str]]:
        direct_hits = [{"title": url, "url": url, "snippet": ""} for url in _urls_in_text(query)]
        web_hits = _search_with_duckduckgo(
            query=query,
            limit=max_sources,
            timeout=self.agent.timeout_seconds,
        )
        return _dedupe_hits([*direct_hits, *web_hits])[:max_sources]

    def _fetch(self, url: str) -> str:
        try:
            content_type, text = _get_url_text(
                url,
                timeout=self.agent.timeout_seconds,
                max_bytes=250_000,
            )
        except ProviderError:
            return ""
        if "html" in content_type:
            return _html_to_text(text)
        return _clean_text(text)


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

        raw = _post_json(
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
        )
        return normalize_anthropic_result(raw, default_model=self.agent.model)

    def _payload(self, request: HubRequest) -> dict[str, Any]:
        payload = _copy_allowed(
            request.raw,
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
                request.raw.get("tool_choice", request.raw.get("function_call"))
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
        payload["max_tokens"] = request.max_tokens or self.agent.max_tokens or 4096
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        elif "system" in request.raw:
            payload["system"] = request.raw["system"]
        return payload


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

        raw = _post_json(
            url=self._url(),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
                **self.agent.headers,
            },
            payload=self._payload(request),
            timeout=self.agent.timeout_seconds,
            debug=_provider_debug(request, self.agent),
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


def _agent_hub_tool_specs(request: HubRequest) -> list[dict[str, Any]]:
    tools = request.raw.get("agent_hub_tools") if isinstance(request.raw, dict) else None
    if not isinstance(tools, list):
        return []
    specs: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        parameters = tool.get("parameters")
        if isinstance(name, str) and isinstance(parameters, dict):
            specs.append(
                {
                    "name": name,
                    "description": str(tool.get("description") or ""),
                    "parameters": parameters,
                }
            )
    return specs


def _request_tool_specs(request: HubRequest) -> list[dict[str, Any]]:
    return _agent_hub_tool_specs(request) or _openai_request_tool_specs(request)


def _openai_request_tool_specs(request: HubRequest) -> list[dict[str, Any]]:
    tools = request.raw.get("tools") if isinstance(request.raw, dict) else None
    specs: list[dict[str, Any]] = []
    if isinstance(tools, list):
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function") if tool.get("type") == "function" else tool
            spec = _tool_spec_from_function(function)
            if spec:
                specs.append(spec)
    functions = request.raw.get("functions") if isinstance(request.raw, dict) else None
    if isinstance(functions, list):
        for function in functions:
            spec = _tool_spec_from_function(function)
            if spec:
                specs.append(spec)
    return specs


def _tool_spec_from_function(function: Any) -> dict[str, Any] | None:
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    parameters = (
        function.get("parameters")
        or function.get("input_schema")
        or {"type": "object", "properties": {}}
    )
    if isinstance(name, str) and isinstance(parameters, dict):
        return {
            "name": name,
            "description": str(function.get("description") or ""),
            "parameters": parameters,
        }
    return None


MESSAGE_CONTEXT_KEYS = (
    "task_progress",
    "todo",
    "todos",
    "todo_list",
    "active_file",
    "active_files",
    "open_files",
    "open_tabs",
    "workspace_metadata",
    "workspace_state",
    "mcp_state",
    "tool_state",
)


def _message_extra_context_text(message: dict[str, Any]) -> str:
    extras = {
        key: message[key]
        for key in MESSAGE_CONTEXT_KEYS
        if key in message and message[key] not in (None, "", [], {})
    }
    if not extras:
        return ""
    return "Protected client context:\n" + json.dumps(
        extras,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _append_extra_context(text: Any, extra_context: str) -> str:
    base = content_to_text(text)
    if not extra_context:
        return base
    return "\n\n".join(part for part in (base, extra_context) if part)


def _anthropic_append_text_block(content: Any, text: str) -> Any:
    if not text:
        return content
    block = {"type": "text", "text": text}
    if isinstance(content, list):
        return [*content, block]
    existing = content_to_text(content)
    return [block] if not existing else [{"type": "text", "text": existing}, block]


def _openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        extra_context = _message_extra_context_text(message)
        if role == "assistant":
            tool_calls = _openai_tool_calls_from_message(message)
            text = content_to_text(content)
            text = _append_extra_context(text, extra_context)
            item: dict[str, Any] = {
                "role": "assistant",
                "content": None if tool_calls and not text else text,
            }
            if tool_calls:
                item["tool_calls"] = tool_calls
            function_call = message.get("function_call")
            if isinstance(function_call, dict):
                item["function_call"] = function_call
            normalized.append(item)
            continue
        if role == "tool":
            normalized.append(
                {
                    "role": "tool",
                    "tool_call_id": str(
                        message.get("tool_call_id")
                        or message.get("tool_use_id")
                        or message.get("name")
                        or "call_0"
                    ),
                    "content": content_to_text(content),
                }
            )
            continue
        if role == "user":
            text, tool_results = _openai_user_parts_from_anthropic(content)
            if not text and not tool_results:
                text = content_to_text(content)
            text = _append_extra_context(text, extra_context)
            for result in tool_results:
                normalized.append(result)
            if text:
                normalized.append({"role": "user", "content": text})
            if text or tool_results:
                continue
        if extra_context:
            normalized.append({"role": role, "content": _append_extra_context(content_to_text(content), extra_context)})
        else:
            normalized.append({"role": role, "content": content})
    return normalized


def _openai_user_parts_from_anthropic(content: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(content, list):
        return "", []
    text_parts: list[str] = []
    tool_results: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "tool_result":
            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": str(
                        item.get("tool_use_id")
                        or item.get("tool_call_id")
                        or item.get("id")
                        or "call_0"
                    ),
                    "content": content_to_text(item.get("content")),
                }
            )
        elif item_type in {"text", "input_text"}:
            text = item.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    return "\n".join(part for part in text_parts if part), tool_results


def _openai_tool_calls_from_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw_calls = message.get("tool_calls")
    if isinstance(raw_calls, list) and raw_calls:
        return [call for call in raw_calls if isinstance(call, dict)]
    content = message.get("content")
    if not isinstance(content, list):
        return []
    calls: list[dict[str, Any]] = []
    for index, item in enumerate(content):
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        calls.append(
            {
                "id": str(item.get("id") or f"call_{index}"),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(
                        item.get("input") if isinstance(item.get("input"), dict) else {},
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                },
            }
        )
    return calls


def _anthropic_user_content(content: Any) -> Any:
    if not isinstance(content, list):
        return content
    blocks: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "tool_result":
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": str(
                        item.get("tool_use_id")
                        or item.get("tool_call_id")
                        or item.get("id")
                        or "call_0"
                    ),
                    "content": content_to_text(item.get("content")),
                }
            )
        elif item_type in {"text", "input_text"} and isinstance(item.get("text"), str):
            blocks.append({"type": "text", "text": item["text"]})
    return blocks if blocks else content_to_text(content)


def _anthropic_assistant_content(message: dict[str, Any]) -> Any:
    content = message.get("content", "")
    blocks: list[dict[str, Any]] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "tool_use" and isinstance(item.get("name"), str):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(item.get("id") or f"toolu_{len(blocks)}"),
                        "name": item["name"],
                        "input": item.get("input") if isinstance(item.get("input"), dict) else {},
                    }
                )
            elif item_type in {"text", "output_text"} and isinstance(item.get("text"), str):
                blocks.append({"type": "text", "text": item["text"]})
    else:
        text = content_to_text(content)
        if text:
            blocks.append({"type": "text", "text": text})

    raw_tool_calls = message.get("tool_calls")
    tool_calls = raw_tool_calls if isinstance(raw_tool_calls, list) else []
    for call in tool_calls:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            continue
        blocks.append(
            {
                "type": "tool_use",
                "id": str(call.get("id") or f"toolu_{len(blocks)}"),
                "name": function["name"],
                "input": _json_object(function.get("arguments")),
            }
        )

    function_call = message.get("function_call")
    if isinstance(function_call, dict) and isinstance(function_call.get("name"), str):
        blocks.append(
            {
                "type": "tool_use",
                "id": "function_call",
                "name": function_call["name"],
                "input": _json_object(function_call.get("arguments")),
            }
        )
    return blocks if blocks else ""


def _openai_tool_choice(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.lower()
        if lowered == "any":
            return "required"
        if lowered in {"auto", "none", "required"}:
            return lowered
    if not isinstance(value, dict):
        return None
    choice_type = value.get("type")
    if choice_type == "tool" and isinstance(value.get("name"), str):
        return {"type": "function", "function": {"name": value["name"]}}
    if choice_type == "function" and isinstance(value.get("function"), dict):
        return value
    if isinstance(value.get("name"), str):
        return {"type": "function", "function": {"name": value["name"]}}
    if choice_type in {"auto", "none", "required"}:
        return choice_type
    if choice_type == "any":
        return "required"
    return None


def _anthropic_tool_choice(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.lower()
        if lowered == "required":
            return {"type": "any"}
        if lowered in {"auto", "none", "any"}:
            return {"type": lowered}
    if not isinstance(value, dict):
        return None
    choice_type = value.get("type")
    if choice_type == "function":
        function = value.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            return {"type": "tool", "name": function["name"]}
    if choice_type == "tool" and isinstance(value.get("name"), str):
        return {"type": "tool", "name": value["name"]}
    if isinstance(value.get("name"), str):
        return {"type": "tool", "name": value["name"]}
    if choice_type in {"auto", "none", "any"}:
        return {"type": choice_type}
    return None


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _openai_tool_specs(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool["parameters"],
            },
        }
        for tool in tools
    ]


def _anthropic_tool_specs(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": tool["parameters"],
        }
        for tool in tools
    ]


def _gemini_tool_specs(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "functionDeclarations": [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": _gemini_schema(tool["parameters"]),
                }
                for tool in tools
            ]
        }
    ]


def _gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            converted[key] = value.upper()
        elif key == "properties" and isinstance(value, dict):
            converted[key] = {
                str(name): _gemini_schema(prop)
                for name, prop in value.items()
                if isinstance(prop, dict)
            }
        elif key == "items" and isinstance(value, dict):
            converted[key] = _gemini_schema(value)
        elif key in {"required", "description", "enum", "nullable"}:
            converted[key] = value
    return converted


def create_provider(agent: AgentConfig) -> Provider:
    provider = normalize_provider(agent.provider)
    provider_type = (agent.provider_type or agent.provider).lower()
    if provider_type in {"ollama", "ollama-local"}:
        from .ollama import OllamaProvider

        return OllamaProvider(agent)
    if provider_type == "groq":
        from .groq import GroqProvider

        return GroqProvider(agent)
    if provider_type == "openrouter":
        from .openrouter import OpenRouterProvider

        return OpenRouterProvider(agent)
    if provider in {"openai", "openai-compatible"}:
        return OpenAIChatProvider(agent)
    if provider == "local-research":
        return LocalResearchProvider(agent)
    if provider == "anthropic":
        return AnthropicMessagesProvider(agent)
    if provider == "gemini":
        return GeminiProvider(agent)
    if provider == "echo":
        return EchoProvider(agent)
    raise ProviderError(
        f"Unsupported provider {agent.provider!r}",
        retryable=False,
        error_type="configuration",
    )


def provider_headers(agent: AgentConfig, api_key: str | None = None) -> dict[str, str]:
    """Build request headers with provider-specific defaults and user overrides."""

    headers = {
        "Content-Type": "application/json",
        **default_headers_for_agent(agent),
        **agent.headers,
    }
    if api_key and not _has_auth_header(headers):
        headers["Authorization"] = f"Bearer {api_key}"
    kind = provider_kind_for_agent(agent)
    if kind == "github-models":
        headers.setdefault("Accept", "application/vnd.github+json")
    return headers


def _has_auth_header(headers: dict[str, str]) -> bool:
    return any(key.lower() in {"authorization", "x-api-key", "api-key"} for key in headers)


def _chat_completions_url(agent: AgentConfig) -> str:
    base_url = agent.base_url or "https://api.openai.com"
    return _join_url(base_url, chat_completions_path_for_agent(agent))


def _provider_debug(request: HubRequest, agent: AgentConfig) -> dict[str, Any] | None:
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    debug = metadata.get("agent_hub_debug")
    if not isinstance(debug, dict):
        return None
    context = dict(debug)
    context.setdefault("provider", agent.provider)
    context.setdefault("provider_name", agent.provider_type or agent.provider)
    context.setdefault("model", agent.model)
    return context


def _normalize_chat_result_for_agent(raw: dict[str, Any], agent: AgentConfig) -> ProviderResult:
    provider_type = (agent.provider_type or agent.provider or "").lower()
    provider_kind = provider_kind_for_agent(agent)
    if provider_kind.startswith("ollama") or provider_type in {"ollama", "ollama-cloud"}:
        return normalize_ollama_result(raw, default_model=agent.model)
    if provider_kind in {"groq", "openrouter"} or provider_type in {"groq", "openrouter"}:
        return normalize_groq_openrouter_result(
            raw,
            default_model=agent.model,
            provider_name=provider_kind or provider_type,
        )
    return normalize_openai_compatible_result(
        raw,
        default_model=agent.model,
        provider_name=provider_kind or provider_type or "openai-compatible",
    )


def _post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    log_provider_debug_event(
        debug,
        {
            "type": "provider_request",
            "url": url,
            "payload": payload,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_headers = dict(response.headers.items())
            provider_request_id = _provider_request_id(response_headers)
            text = response.read().decode("utf-8")
            log_provider_debug_event(
                debug,
                {
                    "type": "raw_provider_response",
                    "provider_request_id": provider_request_id,
                    "status": response.status,
                    "headers": response_headers,
                    "raw_json": text,
                    "empty_response": not bool(text.strip()),
                },
            )
            data = json.loads(text) if text else {}
            metadata = _quota_metadata_from_headers(dict(response.headers.items()))
            if isinstance(data, dict) and data.get("error"):
                raise _provider_error_from_payload(
                    data,
                    status_code=response.status,
                    metadata=metadata,
                )
            if isinstance(data, dict) and metadata:
                provider_metadata = data.setdefault("agent_hub_provider", {})
                if isinstance(provider_metadata, dict):
                    provider_metadata["quota"] = metadata
            return data
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        log_provider_debug_event(
            debug,
            {
                "type": "provider_http_error",
                "status": exc.code,
                "headers": dict(exc.headers.items()) if exc.headers else {},
                "raw_json": text,
            },
        )
        raise _provider_error_from_http(
            exc.code,
            text,
            headers=dict(exc.headers.items()) if exc.headers else None,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ProviderError(f"Provider request timed out: {exc}", retryable=True, error_type="timeout") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        error_type = "timeout" if _looks_like_timeout(reason) else "network"
        prefix = "Provider request timed out" if error_type == "timeout" else "Network error"
        raise ProviderError(f"{prefix}: {reason}", retryable=True, error_type=error_type) from exc
    except json.JSONDecodeError as exc:
        log_provider_debug_event(
            debug,
            {
                "type": "malformed_provider_json",
                "message": str(exc),
            },
        )
        raise ProviderError(
            f"Provider returned invalid JSON: {exc}",
            retryable=True,
            error_type="invalid_provider_response",
        ) from exc


def _post_stream_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    debug: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    log_provider_debug_event(
        debug,
        {
            "type": "provider_stream_request",
            "url": url,
            "payload": payload,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_headers = dict(response.headers.items())
            provider_request_id = _provider_request_id(response_headers)
            metadata = _quota_metadata_from_headers(response_headers)
            saw_done = False
            yielded = 0
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                log_provider_debug_event(
                    debug,
                    {
                        "type": "raw_stream_chunk",
                        "provider_request_id": provider_request_id,
                        "chunk": line,
                        "empty_chunk": not bool(line),
                    },
                )
                if not line or line.startswith(":") or line.startswith("event:"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    saw_done = True
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    log_provider_debug_event(
                        debug,
                        {
                            "type": "malformed_stream_chunk",
                            "provider_request_id": provider_request_id,
                            "message": str(exc),
                            "chunk": line,
                        },
                    )
                    continue
                if not isinstance(data, dict):
                    log_provider_debug_event(
                        debug,
                        {
                            "type": "malformed_stream_chunk",
                            "provider_request_id": provider_request_id,
                            "message": "Provider returned a non-object stream chunk",
                            "chunk": data,
                        },
                    )
                    continue
                if isinstance(data, dict) and data.get("error"):
                    raise _provider_error_from_payload(
                        data,
                        status_code=response.status,
                        metadata=metadata,
                    )
                if metadata:
                    provider_metadata = data.setdefault("agent_hub_provider", {})
                    if isinstance(provider_metadata, dict):
                        provider_metadata["quota"] = metadata
                yielded += 1
                yield data
            if not saw_done:
                log_provider_debug_event(
                    debug,
                    {
                        "type": "stream_missing_done",
                        "provider_request_id": provider_request_id,
                        "yielded_chunks": yielded,
                    },
                )
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        log_provider_debug_event(
            debug,
            {
                "type": "provider_stream_http_error",
                "status": exc.code,
                "headers": dict(exc.headers.items()) if exc.headers else {},
                "raw_json": text,
            },
        )
        raise _provider_error_from_http(
            exc.code,
            text,
            headers=dict(exc.headers.items()) if exc.headers else None,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ProviderError(f"Provider stream timed out: {exc}", retryable=True, error_type="timeout") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        error_type = "timeout" if _looks_like_timeout(reason) else "network"
        prefix = "Provider stream timed out" if error_type == "timeout" else "Network error"
        raise ProviderError(f"{prefix}: {reason}", retryable=True, error_type=error_type) from exc


def _stream_chunk_from_openai_data(
    data: dict[str, Any],
    *,
    default_model: str,
) -> StreamChunk | None:
    normalized = normalize_openai_stream_data(data, default_model=default_model)
    if normalized is None:
        return None
    return StreamChunk(
        text=str(normalized.get("text") or ""),
        delta=dict(normalized.get("delta") or {}),
        model=str(normalized.get("model") or default_model),
        finish_reason=(
            str(normalized["finish_reason"])
            if normalized.get("finish_reason") is not None
            else None
        ),
        raw=dict(normalized.get("raw") or data),
    )


def _stream_delta_text(delta: dict[str, Any]) -> str:
    content = delta.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return content_to_text(content)
    return ""


def _provider_error_from_http(
    status_code: int,
    text: str,
    headers: dict[str, str] | None = None,
) -> ProviderError:
    message = _extract_error_message(text)
    error_type = _classify_provider_error(message, status_code=status_code)
    retryable = (
        status_code in FAILOVER_STATUSES
        or status_code >= 500
        or error_type in RETRYABLE_ERROR_TYPES
    )
    metadata = _quota_metadata_from_headers(headers or {})
    return ProviderError(
        message,
        status_code=status_code,
        retryable=retryable,
        error_type=error_type,
        cooldown_seconds=_metadata_cooldown_seconds(metadata),
        metadata=metadata,
    )


def _provider_request_id(headers: dict[str, str]) -> str | None:
    lower = {str(key).lower(): str(value) for key, value in headers.items() if value is not None}
    for name in (
        "x-request-id",
        "request-id",
        "x-amzn-requestid",
        "x-goog-request-id",
        "cf-ray",
    ):
        value = lower.get(name)
        if value:
            return value
    return None


def _provider_error_from_payload(
    data: dict[str, Any],
    status_code: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> ProviderError:
    message = _extract_error_message(json.dumps(data))
    error_type = _classify_provider_error(message, status_code=status_code)
    retryable = (
        status_code in FAILOVER_STATUSES
        or (status_code is not None and status_code >= 500)
        or error_type in RETRYABLE_ERROR_TYPES
    )
    return ProviderError(
        message,
        status_code=status_code,
        retryable=retryable,
        error_type=error_type,
        cooldown_seconds=_metadata_cooldown_seconds(metadata or {}),
        metadata=metadata or {},
    )


def _classify_provider_error(message: str, status_code: int | None = None) -> str:
    marker_text = message.lower().replace("-", " ")
    if any(marker in marker_text for marker in QUOTA_TEXT_MARKERS):
        return "quota_exhausted"
    if status_code == 429 or any(marker in marker_text for marker in RATE_LIMIT_TEXT_MARKERS):
        return "rate_limited"
    if any(marker in marker_text for marker in CONTEXT_LIMIT_TEXT_MARKERS):
        return "context_limit"
    if status_code in {401, 403} or any(marker in marker_text for marker in AUTH_TEXT_MARKERS):
        return "authentication"
    if status_code in {408, 409, 500, 502, 503} or any(
        marker in marker_text for marker in TEMPORARY_TEXT_MARKERS
    ):
        return "temporary_unavailable"
    if status_code == 404:
        return "model_unavailable"
    return "provider_error"


def _extract_error_message(text: str) -> str:
    if not text:
        return "Provider request failed"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text[:500]
    error = data.get("error")
    if isinstance(error, dict):
        for key in ("message", "type", "code"):
            if error.get(key):
                return str(error[key])
    if isinstance(error, str):
        return error
    return text[:500]


def _quota_metadata_from_headers(headers: dict[str, str]) -> dict[str, Any]:
    """Normalize common provider quota/rate-limit headers into router metadata."""

    if not headers:
        return {}
    lower = {str(key).lower(): str(value) for key, value in headers.items() if value is not None}
    metadata: dict[str, Any] = {}

    requests_remaining = _first_number(
        lower,
        (
            "x-ratelimit-remaining-requests",
            "x-rate-limit-remaining-requests",
            "anthropic-ratelimit-requests-remaining",
            "x-request-limit-remaining",
            "ratelimit-remaining",
            "x-ratelimit-remaining",
        ),
        integer=True,
    )
    if requests_remaining is not None:
        metadata["requests_remaining"] = int(requests_remaining)
        metadata["quota_remaining"] = int(requests_remaining)

    tokens_remaining = _first_number(
        lower,
        (
            "x-ratelimit-remaining-tokens",
            "x-rate-limit-remaining-tokens",
            "anthropic-ratelimit-tokens-remaining",
            "x-token-limit-remaining",
        ),
        integer=True,
    )
    if tokens_remaining is not None:
        metadata["tokens_remaining"] = int(tokens_remaining)

    credits_remaining = _first_number(
        lower,
        (
            "x-ratelimit-remaining-credits",
            "x-credits-remaining",
            "x-credit-balance",
            "x-openrouter-credits-remaining",
        ),
    )
    if credits_remaining is not None:
        metadata["credits_remaining"] = credits_remaining
        metadata["quota_remaining"] = credits_remaining

    reset_at = _first_reset_timestamp(
        lower,
        (
            "x-ratelimit-reset",
            "x-ratelimit-reset-requests",
            "x-rate-limit-reset",
            "anthropic-ratelimit-requests-reset",
            "ratelimit-reset",
        ),
    )
    if reset_at is not None:
        metadata["rate_limit_reset_at"] = reset_at

    retry_after = _parse_retry_after(lower.get("retry-after"))
    if retry_after is not None:
        metadata["cooldown_seconds"] = retry_after
        metadata["cooldown_until"] = time.time() + retry_after

    return metadata


def _metadata_cooldown_seconds(metadata: dict[str, Any]) -> float | None:
    value = metadata.get("cooldown_seconds")
    if value is not None:
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None
    cooldown_until = metadata.get("cooldown_until")
    if cooldown_until is not None:
        try:
            return max(0.0, float(cooldown_until) - time.time())
        except (TypeError, ValueError):
            return None
    return None


def _first_number(
    headers: dict[str, str],
    names: tuple[str, ...],
    *,
    integer: bool = False,
) -> float | int | None:
    for name in names:
        if name not in headers:
            continue
        match = re.search(r"-?\d+(?:\.\d+)?", headers[name])
        if not match:
            continue
        try:
            value = float(match.group(0))
        except ValueError:
            continue
        return int(value) if integer else value
    return None


def _first_reset_timestamp(headers: dict[str, str], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = headers.get(name)
        parsed = _parse_reset_timestamp(value)
        if parsed is not None:
            return parsed
    return None


def _parse_reset_timestamp(value: str | None) -> float | None:
    if not value:
        return None
    stripped = value.strip()
    number_match = re.fullmatch(r"\d+(?:\.\d+)?", stripped)
    if number_match:
        try:
            number = float(number_match.group(0))
        except ValueError:
            number = 0.0
        if number > 1_000_000_000:
            return number / 1000.0 if number > 10_000_000_000 else number
        if number >= 0:
            return time.time() + number
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError, OverflowError):
        loose_match = re.search(r"\d+(?:\.\d+)?", stripped)
        if not loose_match:
            return None
        try:
            return time.time() + max(0.0, float(loose_match.group(0)))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.timestamp()
    return parsed.timestamp()


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    stripped = value.strip()
    try:
        return max(0.0, float(stripped))
    except ValueError:
        timestamp = _parse_reset_timestamp(stripped)
        if timestamp is None:
            return None
        return max(0.0, timestamp - time.time())


def _looks_like_timeout(reason: object) -> bool:
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return True
    return "timed out" in str(reason).lower() or "timeout" in str(reason).lower()


def _research_query(request: HubRequest) -> str:
    raw_query = request.raw.get("query") if isinstance(request.raw, dict) else None
    if isinstance(raw_query, str) and raw_query.strip():
        return _clean_text(raw_query)
    if request.task:
        return _last_question_line(content_to_text(request.task))
    for message in reversed(request.messages):
        if message.get("role") == "user":
            return _last_question_line(content_to_text(message.get("content")))
    return ""


def _last_question_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    if len(lines) > 1 and any(
        lines[0].lower().startswith(prefix)
        for prefix in ("answer this", "research", "use current", "cite")
    ):
        return lines[-1]
    return _clean_text(text)


def _search_with_duckduckgo(query: str, limit: int, timeout: float) -> list[dict[str, str]]:
    url = "https://duckduckgo.com/html/?" + urlencode({"q": query})
    content_type, text = _get_url_text(url, timeout=timeout, max_bytes=200_000)
    if "html" not in content_type:
        raise ProviderError(
            "Search returned a non-HTML response",
            retryable=True,
            error_type="invalid_provider_response",
        )

    parser = _LinkExtractor()
    parser.feed(text)
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in parser.links:
        href = _normalize_result_url(link["href"])
        title = _clean_text(link["text"])
        if not href or href in seen or not title:
            continue
        host = (urlparse(href).hostname or "").lower()
        if "duckduckgo.com" in host:
            continue
        seen.add(href)
        hits.append({"title": title, "url": href, "snippet": ""})
        if len(hits) >= limit:
            break
    return hits


def _get_url_text(url: str, timeout: float, max_bytes: int) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Agent-Hub local research/0.1 (+https://localhost)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.2",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "text/plain")
            body = response.read(max_bytes + 1)[:max_bytes]
    except urllib.error.HTTPError as exc:
        raise _provider_error_from_http(
            exc.code,
            exc.read().decode("utf-8", errors="replace"),
        ) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise ProviderError(f"Network error: {exc}", retryable=True, error_type="network") from exc

    charset = _charset_from_content_type(content_type) or "utf-8"
    return content_type.lower(), body.decode(charset, errors="replace")


def _charset_from_content_type(content_type: str) -> str | None:
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip("\"'") if match else None


def _normalize_result_url(href: str) -> str:
    if not href:
        return ""
    value = html.unescape(href)
    if value.startswith("//"):
        value = "https:" + value
    if value.startswith("/"):
        value = "https://duckduckgo.com" + value
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    uddg = query.get("uddg")
    if uddg and uddg[0]:
        return uddg[0]
    if parsed.scheme in {"http", "https"}:
        return value
    return ""


def _urls_in_text(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s<>\]\)\"']+", text)
    return [url.rstrip(".,;:") for url in urls]


def _dedupe_hits(hits: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for hit in hits:
        url = hit.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(hit)
    return deduped


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return _clean_text(" ".join(parser.parts))


def _best_snippet(query: str, text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    keywords = _keywords(query)
    sentences = _sentences(cleaned)
    if not sentences:
        return cleaned[:500]

    best_score = -1
    best_index = 0
    for index, sentence in enumerate(sentences[:120]):
        lowered = sentence.lower()
        score = sum(lowered.count(keyword) for keyword in keywords)
        if score > best_score:
            best_score = score
            best_index = index

    snippet = " ".join(sentences[best_index : best_index + 2])
    if not snippet or best_score <= 0:
        snippet = " ".join(sentences[:2])
    return snippet[:700].strip()


def _research_answer(query: str, documents: list[dict[str, Any]]) -> str:
    if not documents:
        return (
            f"Local research for: {query}\n\n"
            "I could not find usable source pages. Try a more specific query or include direct URLs."
        )

    lines = [
        f"Local research for: {query}",
        "",
        "Summary:",
    ]
    for index, document in enumerate(documents, start=1):
        snippet = _clean_text(str(document.get("snippet", "")))
        if snippet:
            lines.append(f"- {snippet} [{index}]")

    lines.extend(["", "Sources:"])
    for index, document in enumerate(documents, start=1):
        title = _clean_text(str(document.get("title") or document.get("url")))
        url = document.get("url", "")
        lines.append(f"[{index}] {title} - {url}")
    return "\n".join(lines)


def _keywords(text: str) -> list[str]:
    stopwords = {
        "about",
        "after",
        "from",
        "have",
        "into",
        "latest",
        "search",
        "sources",
        "that",
        "their",
        "this",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
    words = re.findall(r"[a-z0-9][a-z0-9-]{2,}", text.lower())
    return [word for word in words if word not in stopwords][:20]


def _sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+", text)
    return [_clean_text(chunk) for chunk in chunks if len(_clean_text(chunk)) > 40]


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _request_int(
    request: HubRequest,
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(request.raw.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href")
        if href:
            self._href = href
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._href:
            return
        self.links.append({"href": self._href, "text": " ".join(self._parts)})
        self._href = None
        self._parts = []


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data)


def _copy_allowed(source: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: value for key, value in source.items() if key in allowed}


def _join_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        return f"{base}{path[3:]}"
    return f"{base}{path}"


def _rough_tokens(request: HubRequest) -> int:
    return max(1, len("\n".join(content_to_text(m.get("content")) for m in request.messages)) // 4)
