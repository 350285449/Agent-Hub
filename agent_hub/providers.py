from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from .config import AgentConfig
from .models import HubRequest, ProviderResult
from .payloads import content_to_text


FAILOVER_STATUSES = {401, 402, 403, 408, 409, 429}
FAILOVER_TEXT_MARKERS = (
    "rate limit",
    "rate_limit",
    "quota",
    "insufficient_quota",
    "billing",
    "credit",
    "capacity",
    "overloaded",
    "temporarily unavailable",
    "context length",
    "context_length",
    "too many tokens",
    "token limit",
    "maximum context",
)


@dataclass(slots=True)
class ProviderError(Exception):
    message: str
    status_code: int | None = None
    retryable: bool = True

    def __str__(self) -> str:
        return self.message


class Provider(Protocol):
    agent: AgentConfig

    def complete(self, request: HubRequest) -> ProviderResult:
        ...


class EchoProvider:
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


class OpenAIChatProvider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        api_key = self.agent.resolved_api_key
        if not api_key and self.agent.provider == "openai":
            raise ProviderError(
                f"{self.agent.name} is missing API key env {self.agent.api_key_env}",
                retryable=True,
            )

        payload = self._payload(request)
        headers = {
            "Content-Type": "application/json",
            **self.agent.headers,
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        raw = _post_json(
            url=_join_url(self.agent.base_url or "https://api.openai.com", "/v1/chat/completions"),
            headers=headers,
            payload=payload,
            timeout=self.agent.timeout_seconds,
        )
        choice = (raw.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return ProviderResult(
            text=content_to_text(message.get("content")),
            model=raw.get("model") or self.agent.model,
            raw=raw,
            usage=dict(raw.get("usage") or {}),
            finish_reason=choice.get("finish_reason"),
        )

    def _payload(self, request: HubRequest) -> dict[str, Any]:
        payload = _copy_allowed(
            request.raw,
            {
                "frequency_penalty",
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
        payload["model"] = self.agent.model
        payload["messages"] = request.messages
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


class AnthropicMessagesProvider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        api_key = self.agent.resolved_api_key
        if not api_key:
            raise ProviderError(
                f"{self.agent.name} is missing API key env {self.agent.api_key_env}",
                retryable=True,
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
        )
        return ProviderResult(
            text=content_to_text(raw.get("content")),
            model=raw.get("model") or self.agent.model,
            raw=raw,
            usage=dict(raw.get("usage") or {}),
            finish_reason=raw.get("stop_reason"),
        )

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
        system_parts: list[str] = []
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if role in {"system", "developer"}:
                text = content_to_text(content)
                if text:
                    system_parts.append(text)
            elif role in {"assistant", "user"}:
                messages.append({"role": role, "content": content})
            elif role == "tool":
                messages.append(
                    {
                        "role": "user",
                        "content": f"Tool result:\n{content_to_text(content)}",
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


def create_provider(agent: AgentConfig) -> Provider:
    provider = agent.provider.lower()
    if provider in {"openai", "openai-chat", "openai-compatible"}:
        return OpenAIChatProvider(agent)
    if provider in {"anthropic", "claude"}:
        return AnthropicMessagesProvider(agent)
    if provider == "echo":
        return EchoProvider(agent)
    raise ProviderError(f"Unsupported provider {agent.provider!r}", retryable=False)


def _post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise _provider_error_from_http(exc.code, text) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise ProviderError(f"Network error: {exc}", retryable=True) from exc
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Provider returned invalid JSON: {exc}", retryable=True) from exc


def _provider_error_from_http(status_code: int, text: str) -> ProviderError:
    message = _extract_error_message(text)
    marker_text = message.lower()
    retryable = (
        status_code in FAILOVER_STATUSES
        or status_code >= 500
        or any(marker in marker_text for marker in FAILOVER_TEXT_MARKERS)
    )
    return ProviderError(message, status_code=status_code, retryable=retryable)


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


def _copy_allowed(source: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: value for key, value in source.items() if key in allowed}


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _rough_tokens(request: HubRequest) -> int:
    return max(1, len("\n".join(content_to_text(m.get("content")) for m in request.messages)) // 4)
