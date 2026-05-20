from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_CONFIG_PATH = Path("agent-hub.config.json")


@dataclass(slots=True)
class AgentConfig:
    name: str
    provider: str
    model: str
    enabled: bool = True
    free: bool | None = None
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
    workspace_dir: Path = Path(".")
    agent_max_steps: int = 8
    allow_shell_tools: bool = True
    free_only: bool = True
    default_route: list[str] = field(default_factory=list)
    routes: list[RouteRule] = field(default_factory=list)
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    include_raw_responses: bool = False
    expose_routing_details: bool = False

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> HubConfig:
    config_path = Path(path)
    if not config_path.exists():
        return free_local_config()

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    return config_from_dict(raw)


def free_local_config() -> HubConfig:
    """Cloud-style local aliases backed by Ollama or another OpenAI-compatible server."""

    local_model = os.environ.get("AGENT_HUB_LOCAL_MODEL", "local-model")
    local_base_url = os.environ.get("AGENT_HUB_LOCAL_BASE_URL", "http://127.0.0.1:8000")
    local_max_tokens = _env_int("AGENT_HUB_LOCAL_MAX_TOKENS", 4096)
    local_context_window = _env_int("AGENT_HUB_LOCAL_CONTEXT_WINDOW", 8192)
    local_timeout = _env_float("AGENT_HUB_LOCAL_TIMEOUT_SECONDS", 15.0)
    cloud_alias_base_url = os.environ.get(
        "AGENT_HUB_CLOUD_ALIAS_BASE_URL",
        os.environ.get("AGENT_HUB_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
    )

    agents = {
        "local-research": AgentConfig(
            name="local-research",
            provider="local-research",
            model="local-extractive-research",
            free=True,
            timeout_seconds=20.0,
            cooldown_seconds=5.0,
            context_window=1_000_000,
        ),
        "custom-local": AgentConfig(
            name="custom-local",
            provider="openai-compatible",
            model=local_model,
            base_url=local_base_url,
            free=True,
            timeout_seconds=local_timeout,
            max_tokens=local_max_tokens,
            cooldown_seconds=20.0,
            context_window=local_context_window,
        ),
        "ollama-qwen-coder": AgentConfig(
            name="ollama-qwen-coder",
            provider="openai-compatible",
            model=os.environ.get("AGENT_HUB_OLLAMA_CODER_MODEL", "qwen2.5-coder:7b"),
            base_url=os.environ.get("AGENT_HUB_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            free=True,
            timeout_seconds=30.0,
            max_tokens=4096,
            cooldown_seconds=10.0,
            context_window=32_768,
        ),
        "ollama-qwen3": AgentConfig(
            name="ollama-qwen3",
            provider="openai-compatible",
            model=os.environ.get("AGENT_HUB_OLLAMA_GENERAL_MODEL", "qwen3:8b"),
            base_url=os.environ.get("AGENT_HUB_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            free=True,
            timeout_seconds=30.0,
            max_tokens=4096,
            cooldown_seconds=10.0,
            context_window=32_768,
        ),
        "lm-studio": AgentConfig(
            name="lm-studio",
            provider="openai-compatible",
            model=os.environ.get("AGENT_HUB_LM_STUDIO_MODEL", "local-model"),
            base_url=os.environ.get("AGENT_HUB_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234"),
            free=True,
            timeout_seconds=30.0,
            max_tokens=4096,
            cooldown_seconds=10.0,
            context_window=32_768,
        ),
        "localai": AgentConfig(
            name="localai",
            provider="openai-compatible",
            model=os.environ.get("AGENT_HUB_LOCALAI_MODEL", "llama-3.2-1b-instruct:q4_k_m"),
            base_url=os.environ.get("AGENT_HUB_LOCALAI_BASE_URL", "http://127.0.0.1:8080"),
            free=True,
            timeout_seconds=30.0,
            max_tokens=4096,
            cooldown_seconds=10.0,
            context_window=8192,
        ),
        "vllm": AgentConfig(
            name="vllm",
            provider="openai-compatible",
            model=os.environ.get("AGENT_HUB_VLLM_MODEL", local_model),
            base_url=os.environ.get("AGENT_HUB_VLLM_BASE_URL", "http://127.0.0.1:8000"),
            free=True,
            timeout_seconds=30.0,
            max_tokens=4096,
            cooldown_seconds=10.0,
            context_window=local_context_window,
        ),
        "claude": AgentConfig(
            name="claude",
            provider="openai-compatible",
            model=os.environ.get("AGENT_HUB_CLAUDE_LOCAL_MODEL", "qwen2.5-coder:7b"),
            base_url=os.environ.get("AGENT_HUB_CLAUDE_LOCAL_BASE_URL", cloud_alias_base_url),
            free=True,
            timeout_seconds=120.0,
            max_tokens=4096,
            cooldown_seconds=30.0,
            context_window=32_768,
        ),
        "gemini": AgentConfig(
            name="gemini",
            provider="openai-compatible",
            model=os.environ.get("AGENT_HUB_GEMINI_LOCAL_MODEL", "gemma3:4b"),
            base_url=os.environ.get("AGENT_HUB_GEMINI_LOCAL_BASE_URL", cloud_alias_base_url),
            free=True,
            timeout_seconds=120.0,
            max_tokens=4096,
            cooldown_seconds=30.0,
            context_window=128_000,
        ),
        "chatgpt": AgentConfig(
            name="chatgpt",
            provider="openai-compatible",
            model=os.environ.get("AGENT_HUB_CHATGPT_LOCAL_MODEL", "llama3.2"),
            base_url=os.environ.get("AGENT_HUB_CHATGPT_LOCAL_BASE_URL", cloud_alias_base_url),
            free=True,
            timeout_seconds=120.0,
            max_tokens=4096,
            cooldown_seconds=30.0,
            context_window=128_000,
        ),
        "echo": AgentConfig(
            name="echo",
            provider="echo",
            model="local-echo",
            free=True,
            cooldown_seconds=1.0,
            context_window=1_000_000,
        ),
    }
    return HubConfig(
        workspace_dir=Path("."),
        agent_max_steps=8,
        allow_shell_tools=True,
        free_only=True,
        default_route=[*cloud_agent_names(), *free_local_agent_names(), "echo"],
        routes=[
            RouteRule(
                name="coding",
                keywords=["code", "bug", "fix", "refactor", "test", "repo"],
                agents=[*cloud_agent_names(), *free_local_agent_names(), "echo"],
            ),
            RouteRule(
                name="local-agent",
                keywords=["agent", "workspace", "edit", "implement"],
                agents=free_local_agent_names(),
            ),
            RouteRule(
                name="hybrid-agent",
                keywords=[],
                agents=[*cloud_agent_names(), *free_local_agent_names(), "echo"],
            ),
            RouteRule(
                name="cloud-agent",
                keywords=[],
                agents=[*cloud_agent_names(), *free_local_agent_names(), "echo"],
            ),
            RouteRule(
                name="research",
                keywords=["research", "search", "latest", "sources", "web", "news"],
                agents=["local-research", *cloud_agent_names(), "echo"],
            )
        ],
        agents=agents,
        expose_routing_details=False,
    )


def free_local_agent_names() -> list[str]:
    return ["ollama-qwen-coder", "ollama-qwen3", "lm-studio", "vllm", "custom-local", "localai"]


def cloud_agent_names() -> list[str]:
    return ["claude", "gemini", "chatgpt"]


def config_from_dict(raw: dict[str, Any]) -> HubConfig:
    agents = {
        item["name"]: AgentConfig(
            name=item["name"],
            provider=item["provider"],
            model=item.get("model", item["name"]),
            enabled=item.get("enabled", True),
            free=item.get("free"),
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
        workspace_dir=Path(raw.get("workspace_dir", ".")),
        agent_max_steps=int(raw.get("agent_max_steps", 8)),
        allow_shell_tools=bool(raw.get("allow_shell_tools", True)),
        free_only=bool(raw.get("free_only", True)),
        default_route=list(raw.get("default_route", agents.keys())),
        routes=routes,
        agents=agents,
        include_raw_responses=bool(raw.get("include_raw_responses", False)),
        expose_routing_details=bool(raw.get("expose_routing_details", False)),
    )


def is_free_agent(agent: AgentConfig) -> bool:
    if agent.free is not None:
        return bool(agent.free)

    provider = agent.provider.lower()
    if provider == "echo":
        return True
    if normalize_provider(provider) == "local-research":
        return True
    if normalize_provider(provider) != "openai-compatible":
        return False
    return _is_local_or_private_url(agent.base_url)


def normalize_provider(provider: str) -> str:
    lowered = provider.lower()
    if lowered in {"chatgpt", "openai-chat", "gpt"}:
        return "openai"
    if lowered in {"claude", "anthropic-messages"}:
        return "anthropic"
    if lowered in {"google", "google-gemini", "generative-language"}:
        return "gemini"
    if lowered in {"local-research", "research", "local-web", "web-local"}:
        return "local-research"
    if lowered in {"gemma", "gema", "local", "custom", "custom-local", "local-openai"}:
        return "openai-compatible"
    return lowered


def config_to_dict(config: HubConfig) -> dict[str, Any]:
    return {
        "host": config.host,
        "port": config.port,
        "state_dir": str(config.state_dir),
        "inbox_dir": str(config.inbox_dir),
        "outbox_dir": str(config.outbox_dir),
        "archive_dir": str(config.archive_dir),
        "workspace_dir": str(config.workspace_dir),
        "agent_max_steps": config.agent_max_steps,
        "allow_shell_tools": config.allow_shell_tools,
        "free_only": config.free_only,
        "include_raw_responses": config.include_raw_responses,
        "expose_routing_details": config.expose_routing_details,
        "default_route": config.default_route,
        "routes": [
            {
                "name": route.name,
                "keywords": route.keywords,
                "agents": route.agents,
            }
            for route in config.routes
        ],
        "agents": [
            _drop_empty(
                {
                    "name": agent.name,
                    "provider": agent.provider,
                    "model": agent.model,
                    "enabled": agent.enabled,
                    "free": agent.free,
                    "api_key_env": agent.api_key_env,
                    "api_key": agent.api_key,
                    "base_url": agent.base_url,
                    "timeout_seconds": agent.timeout_seconds,
                    "max_tokens": agent.max_tokens,
                    "headers": agent.headers,
                    "cooldown_seconds": agent.cooldown_seconds,
                    "context_window": agent.context_window,
                }
            )
            for agent in config.agents.values()
        ],
    }


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in data.items()
        if value is not None and value != {} and value != []
    }


def _is_local_or_private_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    host = parsed.hostname
    if not host:
        return False
    lowered = host.lower()
    if lowered in {"localhost", "host.docker.internal"}:
        return True
    if lowered in {"0.0.0.0", "127.0.0.1", "::1"}:
        return True
    try:
        import ipaddress

        address = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default

