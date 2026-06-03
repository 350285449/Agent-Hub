from __future__ import annotations

import json
import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .context import content_to_text, estimate_message_tokens, is_protected_context_message


SummarizationHook = Callable[[list[dict[str, Any]], int], list[dict[str, Any]]]


@dataclass(slots=True)
class TokenOptimizationResult:
    messages: list[dict[str, Any]]
    original_tokens: int
    final_tokens: int
    max_context_tokens: int
    cache_hit: bool = False
    summarized: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def tokens_saved(self) -> int:
        return max(0, self.original_tokens - self.final_tokens)

    @property
    def compression_ratio(self) -> float:
        if self.original_tokens <= 0:
            return 1.0
        return round(self.final_tokens / self.original_tokens, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_tokens": self.original_tokens,
            "final_tokens": self.final_tokens,
            "max_context_tokens": self.max_context_tokens,
            "tokens_saved": self.tokens_saved,
            "compression_ratio": self.compression_ratio,
            "cache_hit": self.cache_hit,
            "summarized": self.summarized,
            "warnings": list(self.warnings),
        }


class ContextCache:
    """Tiny reusable context cache for token estimates and compacted message reuse."""

    def __init__(self, path: str | Path, *, enabled: bool = True, max_entries: int = 128) -> None:
        self.path = Path(path)
        self.enabled = enabled and max_entries > 0
        self.max_entries = max(0, int(max_entries))
        self._lock = threading.RLock()

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self._lock:
            data = self._load()
            entry = data.get(key)
            if isinstance(entry, dict):
                entry["last_used_at"] = time.time()
                data[key] = entry
                self._save(data)
                return dict(entry)
            return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock:
            data = self._load()
            data[key] = {"created_at": time.time(), "last_used_at": time.time(), **value}
            if len(data) > self.max_entries:
                ordered = sorted(
                    data.items(),
                    key=lambda item: float(item[1].get("last_used_at") or item[1].get("created_at") or 0.0),
                )
                data = dict(ordered[-self.max_entries :])
            self._save(data)

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        entries = raw.get("entries") if isinstance(raw, dict) else None
        return dict(entries) if isinstance(entries, dict) else {}

    def _save(self, entries: dict[str, dict[str, Any]]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_name(f"{self.path.name}.tmp")
            tmp_path.write_text(
                json.dumps({"version": 1, "entries": entries}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_path.replace(self.path)
        except OSError:
            return


class TokenOptimizer:
    """Provider-aware prompt sizing, safe truncation, and optional summarization hook."""

    def __init__(
        self,
        *,
        cache: ContextCache | None = None,
        summarization_enabled: bool = False,
        summarization_hook: SummarizationHook | None = None,
    ) -> None:
        self.cache = cache
        self.summarization_enabled = summarization_enabled
        self.summarization_hook = summarization_hook

    def optimize(
        self,
        messages: list[dict[str, Any]],
        *,
        max_context_tokens: int,
    ) -> TokenOptimizationResult:
        original_tokens = estimate_message_tokens(messages)
        key = context_cache_key(messages, max_context_tokens=max_context_tokens)
        cache_hit = bool(self.cache and self.cache.get(key))
        warnings: list[str] = []
        optimized = [dict(message) for message in messages]
        summarized = False

        if original_tokens > max_context_tokens and self.summarization_enabled and self.summarization_hook:
            try:
                proposed = self.summarization_hook(optimized, max_context_tokens)
            except Exception:
                proposed = []
            if isinstance(proposed, list) and proposed:
                optimized = [dict(message) for message in proposed if isinstance(message, dict)]
                summarized = True
                warnings.append("summarization_hook_applied")

        if estimate_message_tokens(optimized) > max_context_tokens:
            optimized = safe_truncate_messages(optimized, max_context_tokens)
            warnings.append("safe_truncation_applied")

        final_tokens = estimate_message_tokens(optimized)
        result = TokenOptimizationResult(
            messages=optimized,
            original_tokens=original_tokens,
            final_tokens=final_tokens,
            max_context_tokens=max_context_tokens,
            cache_hit=cache_hit,
            summarized=summarized,
            warnings=warnings,
        )
        if self.cache is not None:
            self.cache.put(
                key,
                {
                    "original_tokens": original_tokens,
                    "final_tokens": final_tokens,
                    "message_count": len(optimized),
                    "tokens_saved": result.tokens_saved,
                },
            )
        return result


def safe_truncate_messages(
    messages: list[dict[str, Any]],
    max_context_tokens: int,
) -> list[dict[str, Any]]:
    """Keep protected/recent context, then trim content until under budget."""

    if estimate_message_tokens(messages) <= max_context_tokens:
        return [dict(message) for message in messages]
    protected: list[dict[str, Any]] = []
    tail: list[dict[str, Any]] = []
    tail_start = max(0, len(messages) - 6)
    for index, message in enumerate(messages):
        copied = dict(message)
        if is_protected_context_message(copied, recent=index >= max(0, len(messages) - 8)):
            protected.append(copied)
        elif index >= tail_start:
            tail.append(copied)
    reduced = _dedupe([*protected, *tail]) or [dict(messages[-1])]
    while len(reduced) > 1 and estimate_message_tokens(reduced) > max_context_tokens:
        removed = False
        for index, message in enumerate(reduced):
            if not is_protected_context_message(message, recent=index >= max(0, len(reduced) - 8)):
                reduced.pop(index)
                removed = True
                break
        if not removed:
            break
    if estimate_message_tokens(reduced) <= max_context_tokens:
        return reduced
    per_message_budget = max(200, (max_context_tokens * 3) // max(1, len(reduced)))
    return [_truncate_message(message, per_message_budget) for message in reduced]


def context_cache_key(messages: list[dict[str, Any]], *, max_context_tokens: int) -> str:
    text = json.dumps(messages, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return f"{max_context_tokens}:{digest}"


def _truncate_message(message: dict[str, Any], maximum_chars: int) -> dict[str, Any]:
    copied = dict(message)
    text = content_to_text(copied.get("content"))
    if len(text) > maximum_chars:
        copied["content"] = text[:maximum_chars].rstrip() + "\n[Context reduced for provider compatibility]"
    return copied


def _dedupe(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for message in messages:
        signature = json.dumps(message, sort_keys=True, ensure_ascii=False, default=str)
        if signature in seen:
            continue
        seen.add(signature)
        result.append(message)
    return result


__all__ = [
    "ContextCache",
    "SummarizationHook",
    "TokenOptimizationResult",
    "TokenOptimizer",
    "context_cache_key",
    "safe_truncate_messages",
]
