from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..context import *  # noqa: F403
from ..context import (
    content_to_text,
    estimate_message_tokens,
    estimate_text_tokens,
    is_protected_context_message,
)
from ..models import HubRequest


@dataclass(slots=True)
class ContextMetadata:
    estimated_tokens: int
    compressed_tokens: int
    summary_count: int = 0
    dropped_messages: int = 0
    preserved_recent_messages: int = 0
    preserved_protected_messages: int = 0
    repository_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimated_tokens": self.estimated_tokens,
            "compressed_tokens": self.compressed_tokens,
            "summary_count": self.summary_count,
            "dropped_messages": self.dropped_messages,
            "preserved_recent_messages": self.preserved_recent_messages,
            "preserved_protected_messages": self.preserved_protected_messages,
            "repository_files": list(self.repository_files),
        }


@dataclass(slots=True)
class ContextWindow:
    messages: list[dict[str, Any]]
    metadata: ContextMetadata


@dataclass(slots=True)
class RepositoryMemory:
    file_summaries: dict[str, str] = field(default_factory=dict)
    repo_summary: str = ""
    important_files: list[str] = field(default_factory=list)

    def remember_file(self, path: str, summary: str, *, important: bool = False) -> None:
        clean = path.replace("\\", "/").strip()
        if not clean:
            return
        self.file_summaries[clean] = _compact_text(summary, 1200)
        if important and clean not in self.important_files:
            self.important_files.append(clean)

    def mark_important(self, path: str) -> None:
        clean = path.replace("\\", "/").strip()
        if clean and clean not in self.important_files:
            self.important_files.append(clean)

    def to_message(self) -> dict[str, str] | None:
        lines: list[str] = []
        if self.repo_summary:
            lines.extend(["Repository summary:", _compact_text(self.repo_summary, 1600)])
        if self.important_files:
            lines.extend(["Important files:", ", ".join(self.important_files[:40])])
        for path in self.important_files[:20]:
            summary = self.file_summaries.get(path)
            if summary:
                lines.append(f"- {path}: {summary}")
        if not lines:
            return None
        return {"role": "system", "content": "\n".join(lines)}


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class ChunkStore(Protocol):
    def add(self, chunks: list[dict[str, Any]]) -> None:
        ...

    def search(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        ...


class SemanticChunkSelector(Protocol):
    def select(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        ...


class KeywordChunkSelector:
    """Future-ready semantic selector using lexical overlap until embeddings exist."""

    def select(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        terms = set(_terms(query))
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for index, chunk in enumerate(chunks):
            text = content_to_text(chunk.get("text") or chunk.get("content") or "")
            score = sum(1 for term in terms if term in text.lower())
            if score:
                scored.append((score, -index, chunk))
        return [chunk for _score, _index, chunk in sorted(scored, reverse=True)[:limit]]


class ContextEngine:
    """Token-aware context compaction with summaries and repository memory."""

    def __init__(
        self,
        *,
        max_tokens: int = 32_000,
        preserve_recent: int = 8,
        repository_memory: RepositoryMemory | None = None,
        chunk_selector: SemanticChunkSelector | None = None,
    ) -> None:
        self.max_tokens = max(1, int(max_tokens))
        self.preserve_recent = max(1, int(preserve_recent))
        self.repository_memory = repository_memory or RepositoryMemory()
        self.chunk_selector = chunk_selector or KeywordChunkSelector()
        self.rolling_summaries: list[str] = []

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        return estimate_message_tokens(messages)

    def compress(
        self,
        request: HubRequest,
        *,
        max_tokens: int | None = None,
    ) -> ContextWindow:
        budget = max(1, int(max_tokens or self.max_tokens))
        original = [dict(message) for message in request.messages if isinstance(message, dict)]
        repository_message = self.repository_memory.to_message()
        estimated = estimate_message_tokens(original)
        if repository_message:
            estimated += estimate_message_tokens([repository_message])
        if estimated <= budget:
            messages = ([repository_message] if repository_message else []) + original
            return ContextWindow(
                messages=messages,
                metadata=ContextMetadata(
                    estimated_tokens=estimated,
                    compressed_tokens=estimated,
                    repository_files=list(self.repository_memory.important_files),
                ),
            )

        recent_start = max(0, len(original) - self.preserve_recent)
        recent = [dict(message) for message in original[recent_start:]]
        older = [dict(message) for message in original[:recent_start]]
        protected = [
            message
            for index, message in enumerate(older)
            if is_protected_context_message(message, recent=index >= max(0, len(older) - 4))
        ]
        summarizable = [message for message in older if message not in protected]
        summary_text = self.summarize_messages(summarizable)
        messages: list[dict[str, Any]] = []
        if repository_message:
            messages.append(repository_message)
        if summary_text:
            self.rolling_summaries.append(summary_text)
            messages.append({"role": "system", "content": f"Conversation summary:\n{summary_text}"})
        messages.extend(protected)
        messages.extend(recent)

        while estimate_message_tokens(messages) > budget and len(messages) > 1:
            drop_index = _first_droppable_index(messages, preserve_tail=len(recent))
            if drop_index is None:
                messages[-1]["content"] = _compact_text(content_to_text(messages[-1].get("content")), budget * 3)
                break
            del messages[drop_index]

        compressed = estimate_message_tokens(messages)
        return ContextWindow(
            messages=messages,
            metadata=ContextMetadata(
                estimated_tokens=estimated,
                compressed_tokens=compressed,
                summary_count=1 if summary_text else 0,
                dropped_messages=max(0, len(original) - len(messages)),
                preserved_recent_messages=len(recent),
                preserved_protected_messages=len(protected),
                repository_files=list(self.repository_memory.important_files),
            ),
        )

    def summarize_messages(self, messages: list[dict[str, Any]]) -> str:
        if not messages:
            return ""
        lines: list[str] = []
        for message in messages[-24:]:
            role = str(message.get("role") or "user")
            text = _compact_text(content_to_text(message.get("content")), 360)
            if text:
                lines.append(f"{role}: {text}")
        return _compact_text("\n".join(lines), 2400)

    def select_chunks(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        return self.chunk_selector.select(query, chunks, limit=limit)


def estimate_context_tokens(request_or_messages: HubRequest | list[dict[str, Any]]) -> int:
    messages = request_or_messages.messages if isinstance(request_or_messages, HubRequest) else request_or_messages
    return estimate_message_tokens(messages)


def compress_request_context(
    request: HubRequest,
    *,
    max_tokens: int = 32_000,
    repository_memory: RepositoryMemory | None = None,
) -> ContextWindow:
    return ContextEngine(max_tokens=max_tokens, repository_memory=repository_memory).compress(request)


def _first_droppable_index(messages: list[dict[str, Any]], *, preserve_tail: int = 0) -> int | None:
    tail_start = max(0, len(messages) - preserve_tail)
    for index, message in enumerate(messages):
        if preserve_tail and index >= tail_start:
            continue
        if message.get("role") == "system":
            continue
        if is_protected_context_message(message):
            continue
        return index
    return None


def _terms(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9_./-]{3,}", str(text).lower())
        if word not in {"the", "and", "for", "with", "that", "this"}
    ][:80]


def _compact_text(text: str, maximum: int) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= maximum:
        return clean
    return clean[: max(0, maximum - 16)].rstrip() + " [truncated]"


__all__ = sorted(
    name
    for name in globals()
    if not name.startswith("_")
    and name
    not in {
        "Any",
        "Protocol",
        "annotations",
        "dataclass",
        "field",
        "re",
    }
)
