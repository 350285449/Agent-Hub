from __future__ import annotations

from typing import Any

from ..config import AgentConfig
from ..models import HubRequest, ProviderResult
from .base import BaseProviderAdapter
from .errors import ProviderError
from .shared import (
    _best_snippet,
    _clean_text,
    _dedupe_hits,
    _facade_callable,
    _get_url_text,
    _html_to_text,
    _research_answer,
    _research_query,
    _request_int,
    _rough_tokens,
    _search_with_duckduckgo,
    _urls_in_text,
)


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
        search_with_duckduckgo = _facade_callable(
            "_search_with_duckduckgo",
            _search_with_duckduckgo,
        )
        web_hits = search_with_duckduckgo(
            query=query,
            limit=max_sources,
            timeout=self.agent.timeout_seconds,
        )
        return _dedupe_hits([*direct_hits, *web_hits])[:max_sources]

    def _fetch(self, url: str) -> str:
        try:
            get_url_text = _facade_callable("_get_url_text", _get_url_text)
            content_type, text = get_url_text(
                url,
                timeout=self.agent.timeout_seconds,
                max_bytes=250_000,
            )
        except ProviderError:
            return ""
        if "html" in content_type:
            return _html_to_text(text)
        return _clean_text(text)


LocalResearchAdapter = LocalResearchProvider


__all__ = ["LocalResearchAdapter", "LocalResearchProvider"]
