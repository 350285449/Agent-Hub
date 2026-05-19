from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("agent-hub.config.json")


@dataclass(slots=True)
class AgentConfig:
    name: str
    provider: str
    model: str
    enabled: bool = True
    api_key_env: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    timeout_seconds: float = 120.0
    max_tokens: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    cooldown_seconds: float = 120.0
    context_window: int | None = None

    @property
    def resolved_api_key(self) -> str | None:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env)
        return None


@dataclass(slots=True)
class RouteRule:
    name: str
    agents: list[str]
    keywords: list[str] = field(default_factory=list)

    def matches(self, text: str) -> bool:
        if not self.keywords:
            return False
        lowered = text.lower()
        return any(keyword.lower() in lowered for keyword in self.keywords)


@dataclass(slots=True)
class HubConfig:
    host: str = "127.0.0.1"
    port: int = 8787
    state_dir: Path = Path(".agent-hub/state")
    inbox_dir: Path = Path(".agent-hub/inbox")
    outbox_dir: Path = Path(".agent-hub/outbox")
    archive_dir: Path = Path(".agent-hub/archive")
    default_route: list[str] = field(default_factory=list)
    routes: list[RouteRule] = field(default_factory=list)
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    include_raw_responses: bool = False

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> HubConfig:
    config_path = Path(path)
    if not config_path.exists():
        return HubConfig(
            agents={
                "echo": AgentConfig(
                    name="echo",
                    provider="echo",
                    model="local-echo",
                )
            },
            default_route=["echo"],
        )

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    return config_from_dict(raw)


def config_from_dict(raw: dict[str, Any]) -> HubConfig:
    agents = {
        item["name"]: AgentConfig(
            name=item["name"],
            provider=item["provider"],
            model=item.get("model", item["name"]),
            enabled=item.get("enabled", True),
            api_key_env=item.get("api_key_env"),
            api_key=item.get("api_key"),
            base_url=item.get("base_url"),
            timeout_seconds=float(item.get("timeout_seconds", 120.0)),
            max_tokens=item.get("max_tokens"),
            headers=dict(item.get("headers", {})),
            cooldown_seconds=float(item.get("cooldown_seconds", 120.0)),
            context_window=item.get("context_window"),
        )
        for item in raw.get("agents", [])
    }
    routes = [
        RouteRule(
            name=item["name"],
            agents=list(item.get("agents", [])),
            keywords=list(item.get("keywords", [])),
        )
        for item in raw.get("routes", [])
    ]
    return HubConfig(
        host=raw.get("host", "127.0.0.1"),
        port=int(raw.get("port", 8787)),
        state_dir=Path(raw.get("state_dir", ".agent-hub/state")),
        inbox_dir=Path(raw.get("inbox_dir", ".agent-hub/inbox")),
        outbox_dir=Path(raw.get("outbox_dir", ".agent-hub/outbox")),
        archive_dir=Path(raw.get("archive_dir", ".agent-hub/archive")),
        default_route=list(raw.get("default_route", agents.keys())),
        routes=routes,
        agents=agents,
        include_raw_responses=bool(raw.get("include_raw_responses", False)),
    )
