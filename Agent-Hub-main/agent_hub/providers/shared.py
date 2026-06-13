from __future__ import annotations

import html
import json
import re
import socket
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlencode, urlparse
from typing import Any

from ..config import AgentConfig, normalize_provider
from ..models import HubRequest, ProviderResult
from ..payloads import content_to_text
from ..provider_presets import (
    chat_completions_path_for_agent,
    default_headers_for_agent,
    provider_kind_for_agent,
)
from ..response_normalization import (
    normalize_groq_openrouter_result,
    normalize_ollama_result,
    normalize_openai_compatible_result,
    normalize_openai_stream_data,
)
from .base import StreamChunk
from .errors import (
    ProviderError,
    classify_provider_error,
    extract_error_message,
    provider_error_category,
    provider_error_from_http,
    provider_error_from_payload,
    provider_user_message,
)
from .quota import metadata_cooldown_seconds, quota_metadata_from_headers
from .transport import (
    looks_like_timeout,
    post_json,
    post_stream_json,
    provider_request_id_from_headers,
)


_classify_provider_error = classify_provider_error
_extract_error_message = extract_error_message
_metadata_cooldown_seconds = metadata_cooldown_seconds
_post_json = post_json
_post_stream_json = post_stream_json
_provider_error_category = provider_error_category
_provider_error_from_http = provider_error_from_http
_provider_error_from_payload = provider_error_from_payload
_provider_request_id = provider_request_id_from_headers
_provider_user_message = provider_user_message
_quota_metadata_from_headers = quota_metadata_from_headers
_looks_like_timeout = looks_like_timeout


def _facade_callable(name: str, default: Any) -> Any:
    facade = sys.modules.get("agent_hub.providers")
    value = getattr(facade, name, None) if facade is not None else None
    return value if callable(value) and value is not default else default


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
        if item_type in {"tool_result", "function_call_output"}:
            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": str(
                        item.get("tool_use_id")
                        or item.get("tool_call_id")
                        or item.get("call_id")
                        or item.get("id")
                        or "call_0"
                    ),
                    "content": content_to_text(item.get("output", item.get("content"))),
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
        if not isinstance(item, dict) or item.get("type") not in {"tool_use", "function_call"}:
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
                        (
                            item.get("input")
                            if isinstance(item.get("input"), dict)
                            else _json_object(item.get("arguments"))
                        ),
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
        if item_type in {"tool_result", "function_call_output"}:
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": str(
                        item.get("tool_use_id")
                        or item.get("tool_call_id")
                        or item.get("call_id")
                        or item.get("id")
                        or "call_0"
                    ),
                    "content": content_to_text(item.get("output", item.get("content"))),
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
            if item_type in {"tool_use", "function_call"} and isinstance(item.get("name"), str):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(item.get("id") or f"toolu_{len(blocks)}"),
                        "name": item["name"],
                        "input": (
                            item.get("input")
                            if isinstance(item.get("input"), dict)
                            else _json_object(item.get("arguments"))
                        ),
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


def _gemini_tool_choice(value: Any) -> dict[str, Any] | None:
    mode = ""
    allowed: list[str] = []
    if isinstance(value, str):
        mode = value.strip().lower()
    elif isinstance(value, dict):
        choice_type = str(value.get("type") or "").lower()
        function = value.get("function") if isinstance(value.get("function"), dict) else value
        name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str) and name:
            mode = "required"
            allowed = [name]
        else:
            mode = choice_type
    mapped = {
        "any": "ANY",
        "required": "ANY",
        "auto": "AUTO",
        "none": "NONE",
    }.get(mode)
    if mapped is None:
        return None
    config: dict[str, Any] = {"mode": mapped}
    if allowed:
        config["allowedFunctionNames"] = allowed
    return {"functionCallingConfig": config}


def _gemini_message_parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    role = str(message.get("role") or "user")
    content = message.get("content")
    parts: list[dict[str, Any]] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                if isinstance(item, str):
                    parts.append({"text": item})
                continue
            item_type = item.get("type")
            if item_type in {"text", "input_text", "output_text"} and isinstance(item.get("text"), str):
                parts.append({"text": item["text"]})
            elif item_type in {"tool_use", "function_call"} and isinstance(item.get("name"), str):
                parts.append(
                    {
                        "functionCall": {
                            "name": item["name"],
                            "args": (
                                item.get("input")
                                if isinstance(item.get("input"), dict)
                                else _json_object(item.get("arguments"))
                            ),
                        }
                    }
                )
            elif item_type in {"tool_result", "function_call_output"}:
                parts.append(
                    _gemini_function_response(
                        name=str(item.get("name") or "tool"),
                        content=item.get("output", item.get("content")),
                    )
                )

    raw_calls = message.get("tool_calls")
    if isinstance(raw_calls, list):
        for call in raw_calls:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict) or not isinstance(function.get("name"), str):
                continue
            parts.append(
                {
                    "functionCall": {
                        "name": function["name"],
                        "args": _json_object(function.get("arguments")),
                    }
                }
            )
    function_call = message.get("function_call")
    if isinstance(function_call, dict) and isinstance(function_call.get("name"), str):
        parts.append(
            {
                "functionCall": {
                    "name": function_call["name"],
                    "args": _json_object(function_call.get("arguments")),
                }
            }
        )
    if role == "tool" and not any("functionResponse" in part for part in parts):
        parts.append(
            _gemini_function_response(
                name=str(message.get("name") or "tool"),
                content=content,
            )
        )
    if not parts:
        parts.append({"text": content_to_text(content)})
    extra_context = _message_extra_context_text(message)
    if extra_context:
        parts.append({"text": extra_context})
    return parts


def _gemini_function_response(*, name: str, content: Any) -> dict[str, Any]:
    return {
        "functionResponse": {
            "name": name,
            "response": {"output": content_to_text(content)},
        }
    }


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


def _post_json_with_output_retry(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    debug: dict[str, Any] | None,
    request: HubRequest,
    agent: AgentConfig,
) -> dict[str, Any]:
    """Retry once with a safer output budget when a provider rejects max tokens."""

    try:
        post = _facade_callable("_post_json", _post_json)
        return post(
            url=url,
            headers=headers,
            payload=payload,
            timeout=timeout,
            debug=debug,
        )
    except ProviderError as exc:
        if exc.error_type != "output_too_large" or not _request_auto_retry_enabled(request):
            raise
        retry_limit = _retry_output_token_limit(request, agent, exc)
        if retry_limit is None:
            raise
        retry_payload = _payload_with_output_token_limit(payload, retry_limit)
        post = _facade_callable("_post_json", _post_json)
        raw = post(
            url=url,
            headers=headers,
            payload=retry_payload,
            timeout=timeout,
            debug=debug,
        )
        if isinstance(raw, dict):
            provider_metadata = raw.setdefault("agent_hub_provider", {})
            if isinstance(provider_metadata, dict):
                limits = provider_metadata.setdefault("limits", {})
                if isinstance(limits, dict):
                    limits["max_output_tokens"] = retry_limit
                provider_metadata["output_token_retry"] = {
                    "original_error": str(exc)[:500],
                    "retry_max_tokens": retry_limit,
                }
        return raw


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
    get_url_text = _facade_callable("_get_url_text", _get_url_text)
    content_type, text = get_url_text(url, timeout=timeout, max_bytes=200_000)
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


def _search_with_duckduckgo_instant(query: str, limit: int, timeout: float) -> list[dict[str, str]]:
    url = "https://api.duckduckgo.com/?" + urlencode(
        {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }
    )
    get_url_text = _facade_callable("_get_url_text", _get_url_text)
    _content_type, text = get_url_text(url, timeout=timeout, max_bytes=300_000)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            "DuckDuckGo instant answer returned invalid JSON",
            retryable=True,
            error_type="invalid_provider_response",
        ) from exc
    hits: list[dict[str, str]] = []
    abstract_url = payload.get("AbstractURL") if isinstance(payload, dict) else None
    if isinstance(abstract_url, str) and abstract_url:
        hits.append(
            {
                "title": _clean_text(str(payload.get("Heading") or abstract_url)),
                "url": abstract_url,
                "snippet": _clean_text(str(payload.get("AbstractText") or "")),
            }
        )
    related = payload.get("RelatedTopics") if isinstance(payload, dict) else []
    for item in _flatten_related_topics(related):
        url_value = item.get("FirstURL")
        if not isinstance(url_value, str) or not url_value:
            continue
        host = (urlparse(url_value).hostname or "").lower()
        if "duckduckgo.com" in host:
            continue
        hits.append(
            {
                "title": _clean_text(str(item.get("Text") or url_value)).split(" - ", 1)[0],
                "url": url_value,
                "snippet": _clean_text(str(item.get("Text") or "")),
            }
        )
        if len(hits) >= limit:
            break
    return _dedupe_hits(hits)[:limit]


def _search_with_wikipedia(query: str, limit: int, timeout: float) -> list[dict[str, str]]:
    url = "https://en.wikipedia.org/w/api.php?" + urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "format": "json",
            "utf8": "1",
        }
    )
    get_url_text = _facade_callable("_get_url_text", _get_url_text)
    _content_type, text = get_url_text(url, timeout=timeout, max_bytes=300_000)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            "Wikipedia search returned invalid JSON",
            retryable=True,
            error_type="invalid_provider_response",
        ) from exc
    search = payload.get("query", {}).get("search", []) if isinstance(payload, dict) else []
    hits: list[dict[str, str]] = []
    for item in search if isinstance(search, list) else []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        title = _clean_text(str(item["title"]))
        hits.append(
            {
                "title": title,
                "url": "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="_()"),
                "snippet": _html_to_text(str(item.get("snippet") or "")),
            }
        )
    return hits[:limit]


def _flatten_related_topics(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("Topics"), list):
            rows.extend(_flatten_related_topics(item["Topics"]))
        else:
            rows.append(item)
    return rows


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
        raise ProviderError(
            f"Network error: {exc}",
            retryable=True,
            error_type="provider_unavailable",
        ) from exc

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
    raw = request.raw if isinstance(request.raw, dict) else {}
    try:
        value = int(raw.get(key, default))
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


def _copy_allowed(source: dict[str, Any] | Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    return {key: value for key, value in source.items() if key in allowed}


def _required_provider_max_tokens(request: HubRequest, agent: AgentConfig) -> int:
    explicit = _positive_int_or_none(request.max_tokens)
    if explicit is not None:
        return explicit
    configured = _positive_int_or_none(agent.max_tokens)
    if configured is not None:
        return configured
    if agent.context_window:
        return max(1, int(agent.context_window) - _rough_tokens(request))
    return 4096


def _request_auto_retry_enabled(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    value = hub.get("auto_retry", raw.get("auto_retry", True))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _retry_output_token_limit(
    request: HubRequest,
    agent: AgentConfig,
    error: ProviderError,
) -> int | None:
    current = _payload_requested_output_tokens(request)
    parsed = _limit_from_error_message(str(error))
    configured = _positive_int_or_none(agent.max_tokens)
    remaining = None
    if agent.context_window:
        remaining = max(1, int(agent.context_window) - _rough_tokens(request))
    for value in (parsed, configured, remaining, 4096):
        if not isinstance(value, int) or value <= 0:
            continue
        if current is not None and value >= current:
            continue
        return value
    return None


def _payload_requested_output_tokens(request: HubRequest) -> int | None:
    for value in (
        request.max_tokens,
        request.raw.get("max_completion_tokens") if isinstance(request.raw, dict) else None,
        request.raw.get("max_output_tokens") if isinstance(request.raw, dict) else None,
        request.raw.get("max_tokens") if isinstance(request.raw, dict) else None,
    ):
        parsed = _positive_int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _payload_with_output_token_limit(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    copied = dict(payload)
    if "generationConfig" in copied and isinstance(copied["generationConfig"], dict):
        generation_config = dict(copied["generationConfig"])
        generation_config["maxOutputTokens"] = limit
        copied["generationConfig"] = generation_config
        return copied
    if "max_completion_tokens" in copied:
        copied["max_completion_tokens"] = limit
        return copied
    copied["max_tokens"] = limit
    return copied


def _limit_from_error_message(message: str) -> int | None:
    lowered = message.lower()
    patterns = (
        r"(?:maximum|max|limit|up to|at most)[^\d]{0,40}(\d{2,7})",
        r"(\d{2,7})[^\d]{0,40}(?:maximum|max|limit|tokens)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, lowered):
            value = _positive_int_or_none(match.group(1))
            if value is not None and value >= 16:
                return value
    return None


def _positive_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _join_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        return f"{base}{path[3:]}"
    return f"{base}{path}"


def _rough_tokens(request: HubRequest) -> int:
    return max(1, len("\n".join(content_to_text(m.get("content")) for m in request.messages)) // 4)


