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
    _search_with_duckduckgo_instant,
    _search_with_wikipedia,
    _urls_in_text,
)


class LocalResearchProvider(BaseProviderAdapter):
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent
        self._last_search_diagnostics: list[dict[str, Any]] = []

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
        hits = self._search(query, max_sources=max_sources)

        documents: list[dict[str, Any]] = []
        for hit in hits[:max_sources]:
            text = self._fetch(hit["url"])
            fetched_snippet = _best_snippet(query, text) if text else ""
            snippet = _select_research_snippet(
                query=query,
                fetched_snippet=fetched_snippet,
                search_snippet=str(hit.get("snippet") or ""),
            )
            if not snippet:
                continue
            documents.append(
                {
                    "title": hit.get("title") or hit["url"],
                    "url": hit["url"],
                    "snippet": snippet,
                    "source": hit.get("source", "web"),
                    "fetch_status": "fetched" if text else "search_snippet",
                }
            )

        if not documents:
            documents = [
                {
                    "title": hit.get("title") or hit["url"],
                    "url": hit["url"],
                    "snippet": hit.get("snippet", ""),
                    "source": hit.get("source", "web"),
                    "fetch_status": "search_snippet",
                }
                for hit in hits[:max_sources]
                if hit.get("url") and hit.get("snippet")
            ]

        answer = _research_answer(query, documents)
        return ProviderResult(
            text=answer,
            model=self.agent.model,
            raw={
                "local_research": True,
                "query": query,
                "source_count": len(documents),
                "search_attempts": list(self._last_search_diagnostics),
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
        direct_hits = [
            {"title": url, "url": url, "snippet": "", "source": "direct_url"}
            for url in _urls_in_text(query)
        ]
        diagnostics: list[dict[str, Any]] = [
            {
                "strategy": "direct_url",
                "ok": bool(direct_hits),
                "result_count": len(direct_hits),
            }
        ]
        hits = list(direct_hits)
        search_query = query
        for url in _urls_in_text(query):
            search_query = search_query.replace(url, " ")
        search_query = _clean_text(search_query) or query
        strategies = [
            ("duckduckgo_html", "_search_with_duckduckgo", _search_with_duckduckgo),
            (
                "duckduckgo_instant",
                "_search_with_duckduckgo_instant",
                _search_with_duckduckgo_instant,
            ),
            ("wikipedia", "_search_with_wikipedia", _search_with_wikipedia),
        ]
        for strategy, facade_name, default in strategies:
            if len(_dedupe_hits(hits)) >= max_sources:
                break
            search = _facade_callable(facade_name, default)
            try:
                found = search(
                    query=search_query,
                    limit=max_sources,
                    timeout=self.agent.timeout_seconds,
                )
            except Exception as exc:
                diagnostics.append(
                    {
                        "strategy": strategy,
                        "ok": False,
                        "result_count": 0,
                        "error": str(exc)[:300],
                    }
                )
                continue
            normalized = [
                {**hit, "source": strategy}
                for hit in found
                if isinstance(hit, dict) and hit.get("url")
            ]
            hits.extend(normalized)
            diagnostics.append(
                {
                    "strategy": strategy,
                    "ok": bool(normalized),
                    "result_count": len(normalized),
                }
            )
        self._last_search_diagnostics = diagnostics
        return _dedupe_hits(hits)[:max_sources]

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


def _select_research_snippet(*, query: str, fetched_snippet: str, search_snippet: str) -> str:
    fetched = _clean_text(fetched_snippet)
    searched = _clean_text(search_snippet)
    if not fetched:
        return searched
    if not searched:
        return fetched
    return searched if _snippet_quality(query, searched) >= _snippet_quality(query, fetched) else fetched


def _snippet_quality(query: str, snippet: str) -> float:
    lowered = snippet.lower()
    words = [word for word in query.lower().split() if len(word) > 2]
    keyword_hits = sum(1 for word in words if word in lowered)
    noise_penalty = 0.0
    if len(snippet) > 500 and snippet.count(" ") > 70:
        noise_penalty += 0.5
    if sum(1 for char in snippet if ord(char) > 127) > len(snippet) * 0.35:
        noise_penalty += 0.5
    return keyword_hits - noise_penalty


LocalResearchAdapter = LocalResearchProvider


__all__ = ["LocalResearchAdapter", "LocalResearchProvider"]
