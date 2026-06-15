from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..config import HubConfig
from ..models import HubRequest, HubResponse
from ..plugins.discovery import discover_plugins
from ..session_store import SessionStore

MemoryTier = Literal["request", "session", "workspace", "long_term"]


@dataclass(slots=True)
class MemoryRecord:
    key: str
    value: str
    tier: MemoryTier
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "tier": self.tier,
            "metadata": dict(self.metadata),
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class MemoryCompressionResult:
    original: str
    compressed: str
    original_chars: int
    compressed_chars: int
    ratio: float
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.memory_compression",
            "original_chars": self.original_chars,
            "compressed_chars": self.compressed_chars,
            "ratio": self.ratio,
            "keywords": list(self.keywords),
            "compressed": self.compressed,
        }


class DeterministicSemanticCompressor:
    """Dependency-free summarizer for memory values and retrieved context."""

    def compress(self, text: str, *, max_chars: int = 1200) -> MemoryCompressionResult:
        original = str(text or "")
        maximum = max(120, int(max_chars or 1200))
        cleaned = _collapse_blank_lines(original)
        if len(cleaned) <= maximum:
            compressed = cleaned
        else:
            compressed = _semantic_excerpt(cleaned, maximum=maximum)
        keywords = _keywords(cleaned)
        return MemoryCompressionResult(
            original=original,
            compressed=compressed,
            original_chars=len(original),
            compressed_chars=len(compressed),
            ratio=round(len(compressed) / max(1, len(original)), 4),
            keywords=keywords,
        )


class MemoryService:
    """Explicit request/session/workspace/long-term memory facade."""

    def __init__(
        self,
        state_dir: Path,
        workspace_dir: Path | None = None,
        *,
        config: HubConfig | None = None,
        compressor: DeterministicSemanticCompressor | None = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.workspace_dir = Path(workspace_dir) if workspace_dir else None
        self.config = config
        self.compressor = compressor or DeterministicSemanticCompressor()
        self.session_store = SessionStore(self.state_dir)
        self._request_records: dict[str, MemoryRecord] = {}
        self._memory_dir = self.state_dir / "memory"
        self._memory_dir.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        tier: MemoryTier,
        key: str,
        value: str,
        *,
        metadata: dict[str, Any] | None = None,
        compress: bool = False,
        max_chars: int = 1200,
    ) -> MemoryRecord:
        metadata_data = dict(metadata or {})
        stored_value = str(value)
        if compress:
            result = self.compress(stored_value, max_chars=max_chars)
            stored_value = result.compressed
            metadata_data["compression"] = result.to_dict()
        record = MemoryRecord(key=key, value=stored_value, tier=tier, metadata=metadata_data)
        if tier == "request":
            self._request_records[key] = record
            return record
        data = self._load_tier(tier)
        data[key] = record.to_dict()
        self._write_tier(tier, data)
        return record

    def get(self, tier: MemoryTier, key: str) -> MemoryRecord | None:
        if tier == "request":
            return self._request_records.get(key)
        raw = self._load_tier(tier).get(key)
        return _record_from_dict(raw) if isinstance(raw, dict) else None

    def search(self, query: str, *, tiers: list[MemoryTier] | None = None, limit: int = 10) -> list[MemoryRecord]:
        needle = query.casefold()
        records: list[MemoryRecord] = []
        for tier in tiers or ["request", "session", "workspace", "long_term"]:
            records.extend(self._records_for_tier(tier))
        matches = [record for record in records if needle in record.key.casefold() or needle in record.value.casefold()]
        matches.sort(key=lambda record: record.updated_at, reverse=True)
        return matches[:limit]

    def compress(self, text: str, *, max_chars: int = 1200) -> MemoryCompressionResult:
        return self.compressor.compress(text, max_chars=max_chars)

    def record_turn(self, request: HubRequest, response: HubResponse) -> None:
        self.session_store.record_turn(request, response)
        self.put(
            "session",
            f"{request.session_id}:last_turn",
            response.text,
            metadata={"agent": response.agent, "provider": response.provider, "model": response.model},
        )

    def explain(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.memory_tiers",
            "tiers": ["request", "session", "workspace", "long_term"],
            "workspace_dir": str(self.workspace_dir) if self.workspace_dir else None,
            "counts": {
                tier: len(self._records_for_tier(tier))
                for tier in ["request", "session", "workspace", "long_term"]
            },
            "semantic_compression": {
                "available": True,
                "implementation": self.compressor.__class__.__name__,
                "network_required": False,
            },
            "plugin_memory_contexts": len(self._plugin_memory_records()),
        }

    def _records_for_tier(self, tier: MemoryTier) -> list[MemoryRecord]:
        if tier == "request":
            return list(self._request_records.values())
        records = []
        for raw in self._load_tier(tier).values():
            if isinstance(raw, dict):
                records.append(_record_from_dict(raw))
        records.extend(record for record in self._plugin_memory_records() if record.tier == tier)
        return records

    def _plugin_memory_records(self) -> list[MemoryRecord]:
        if self.config is None:
            return []
        records: list[MemoryRecord] = []
        for plugin in discover_plugins(self.config).plugins:
            if not plugin.registerable or plugin.manifest.type != "memory_context":
                continue
            metadata = plugin.manifest.metadata if isinstance(plugin.manifest.metadata, dict) else {}
            contexts = metadata.get("contexts")
            rows = contexts if isinstance(contexts, list) else [metadata]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                tier = row.get("tier") if row.get("tier") in {"session", "workspace", "long_term"} else "workspace"
                key = str(row.get("key") or plugin.manifest.id).strip()
                value = str(row.get("value") or row.get("summary") or "").strip()
                if not key or not value:
                    continue
                records.append(
                    MemoryRecord(
                        key=key,
                        value=value,
                        tier=tier,
                        metadata={
                            "plugin_id": plugin.manifest.id,
                            "plugin_memory_context": True,
                            **(dict(row.get("metadata")) if isinstance(row.get("metadata"), dict) else {}),
                        },
                    )
                )
        return records

    def _tier_path(self, tier: MemoryTier) -> Path:
        if tier == "request":
            raise ValueError("request memory is in-process only")
        return self._memory_dir / f"{tier}.json"

    def _load_tier(self, tier: MemoryTier) -> dict[str, Any]:
        path = self._tier_path(tier)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_tier(self, tier: MemoryTier, data: dict[str, Any]) -> None:
        path = self._tier_path(tier)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _record_from_dict(data: dict[str, Any]) -> MemoryRecord:
    return MemoryRecord(
        key=str(data.get("key") or ""),
        value=str(data.get("value") or ""),
        tier=data.get("tier") if data.get("tier") in {"request", "session", "workspace", "long_term"} else "session",
        metadata=dict(data.get("metadata") or {}),
        updated_at=int(data.get("updated_at") or 0),
    )


def _collapse_blank_lines(text: str) -> str:
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    collapsed: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank:
                collapsed.append("")
            blank = True
            continue
        blank = False
        collapsed.append(line)
    return "\n".join(collapsed).strip()


def _semantic_excerpt(text: str, *, maximum: int) -> str:
    lines = text.splitlines()
    scored: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        score = 0
        lowered = stripped.lower()
        if stripped.startswith(("#", "-", "*")):
            score += 4
        if any(marker in lowered for marker in ("todo", "fixme", "error", "traceback", "security", "api", "route", "plugin", "memory")):
            score += 5
        if len(stripped) < 180:
            score += 2
        scored.append((-score, index, stripped))
    selected = [row[2] for row in sorted(scored)[: max(4, min(24, maximum // 80))]]
    if not selected:
        return text[:maximum].rstrip()
    output = "\n".join(selected)
    if len(output) > maximum:
        output = output[: maximum - 14].rstrip() + " [truncated]"
    return output


def _keywords(text: str) -> list[str]:
    words = [
        word.lower()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text)
        if word.lower() not in {"the", "and", "for", "with", "that", "this", "from", "into", "are", "was"}
    ]
    counts: dict[str, int] = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    return [word for word, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:12]]
