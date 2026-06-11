from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .context import content_to_text, estimate_message_tokens, is_protected_context_message


SummarizationHook = Callable[[list[dict[str, Any]], int], list[dict[str, Any]]]
_OPTIMIZER_CACHE_VERSION = "boost-token-optimizer-v2"


@dataclass(slots=True)
class TokenOptimizationResult:
    messages: list[dict[str, Any]]
    original_tokens: int
    final_tokens: int
    max_context_tokens: int
    target_context_tokens: int | None = None
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

    @property
    def saved_percent(self) -> float:
        if self.original_tokens <= 0:
            return 0.0
        return round((self.tokens_saved / self.original_tokens) * 100.0, 1)

    @property
    def target_reached(self) -> bool:
        if self.target_context_tokens is None:
            return self.final_tokens <= self.max_context_tokens
        return self.final_tokens <= self.target_context_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_tokens": self.original_tokens,
            "final_tokens": self.final_tokens,
            "max_context_tokens": self.max_context_tokens,
            "target_context_tokens": self.target_context_tokens,
            "tokens_saved": self.tokens_saved,
            "saved_percent": self.saved_percent,
            "compression_ratio": self.compression_ratio,
            "target_reached": self.target_reached,
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
        target_context_tokens: int | None = None,
    ) -> TokenOptimizationResult:
        original_tokens = estimate_message_tokens(messages)
        warnings: list[str] = []
        optimized = [dict(message) for message in messages]
        summarized = False
        target_tokens = _normalized_target_context_tokens(
            max_context_tokens=max_context_tokens,
            target_context_tokens=target_context_tokens,
        )
        key = context_cache_key(
            messages,
            max_context_tokens=max_context_tokens,
            target_context_tokens=target_tokens,
        )
        cached = self.cache.get(key) if self.cache is not None else None
        cache_hit = cached is not None
        cached_messages = cached.get("messages") if isinstance(cached, dict) else None
        if _cached_messages_fit(
            cached_messages,
            max_context_tokens=max_context_tokens,
            target_context_tokens=target_tokens,
        ):
            optimized = [dict(message) for message in cached_messages if isinstance(message, dict)]
            final_tokens = estimate_message_tokens(optimized)
            return TokenOptimizationResult(
                messages=optimized,
                original_tokens=original_tokens,
                final_tokens=final_tokens,
                max_context_tokens=max_context_tokens,
                target_context_tokens=target_tokens if target_tokens < max_context_tokens else None,
                cache_hit=True,
                summarized=bool(cached.get("summarized")) if isinstance(cached, dict) else False,
                warnings=["context_cache_reused"],
            )
        focus_terms = _focus_terms_from_messages(optimized)

        if original_tokens > target_tokens and self.summarization_enabled and self.summarization_hook:
            try:
                proposed = self.summarization_hook(optimized, target_tokens)
            except Exception:
                proposed = []
            if isinstance(proposed, list) and proposed:
                optimized = [dict(message) for message in proposed if isinstance(message, dict)]
                summarized = True
                warnings.append("summarization_hook_applied")
                focus_terms = _focus_terms_from_messages(optimized) or focus_terms

        optimized, deduplicated = dedupe_redundant_messages(optimized)
        if deduplicated:
            warnings.append(f"deduplicated_messages:{deduplicated}")

        if estimate_message_tokens(optimized) > target_tokens:
            optimized, collapsed = collapse_semantic_duplicate_messages(optimized, target_tokens)
            if collapsed:
                warnings.append(f"semantic_delta_compaction:{collapsed}")

        if estimate_message_tokens(optimized) > target_tokens:
            optimized, compacted = compact_repetitive_messages(
                optimized,
                target_tokens,
                focus_terms=focus_terms,
            )
            if compacted:
                warnings.append(f"extractive_message_compaction:{compacted}")

        if estimate_message_tokens(optimized) > target_tokens:
            optimized, selected = select_budgeted_relevant_messages(
                optimized,
                target_context_tokens=target_tokens,
                hard_context_tokens=max_context_tokens,
                focus_terms=focus_terms,
            )
            if selected:
                warnings.append(f"budgeted_relevance_mmr:{selected}")

        if estimate_message_tokens(optimized) > target_tokens:
            optimized, trimmed = trim_low_signal_messages(
                optimized,
                target_context_tokens=target_tokens,
                hard_context_tokens=max_context_tokens,
                focus_terms=focus_terms,
            )
            if trimmed:
                warnings.append(f"budgeted_context_knapsack:{trimmed}")

        if estimate_message_tokens(optimized) > max_context_tokens:
            optimized = safe_truncate_messages(optimized, max_context_tokens)
            warnings.append("safe_truncation_applied")

        final_tokens = estimate_message_tokens(optimized)
        result = TokenOptimizationResult(
            messages=optimized,
            original_tokens=original_tokens,
            final_tokens=final_tokens,
            max_context_tokens=max_context_tokens,
            target_context_tokens=target_tokens if target_tokens < max_context_tokens else None,
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
                    "messages": _cacheable_messages(optimized),
                    "summarized": summarized,
                    "optimizer_version": _OPTIMIZER_CACHE_VERSION,
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


def dedupe_redundant_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Drop exact repeated, unprotected messages while keeping the newest copy."""

    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    removed = 0
    last_recent_index = max(0, len(messages) - 4)
    for index in range(len(messages) - 1, -1, -1):
        message = dict(messages[index])
        if is_protected_context_message(message, recent=index >= last_recent_index):
            kept.append(message)
            continue
        signature = _message_signature(message)
        if signature in seen:
            removed += 1
            continue
        seen.add(signature)
        kept.append(message)
    kept.reverse()
    return kept, removed


def compact_repetitive_messages(
    messages: list[dict[str, Any]],
    max_context_tokens: int,
    *,
    focus_terms: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Replace large, low-entropy message bodies with compact extractive digests."""

    optimized = [dict(message) for message in messages]
    compacted = 0
    protected_tail = max(0, len(optimized) - 4)
    candidates = sorted(
        (
            (index, content_to_text(message.get("content")))
            for index, message in enumerate(optimized)
            if isinstance(message, dict)
            and not is_protected_context_message(message, recent=index >= protected_tail)
        ),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    for index, text in candidates:
        if estimate_message_tokens(optimized) <= max_context_tokens:
            break
        if len(text) < 1_200 or not _worth_extractively_compacting(text):
            continue
        next_message = dict(optimized[index])
        next_message["content"] = _extractive_digest(
            text,
            maximum=max(700, min(2_000, len(text) // 4)),
            focus_terms=focus_terms,
        )
        next_message["agent_hub_compacted_message"] = True
        optimized[index] = next_message
        compacted += 1
    return optimized, compacted


def collapse_semantic_duplicate_messages(
    messages: list[dict[str, Any]],
    max_context_tokens: int,
) -> tuple[list[dict[str, Any]], int]:
    """Collapse older near-duplicate messages into small deltas, keeping newest evidence."""

    if estimate_message_tokens(messages) <= max_context_tokens:
        return [dict(message) for message in messages], 0
    seen: list[tuple[str, str, set[str], set[str]]] = []
    kept: list[dict[str, Any]] = []
    collapsed = 0
    recent_start = max(0, len(messages) - 4)
    for index in range(len(messages) - 1, -1, -1):
        message = dict(messages[index])
        if is_protected_context_message(message, recent=index >= recent_start):
            kept.append(message)
            continue
        text = content_to_text(message.get("content"))
        fingerprint = _semantic_fingerprint(text)
        if len(text) < 800 or len(fingerprint) < 10:
            _remember_semantic_message(seen, message, fingerprint, text)
            kept.append(message)
            continue
        role = str(message.get("role") or "")
        name = str(message.get("name") or "")
        match_lines: set[str] | None = None
        for seen_role, seen_name, seen_fingerprint, seen_lines in seen:
            if seen_role != role or seen_name != name:
                continue
            if _jaccard_similarity(fingerprint, seen_fingerprint) >= 0.82:
                match_lines = seen_lines
                break
        if match_lines is None:
            _remember_semantic_message(seen, message, fingerprint, text)
            kept.append(message)
            continue
        delta = _semantic_delta_digest(text, reference_lines=match_lines, maximum=650)
        if delta:
            message["content"] = delta
            message["agent_hub_semantic_delta"] = True
            kept.append(message)
        collapsed += 1
    kept.reverse()
    return kept, collapsed


def trim_low_signal_messages(
    messages: list[dict[str, Any]],
    *,
    target_context_tokens: int,
    hard_context_tokens: int,
    focus_terms: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Trim low-utility older context by utility-per-token while preserving recent state."""

    optimized = [dict(message) for message in messages]
    if estimate_message_tokens(optimized) <= target_context_tokens:
        return optimized, 0
    candidates: list[tuple[float, int, int]] = []
    for index, message in enumerate(optimized):
        if _must_keep_context_message(
            message,
            index=index,
            total=len(optimized),
            focus_terms=focus_terms,
        ):
            continue
        text = content_to_text(message.get("content"))
        tokens = max(1, estimate_message_tokens([message]))
        utility = _message_utility_score(message, index=index, total=len(optimized))
        candidates.append((utility / tokens, -tokens, index))
    changed = 0
    removed: set[int] = set()
    for _, _, index in sorted(candidates):
        if estimate_message_tokens([msg for pos, msg in enumerate(optimized) if pos not in removed]) <= target_context_tokens:
            break
        message = optimized[index]
        text = content_to_text(message.get("content"))
        if len(text) >= 900 and _has_high_signal(text):
            compact = _extractive_digest(
                text,
                maximum=max(320, min(900, len(text) // 8)),
                focus_terms=focus_terms,
            )
            if len(compact) < len(text) * 0.7:
                next_message = dict(message)
                next_message["content"] = compact
                next_message["agent_hub_budget_compacted"] = True
                optimized[index] = next_message
                changed += 1
                continue
        removed.add(index)
        changed += 1
    if removed:
        optimized = [message for index, message in enumerate(optimized) if index not in removed]
    if estimate_message_tokens(optimized) > hard_context_tokens:
        optimized = safe_truncate_messages(optimized, hard_context_tokens)
    return optimized, changed


def select_budgeted_relevant_messages(
    messages: list[dict[str, Any]],
    *,
    target_context_tokens: int,
    hard_context_tokens: int,
    focus_terms: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Select older context with maximal relevance and novelty under the token budget."""

    optimized = [dict(message) for message in messages]
    if estimate_message_tokens(optimized) <= target_context_tokens:
        return optimized, 0
    fixed_indices = {
        index
        for index, message in enumerate(optimized)
        if _must_keep_context_message(
            message,
            index=index,
            total=len(optimized),
            focus_terms=focus_terms,
        )
    }
    fixed_messages = [message for index, message in enumerate(optimized) if index in fixed_indices]
    fixed_tokens = estimate_message_tokens(fixed_messages)
    if fixed_tokens >= target_context_tokens:
        return optimized, 0

    selected_indices = set(fixed_indices)
    selected_messages = {index: dict(optimized[index]) for index in fixed_indices}
    selected_fingerprints = [
        _semantic_fingerprint(content_to_text(message.get("content")))
        for message in fixed_messages
    ]
    budget_left = max(0, target_context_tokens - fixed_tokens)
    candidates: list[dict[str, Any]] = []
    terms = set(focus_terms or set())
    for index, message in enumerate(optimized):
        if index in fixed_indices:
            continue
        text = content_to_text(message.get("content"))
        tokens = max(1, estimate_message_tokens([message]))
        relevance = _focus_relevance_score(text, terms)
        utility = _message_utility_score(message, index=index, total=len(optimized))
        candidates.append(
            {
                "index": index,
                "message": message,
                "text": text,
                "tokens": tokens,
                "fingerprint": _semantic_fingerprint(text),
                "score": utility + relevance * 3.2,
                "focus_relevance": relevance,
            }
        )

    compacted = 0
    while candidates and budget_left > 0:
        candidates.sort(
            key=lambda row: _mmr_budget_score(row, selected_fingerprints),
            reverse=True,
        )
        row = candidates.pop(0)
        index = int(row["index"])
        tokens = int(row["tokens"])
        message = dict(row["message"])
        if tokens <= budget_left:
            selected_indices.add(index)
            selected_messages[index] = message
            selected_fingerprints.append(set(row["fingerprint"]))
            budget_left -= tokens
            continue
        text = str(row["text"])
        if row["focus_relevance"] <= 0 and not _has_high_signal(text):
            continue
        compact_budget = max(280, min(900, budget_left * 3))
        compact_text = _extractive_digest(text, maximum=compact_budget, focus_terms=terms)
        if not compact_text or len(compact_text) >= len(text) * 0.82:
            continue
        compact_message = dict(message)
        compact_message["content"] = compact_text
        compact_message["agent_hub_mmr_compacted"] = True
        compact_tokens = estimate_message_tokens([compact_message])
        if compact_tokens > budget_left:
            continue
        selected_indices.add(index)
        selected_messages[index] = compact_message
        selected_fingerprints.append(_semantic_fingerprint(compact_text))
        budget_left -= compact_tokens
        compacted += 1

    selected = [selected_messages[index] for index in sorted(selected_indices)]
    if not selected:
        return optimized, 0
    if estimate_message_tokens(selected) > hard_context_tokens:
        selected = safe_truncate_messages(selected, hard_context_tokens)
    changed = (len(optimized) - len(selected)) + compacted
    if changed <= 0 or estimate_message_tokens(selected) >= estimate_message_tokens(optimized):
        return optimized, 0
    return selected, changed


def context_cache_key(
    messages: list[dict[str, Any]],
    *,
    max_context_tokens: int,
    target_context_tokens: int | None = None,
) -> str:
    text = json.dumps(messages, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    target = target_context_tokens if target_context_tokens is not None else max_context_tokens
    return f"{_OPTIMIZER_CACHE_VERSION}:{max_context_tokens}:{target}:{digest}"


def _truncate_message(message: dict[str, Any], maximum_chars: int) -> dict[str, Any]:
    copied = dict(message)
    text = content_to_text(copied.get("content"))
    if len(text) > maximum_chars:
        copied["content"] = text[:maximum_chars].rstrip() + "\n[Context reduced for provider compatibility]"
    return copied


def _message_signature(message: dict[str, Any]) -> str:
    role = str(message.get("role") or "")
    name = str(message.get("name") or "")
    content = content_to_text(message.get("content"))
    normalized = "\n".join(line.rstrip() for line in content.splitlines()).strip()
    digest = hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()
    return f"{role}:{name}:{digest}"


def _worth_extractively_compacting(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 30:
        unique_ratio = len(set(lines)) / max(1, len(lines))
        if unique_ratio < 0.72:
            return True
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "traceback",
            "exception",
            "error:",
            "warning:",
            "\"matches\"",
            "\"content\"",
            "tool result",
            "diff --git",
        )
    )


def _extractive_digest(
    text: str,
    *,
    maximum: int,
    focus_terms: set[str] | None = None,
) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    focused = _focused_digest_lines(lines, focus_terms=focus_terms)
    important: list[str] = []
    for line in lines:
        lowered = line.lower()
        if any(
            marker in lowered
            for marker in (
                "traceback",
                "exception",
                "error",
                "warning",
                "failed",
                "assert",
                "file ",
                "diff --git",
                "++",
                "--",
            )
        ):
            important.append(line[:260])
        if len(important) >= 18:
            break
    head = [line[:260] for line in lines[:12] if line.strip()]
    tail = [line[:260] for line in lines[-8:] if line.strip()]
    compact = "\n".join(
        [
            "[Message compacted by Agent Hub extractive optimizer]",
            f"Original chars: {len(text)}",
            "",
            *head,
            *focused,
            *important,
            *tail,
        ]
    )
    compact = _dedupe_lines(compact)
    if len(compact) <= maximum:
        return compact
    return compact[: max(0, maximum - 16)].rstrip() + " [truncated]"


def _dedupe_lines(text: str) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for line in text.splitlines():
        key = line.strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(line)
    return "\n".join(result)


def _normalized_target_context_tokens(
    *,
    max_context_tokens: int,
    target_context_tokens: int | None,
) -> int:
    hard_limit = max(1, int(max_context_tokens or 1))
    if target_context_tokens is None:
        return hard_limit
    try:
        target = int(target_context_tokens)
    except (TypeError, ValueError):
        return hard_limit
    if target <= 0:
        return hard_limit
    return max(256, min(hard_limit, target))


def _cached_messages_fit(
    value: Any,
    *,
    max_context_tokens: int,
    target_context_tokens: int,
) -> bool:
    if not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value):
        return False
    tokens = estimate_message_tokens([dict(item) for item in value])
    if tokens > max_context_tokens:
        return False
    return target_context_tokens >= max_context_tokens or tokens <= target_context_tokens


def _cacheable_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        return json.loads(json.dumps(messages, ensure_ascii=False, default=str))
    except (TypeError, ValueError, json.JSONDecodeError):
        return [dict(message) for message in messages if isinstance(message, dict)]


def _focus_terms_from_messages(messages: list[dict[str, Any]]) -> set[str]:
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if message.get("agent_hub_repo_context"):
            continue
        role = str(message.get("role") or "")
        if role not in {"", "user"}:
            continue
        terms = _focus_terms(content_to_text(message.get("content")))
        if terms:
            return terms
    return set()


def _focus_terms(text: str) -> set[str]:
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9_./:-]{3,}", str(text or "").lower())[:500]:
        clean = token.strip("./:-_")
        if not clean or clean in _LOW_SIGNAL_TOKENS:
            continue
        terms.append(token)
        if "." in token or "/" in token:
            path_parts = [part for part in re.split(r"[/.:_-]+", token) if len(part) >= 3]
            terms.extend(part for part in path_parts if part not in _LOW_SIGNAL_TOKENS)
    return set(terms[:120])


def _focus_relevance_score(text: str, focus_terms: set[str]) -> float:
    if not focus_terms:
        return 0.0
    lowered = str(text or "").lower()
    matches = sum(1 for term in focus_terms if term in lowered)
    if matches <= 0:
        return 0.0
    return min(6.0, matches / max(1.0, len(focus_terms) ** 0.45))


def _must_keep_context_message(
    message: dict[str, Any],
    *,
    index: int,
    total: int,
    focus_terms: set[str] | None = None,
) -> bool:
    recent = index >= max(0, total - 4)
    if is_protected_context_message(message, recent=recent):
        return True
    role = str(message.get("role") or "")
    if role in {"system", "user"} and recent:
        return True
    if not recent:
        return False
    text = content_to_text(message.get("content"))
    if len(text) < 1_200:
        return True
    return _has_high_signal(text) or _focus_relevance_score(text, set(focus_terms or set())) >= 1.25


def _focused_digest_lines(lines: list[str], *, focus_terms: set[str] | None = None) -> list[str]:
    terms = {term for term in (focus_terms or set()) if len(term) >= 3}
    if not terms:
        return []
    selected: list[str] = []
    seen_windows: set[tuple[int, int]] = set()
    for index, line in enumerate(lines):
        lowered = line.lower()
        if not any(term in lowered for term in terms):
            continue
        start = max(0, index - 2)
        end = min(len(lines), index + 4)
        window = (start, end)
        if window in seen_windows:
            continue
        seen_windows.add(window)
        selected.extend(value[:260] for value in lines[start:end] if value.strip())
        if len(selected) >= 24:
            break
    return _dedupe_lines("\n".join(selected)).splitlines()


def _mmr_budget_score(row: dict[str, Any], selected_fingerprints: list[set[str]]) -> float:
    fingerprint = set(row.get("fingerprint") or set())
    novelty_penalty = 0.0
    if fingerprint and selected_fingerprints:
        novelty_penalty = max(_jaccard_similarity(fingerprint, seen) for seen in selected_fingerprints)
    score = float(row.get("score") or 0.0) * (1.0 - min(0.72, novelty_penalty))
    tokens = max(1, int(row.get("tokens") or 1))
    return score / (tokens ** 0.72)


def _remember_semantic_message(
    seen: list[tuple[str, str, set[str], set[str]]],
    message: dict[str, Any],
    fingerprint: set[str],
    text: str,
) -> None:
    if not fingerprint:
        return
    role = str(message.get("role") or "")
    name = str(message.get("name") or "")
    seen.append((role, name, fingerprint, _normalized_line_set(text)))
    if len(seen) > 48:
        del seen[:16]


def _semantic_fingerprint(text: str) -> set[str]:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9_./:-]{3,}", str(text or "").lower())
        if token not in _LOW_SIGNAL_TOKENS
    ][:1800]
    if len(tokens) < 3:
        return set(tokens)
    return {" ".join(tokens[index : index + 3]) for index in range(len(tokens) - 2)}


def _normalized_line_set(text: str) -> set[str]:
    return {_normalize_line(line) for line in text.splitlines() if _normalize_line(line)}


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lower())


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))


def _semantic_delta_digest(text: str, *, reference_lines: set[str], maximum: int) -> str:
    unique: list[str] = []
    for line in text.splitlines():
        clean = _normalize_line(line)
        if not clean or clean in reference_lines:
            continue
        if _high_signal_line(line):
            unique.append(line.rstrip()[:260])
        if len(unique) >= 12:
            break
    if not unique:
        return ""
    compact = "\n".join(
        [
            "[Near-duplicate context collapsed by Agent Hub]",
            "Unique high-signal lines:",
            *unique,
        ]
    )
    return _fit_text(_dedupe_lines(compact), maximum)


def _message_utility_score(message: dict[str, Any], *, index: int, total: int) -> float:
    text = content_to_text(message.get("content"))
    lowered = text.lower()
    score = 1.0
    role = str(message.get("role") or "")
    if role == "user":
        score += 1.4
    if role in {"tool", "function"} or message.get("tool_call_id") or message.get("tool_use_id"):
        score += 0.8
    if _has_high_signal(text):
        score += 4.0
    if re.search(r"\b[\w./-]+\.(?:py|js|ts|tsx|jsx|md|json|yaml|yml|toml)\b", text):
        score += 2.0
    if "diff --git" in lowered or re.search(r"^\s*(?:def|class|function|export|async def)\s+", text, re.MULTILINE):
        score += 2.2
    if _low_entropy_line_ratio(text) > 0.35:
        score -= 1.6
    score += max(0.0, (index / max(1, total - 1)) * 2.0)
    return max(0.1, score)


def _has_high_signal(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "traceback",
            "exception",
            "error",
            "warning",
            "failed",
            "assert",
            "diff --git",
            "todo",
            "fixme",
        )
    )


def _high_signal_line(line: str) -> bool:
    lowered = line.lower()
    return any(
        marker in lowered
        for marker in (
            "traceback",
            "exception",
            "error",
            "warning",
            "failed",
            "assert",
            "file ",
            "diff --git",
            "todo",
            "fixme",
        )
    )


def _low_entropy_line_ratio(text: str) -> float:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 8:
        return 0.0
    counts: dict[str, int] = {}
    for line in lines:
        counts[line] = counts.get(line, 0) + 1
    repeated = sum(count for count in counts.values() if count > 1)
    return repeated / max(1, len(lines))


def _fit_text(text: str, maximum: int) -> str:
    if len(text) <= maximum:
        return text
    return text[: max(0, maximum - 16)].rstrip() + " [truncated]"


_LOW_SIGNAL_TOKENS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "has",
    "have",
    "into",
    "not",
    "that",
    "the",
    "this",
    "with",
}


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
    "collapse_semantic_duplicate_messages",
    "compact_repetitive_messages",
    "context_cache_key",
    "dedupe_redundant_messages",
    "safe_truncate_messages",
    "select_budgeted_relevant_messages",
    "trim_low_signal_messages",
]
