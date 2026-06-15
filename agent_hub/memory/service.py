from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..models import HubRequest, HubResponse
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


class MemoryService:
    """Explicit request/session/workspace/long-term memory facade."""

    def __init__(self, state_dir: Path, workspace_dir: Path | None = None) -> None:
        self.state_dir = Path(state_dir)
        self.workspace_dir = Path(workspace_dir) if workspace_dir else None
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
    ) -> MemoryRecord:
        record = MemoryRecord(key=key, value=value, tier=tier, metadata=dict(metadata or {}))
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
        }

    def _records_for_tier(self, tier: MemoryTier) -> list[MemoryRecord]:
        if tier == "request":
            return list(self._request_records.values())
        records = []
        for raw in self._load_tier(tier).values():
            if isinstance(raw, dict):
                records.append(_record_from_dict(raw))
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
