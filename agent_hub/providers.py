from __future__ import annotations

import html
import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlencode, urlparse
from typing import Any, Protocol

from .config import AgentConfig, normalize_provider
from .models import HubRequest, ProviderResult
from .payloads import content_to_text


FAILOVER_STATUSES = {401, 402, 403, 404, 408, 409, 429}
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
        if not api_key and normalize_provider(self.agent.provider) == "openai":
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


class LocalResearchProvider:
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


class GeminiProvider:
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
            url=self._url(),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
                **self.agent.headers,
            },
            payload=self._payload(request),
            timeout=self.agent.timeout_seconds,
        )
        candidate = (raw.get("candidates") or [{}])[0]
        content = candidate.get("content") or {}
        return ProviderResult(
            text=content_to_text(content.get("parts")),
            model=self.agent.model,
            raw=raw,
            usage=dict(raw.get("usageMetadata") or {}),
            finish_reason=candidate.get("finishReason"),
        )

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
        generation_config = dict(
            request.raw.get("generationConfig")
            or request.raw.get("generation_config")
            or {}
        )
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for message in request.messages:
            role = message.get("role", "user")
            text = content_to_text(message.get("content"))
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


def create_provider(agent: AgentConfig) -> Provider:
    provider = normalize_provider(agent.provider)
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
        raise ProviderError("Search returned a non-HTML response", retryable=True)

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
        raise ProviderError(f"Network error: {exc}", retryable=True) from exc

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
