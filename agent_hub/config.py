"""Configuration objects and defaults for the Agent-Hub runtime.

The app loads a JSON config into these dataclasses, then the router uses the
routes to pick an enabled agent for each request. The default cloud-control
route starts with Ollama cloud model IDs, so fresh configs do not run heavy local
models unless the user chooses the explicit local-control route.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .provider_presets import OPENAI_COMPATIBLE_PROVIDER_TYPES


DEFAULT_CONFIG_PATH = Path("agent-hub.config.json")


@dataclass(slots=True)
class AgentConfig:
    """Runtime settings for one model/provider candidate."""

    name: str
    provider: str
    model: str
    enabled: bool = True

    free: bool | None = None
    provider_type: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None

    base_url: str | None = None
    chat_completions_path: str | None = None
    timeout_seconds: float = 120.0
    max_tokens: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    cooldown_seconds: float = 120.0
    context_window: int | None = None
    coding_score: float | None = None
    reasoning_score: float | None = None
    speed_score: float | None = None
    supports_tools: bool | None = None
    supports_json: bool | None = None
    supports_streaming: bool | None = None
    supports_vision: bool | None = None
    supports_function_calling: bool | None = None
    priority: float = 0.0

    @property
    def resolved_api_key(self) -> str | None:
        """Return the explicit key first, then resolve the configured env var."""

        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env)
        return None


@dataclass(slots=True)
class RouteRule:
    """Keyword-triggered route that maps a request to candidate agents."""

    name: str
    agents: list[str]
    keywords: list[str] = field(default_factory=list)

    def matches(self, text: str) -> bool:
        """Return True when any configured keyword appears in the request text."""

        if not self.keywords:
            return False
        lowered = text.lower()
        return any(keyword.lower() in lowered for keyword in self.keywords)


@dataclass(slots=True)
class HubConfig:
    """Complete server, workspace, routing, and agent configuration."""

    host: str = "127.0.0.1"
    port: int = 8787

    state_dir: Path = Path(".agent-hub/state")
    inbox_dir: Path = Path(".agent-hub/inbox")
    outbox_dir: Path = Path(".agent-hub/outbox")
    archive_dir: Path = Path(".agent-hub/archive")
    workspace_dir: Path = Path(".")

    agent_max_steps: int = 8
    allow_shell_tools: bool = True
    shell_command_policy: str = "allow"
    free_only: bool = True
    enable_load_balancing: bool = True
    auto_enable_available_providers: bool = True
    auto_detect_local_models: bool = True
    local_model_probe_timeout_seconds: float = 0.35
    quota_cooldown_seconds: float = 1800.0
    rate_limit_cooldown_seconds: float = 300.0

    default_route: list[str] = field(default_factory=list)
    routes: list[RouteRule] = field(default_factory=list)
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    group_roles: dict[str, str] = field(default_factory=dict)
    initialization_report: dict[str, Any] = field(default_factory=dict)

    include_raw_responses: bool = False
    expose_routing_details: bool = False

    def ensure_dirs(self) -> None:
        """Create all local persistence folders required by the hub."""

        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)


def load_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    create_if_missing: bool = True,
    auto_detect: bool = True,
) -> HubConfig:
    """Load JSON config, creating and runtime-initializing defaults when absent."""

    config_path = Path(path)
    created_default_config = False
    if not config_path.exists():
        config = free_local_config()
        if create_if_missing:
            write_default_config(config_path, config)
            created_default_config = True
    else:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        config = config_from_dict(raw)

    if auto_detect:
        from .discovery import auto_configure_config

        _resolve_config_paths(config, config_path.parent)
        config.initialization_report = auto_configure_config(config)
    else:
        _resolve_config_paths(config, config_path.parent)
    if created_default_config:
        config.initialization_report["created_default_config"] = True
    config.ensure_dirs()
    return config


def write_default_config(path: str | Path, config: HubConfig | None = None) -> None:
    """Write the default editable config JSON to disk if initialization needs it."""

    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = config_to_dict(config or free_local_config())
    data["cloud_control_selection"] = {
        "route_mode": "ollama-cloud",
        "api_key_models_enabled": False,
    }
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _ollama_cloud_agent(name: str, model: str) -> AgentConfig:
    """Build a shared Ollama OpenAI-compatible cloud agent definition."""

    return AgentConfig(
        name=name,
        provider="openai-compatible",
        provider_type="ollama-cloud",
        model=model,
        base_url=os.environ.get("AGENT_HUB_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        free=True,
        timeout_seconds=180.0,
        max_tokens=4096,
        cooldown_seconds=10.0,
        context_window=128_000,
        supports_json=True,
        supports_streaming=True,
    )


def free_local_config() -> HubConfig:
    """Starter config with Ollama-cloud control and explicit local control."""

    local_model = os.environ.get("AGENT_HUB_LOCAL_MODEL", "local-model")
    local_base_url = os.environ.get("AGENT_HUB_LOCAL_BASE_URL", "http://127.0.0.1:8000")
    local_max_tokens = _env_int("AGENT_HUB_LOCAL_MAX_TOKENS", 4096)
    local_context_window = _env_int("AGENT_HUB_LOCAL_CONTEXT_WINDOW", 8192)
    local_timeout = _env_float("AGENT_HUB_LOCAL_TIMEOUT_SECONDS", 15.0)

    agents = {
        "local-research": AgentConfig(
            name="local-research",
            provider="local-research",
            provider_type="local-research",
            model="local-extractive-research",
            free=True,
            timeout_seconds=20.0,
            cooldown_seconds=5.0,
            context_window=1_000_000,
        ),
        "ollama-kimi-cloud": _ollama_cloud_agent("ollama-kimi-cloud", "kimi-k2.6:cloud"),
        "ollama-glm-cloud": _ollama_cloud_agent("ollama-glm-cloud", "glm-5.1:cloud"),
        "ollama-qwen-cloud": _ollama_cloud_agent("ollama-qwen-cloud", "qwen3.5:cloud"),
        "ollama-nemotron-cloud": _ollama_cloud_agent(
            "ollama-nemotron-cloud",
            "nemotron-3-super:cloud",
        ),
        "ollama-gemma-cloud": _ollama_cloud_agent("ollama-gemma-cloud", "gemma4:31b-cloud"),
        "custom-local": AgentConfig(
            name="custom-local",
            provider="openai-compatible",
            provider_type="openai-compatible",
            model=local_model,
            base_url=local_base_url,
            free=True,
            timeout_seconds=local_timeout,
            max_tokens=local_max_tokens,
            cooldown_seconds=20.0,
            context_window=local_context_window,
            coding_score=0.5,
            reasoning_score=0.5,
            supports_json=True,
            supports_streaming=True,
        ),
        "ollama-qwen-coder": AgentConfig(
            name="ollama-qwen-coder",
            provider="openai-compatible",
            provider_type="openai-compatible",
            model=os.environ.get("AGENT_HUB_OLLAMA_CODER_MODEL", "qwen2.5-coder:7b"),
            base_url=os.environ.get("AGENT_HUB_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            free=True,
            timeout_seconds=300.0,
            max_tokens=4096,
            cooldown_seconds=10.0,
            context_window=32_768,
            coding_score=0.75,
            reasoning_score=0.55,
            speed_score=0.55,
            supports_json=True,
            supports_streaming=True,
            supports_tools=True,
            priority=40,
        ),
        "ollama-qwen3": AgentConfig(
            name="ollama-qwen3",
            provider="openai-compatible",
            provider_type="openai-compatible",
            model=os.environ.get("AGENT_HUB_OLLAMA_GENERAL_MODEL", "qwen3:8b"),
            base_url=os.environ.get("AGENT_HUB_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            free=True,
            timeout_seconds=300.0,
            max_tokens=4096,
            cooldown_seconds=10.0,
            context_window=32_768,
            coding_score=0.6,
            reasoning_score=0.65,
            speed_score=0.55,
            supports_json=True,
            supports_streaming=True,
            priority=35,
        ),
        "lm-studio": AgentConfig(
            name="lm-studio",
            provider="openai-compatible",
            provider_type="openai-compatible",
            model=os.environ.get("AGENT_HUB_LM_STUDIO_MODEL", "local-model"),
            base_url=os.environ.get("AGENT_HUB_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234"),
            free=True,
            timeout_seconds=30.0,
            max_tokens=4096,
            cooldown_seconds=10.0,
            context_window=32_768,
            coding_score=0.55,
            reasoning_score=0.5,
            speed_score=0.45,
            supports_json=True,
            supports_streaming=True,
        ),
        "localai": AgentConfig(
            name="localai",
            provider="openai-compatible",
            provider_type="openai-compatible",
            model=os.environ.get("AGENT_HUB_LOCALAI_MODEL", "llama-3.2-1b-instruct:q4_k_m"),
            base_url=os.environ.get("AGENT_HUB_LOCALAI_BASE_URL", "http://127.0.0.1:8080"),
            free=True,
            timeout_seconds=30.0,
            max_tokens=4096,
            cooldown_seconds=10.0,
            context_window=8192,
            coding_score=0.45,
            reasoning_score=0.4,
            speed_score=0.45,
            supports_json=True,
        ),
        "vllm": AgentConfig(
            name="vllm",
            provider="openai-compatible",
            provider_type="openai-compatible",
            model=os.environ.get("AGENT_HUB_VLLM_MODEL", local_model),
            base_url=os.environ.get("AGENT_HUB_VLLM_BASE_URL", "http://127.0.0.1:8000"),
            free=True,
            timeout_seconds=30.0,
            max_tokens=4096,
            cooldown_seconds=10.0,
            context_window=local_context_window,
            coding_score=0.65,
            reasoning_score=0.6,
            speed_score=0.7,
            supports_json=True,
            supports_streaming=True,
            supports_tools=True,
        ),
        "codex": AgentConfig(
            name="codex",
            provider="openai",
            provider_type="openai",
            model=os.environ.get(
                "AGENT_HUB_CODEX_MODEL",
                os.environ.get("AGENT_HUB_OPENAI_MODEL", "gpt-4o-mini"),
            ),
            enabled=False,
            free=True,
            api_key_env=os.environ.get("AGENT_HUB_CODEX_API_KEY_ENV", "OPENAI_API_KEY"),
            timeout_seconds=60.0,
            max_tokens=4096,
            cooldown_seconds=30.0,
            context_window=128_000,
            coding_score=0.75,
            reasoning_score=0.75,
            speed_score=0.65,
            supports_tools=True,
            supports_json=True,
            supports_streaming=True,
            supports_vision=True,
            supports_function_calling=True,
        ),
        "claude": AgentConfig(
            name="claude",
            provider="anthropic",
            provider_type="anthropic",
            model=os.environ.get("AGENT_HUB_CLAUDE_MODEL", "claude-3-5-haiku-latest"),
            enabled=False,
            free=True,
            api_key_env=os.environ.get("AGENT_HUB_CLAUDE_API_KEY_ENV", "ANTHROPIC_API_KEY"),
            timeout_seconds=60.0,
            max_tokens=4096,
            cooldown_seconds=30.0,
            context_window=200_000,
            coding_score=0.75,
            reasoning_score=0.8,
            speed_score=0.6,
            supports_tools=True,
            supports_json=True,
            supports_streaming=True,
            supports_vision=True,
            supports_function_calling=True,
        ),
        "gemini": AgentConfig(
            name="gemini",
            provider="gemini",
            provider_type="gemini",
            model=os.environ.get("AGENT_HUB_GEMINI_MODEL", "gemini-2.0-flash"),
            enabled=False,
            free=True,
            api_key_env=os.environ.get("AGENT_HUB_GEMINI_API_KEY_ENV", "GEMINI_API_KEY"),
            timeout_seconds=60.0,
            max_tokens=4096,
            cooldown_seconds=30.0,
            context_window=1_000_000,
            coding_score=0.75,
            reasoning_score=0.8,
            speed_score=0.7,
            supports_tools=True,
            supports_json=True,
            supports_streaming=True,
            supports_vision=True,
            supports_function_calling=True,
        ),
        "chatgpt": AgentConfig(
            name="chatgpt",
            provider="openai",
            provider_type="openai",
            model=os.environ.get(
                "AGENT_HUB_CHATGPT_MODEL",
                os.environ.get("AGENT_HUB_OPENAI_MODEL", "gpt-4o-mini"),
            ),
            enabled=False,
            free=True,
            api_key_env=os.environ.get("AGENT_HUB_CHATGPT_API_KEY_ENV", "OPENAI_API_KEY"),
            timeout_seconds=60.0,
            max_tokens=4096,
            cooldown_seconds=30.0,
            context_window=128_000,
            coding_score=0.75,
            reasoning_score=0.75,
            speed_score=0.65,
            supports_tools=True,
            supports_json=True,
            supports_streaming=True,
            supports_vision=True,
            supports_function_calling=True,
        ),
        "echo": AgentConfig(
            name="echo",
            provider="echo",
            provider_type="echo",
            model="local-echo",
            free=True,
            cooldown_seconds=1.0,
            context_window=1_000_000,
            speed_score=1.0,
        ),
    }
    return HubConfig(
        workspace_dir=Path("."),
        agent_max_steps=8,
        allow_shell_tools=True,
        shell_command_policy="allow",
        free_only=True,
        auto_enable_available_providers=True,
        auto_detect_local_models=True,
        default_route=default_agent_names(),
        routes=[
            RouteRule(
                name="coding",
                keywords=["code", "bug", "fix", "refactor", "test", "repo"],
                agents=default_agent_names(),
            ),
            RouteRule(
                name="local-agent",
                keywords=["agent", "workspace", "edit", "implement"],
                agents=free_local_agent_names(),
            ),
            RouteRule(
                name="hybrid-agent",
                keywords=[],
                agents=default_agent_names(),
            ),
            RouteRule(
                name="cloud-agent",
                keywords=[],
                agents=cloud_route_agent_names(),
            ),
            RouteRule(
                name="research",
                keywords=["research", "search", "latest", "sources", "web", "news"],
                agents=["local-research", *ollama_cloud_agent_names(), "echo"],
            )
        ],
        agents=agents,
        expose_routing_details=False,
    )


def free_local_agent_names() -> list[str]:
    """Agents that should run from local or user-controlled endpoints."""

    return ["ollama-qwen-coder", "ollama-qwen3", "lm-studio", "vllm", "custom-local", "localai"]


def ollama_cloud_agent_names() -> list[str]:
    """Free Ollama cloud candidates used before hosted API providers."""

    return [
        "ollama-kimi-cloud",
        "ollama-glm-cloud",
        "ollama-qwen-cloud",
        "ollama-nemotron-cloud",
        "ollama-gemma-cloud",
    ]


def cloud_agent_names() -> list[str]:
    """Hosted providers that usually need API key environment variables."""

    return ["codex", "claude", "gemini", "chatgpt"]


def cloud_route_agent_names() -> list[str]:
    """Default cloud route: Ollama cloud first, then echo diagnostics."""

    return [*ollama_cloud_agent_names(), "echo"]


def default_agent_names() -> list[str]:
    """Default route with Ollama cloud agents and no API-key providers."""

    return [
        *ollama_cloud_agent_names(),
        "echo",
    ]


def config_from_dict(raw: dict[str, Any]) -> HubConfig:
    """Convert the JSON-compatible config shape into dataclass instances."""

    agents = {
        item["name"]: AgentConfig(
            name=item["name"],
            provider=item["provider"],
            model=item.get("model", item["name"]),
            enabled=item.get("enabled", True),
            free=item.get("free"),
            provider_type=item.get("provider_type"),
            api_key_env=item.get("api_key_env"),
            api_key=item.get("api_key"),
            base_url=_expand_env_string(item.get("base_url")),
            chat_completions_path=item.get("chat_completions_path"),
            timeout_seconds=float(item.get("timeout_seconds", 120.0)),
            max_tokens=item.get("max_tokens"),
            headers={str(key): _expand_env_string(value) for key, value in dict(item.get("headers", {})).items()},
            cooldown_seconds=float(item.get("cooldown_seconds", 120.0)),
            context_window=item.get("context_window"),
            coding_score=_optional_float(item.get("coding_score")),
            reasoning_score=_optional_float(item.get("reasoning_score")),
            speed_score=_optional_float(item.get("speed_score")),
            supports_tools=_optional_bool(item.get("supports_tools")),
            supports_json=_optional_bool(item.get("supports_json")),
            supports_streaming=_optional_bool(item.get("supports_streaming")),
            supports_vision=_optional_bool(item.get("supports_vision")),
            supports_function_calling=_optional_bool(item.get("supports_function_calling")),
            priority=float(item.get("priority", 0.0)),
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
        allow_shell_tools=_bool_with_default(raw.get("allow_shell_tools"), True),
        shell_command_policy=_normalize_shell_command_policy(
            raw.get("shell_command_policy", raw.get("shell_tools_policy", "allow"))
        ),
        free_only=_bool_with_default(raw.get("free_only"), True),
        enable_load_balancing=_bool_with_default(raw.get("enable_load_balancing"), True),
        auto_enable_available_providers=_bool_with_default(
            raw.get("auto_enable_available_providers"),
            True,
        ),
        auto_detect_local_models=_bool_with_default(raw.get("auto_detect_local_models"), True),
        local_model_probe_timeout_seconds=float(
            raw.get("local_model_probe_timeout_seconds", 0.35)
        ),
        quota_cooldown_seconds=float(raw.get("quota_cooldown_seconds", 1800.0)),
        rate_limit_cooldown_seconds=float(raw.get("rate_limit_cooldown_seconds", 300.0)),
        default_route=list(raw.get("default_route", agents.keys())),
        routes=routes,
        agents=agents,
        group_roles=dict(raw.get("group_roles", {})),
        include_raw_responses=_bool_with_default(raw.get("include_raw_responses"), False),
        expose_routing_details=_bool_with_default(raw.get("expose_routing_details"), False),
    )


def is_free_agent(agent: AgentConfig) -> bool:
    """Infer whether an agent is free/local enough for free_only routing."""

    if agent.free is not None:
        return bool(agent.free)

    provider = agent.provider.lower()
    provider_type = (agent.provider_type or agent.provider).lower()
    if provider == "echo":
        return True
    if normalize_provider(provider) == "local-research":
        return True
    if provider_type == "ollama-cloud":
        return True
    if normalize_provider(provider) != "openai-compatible":
        return False
    return _is_local_or_private_url(agent.base_url)


def normalize_provider(provider: str) -> str:
    """Map common provider aliases to the internal provider names."""

    lowered = provider.lower()
    if lowered in OPENAI_COMPATIBLE_PROVIDER_TYPES:
        return "openai-compatible"
    if lowered in {"codex", "chatgpt", "openai-chat", "gpt"}:
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
    """Convert HubConfig back to a JSON-serializable dictionary."""

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
        "shell_command_policy": config.shell_command_policy,
        "free_only": config.free_only,
        "enable_load_balancing": config.enable_load_balancing,
        "auto_enable_available_providers": config.auto_enable_available_providers,
        "auto_detect_local_models": config.auto_detect_local_models,
        "local_model_probe_timeout_seconds": config.local_model_probe_timeout_seconds,
        "quota_cooldown_seconds": config.quota_cooldown_seconds,
        "rate_limit_cooldown_seconds": config.rate_limit_cooldown_seconds,
        "include_raw_responses": config.include_raw_responses,
        "expose_routing_details": config.expose_routing_details,
        "default_route": config.default_route,
        "group_roles": config.group_roles,
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
                    "provider_type": agent.provider_type,
                    "model": agent.model,
                    "enabled": agent.enabled,
                    "free": agent.free,
                    "api_key_env": agent.api_key_env,
                    "api_key": agent.api_key,
                    "base_url": agent.base_url,
                    "chat_completions_path": agent.chat_completions_path,
                    "timeout_seconds": agent.timeout_seconds,
                    "max_tokens": agent.max_tokens,
                    "headers": agent.headers,
                    "cooldown_seconds": agent.cooldown_seconds,
                    "context_window": agent.context_window,
                    "coding_score": agent.coding_score,
                    "reasoning_score": agent.reasoning_score,
                    "speed_score": agent.speed_score,
                    "supports_tools": agent.supports_tools,
                    "supports_json": agent.supports_json,
                    "supports_streaming": agent.supports_streaming,
                    "supports_vision": agent.supports_vision,
                    "supports_function_calling": agent.supports_function_calling,
                    "priority": agent.priority,
                }
            )
            for agent in config.agents.values()
        ],
    }


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    """Remove empty optional values before writing config JSON."""

    return {
        key: value
        for key, value in data.items()
        if value is not None and value != {} and value != []
    }


def _resolve_config_paths(config: HubConfig, base_dir: Path) -> None:
    """Resolve workspace/state paths relative to the config file location."""

    base = base_dir.resolve()
    config.state_dir = _resolve_config_path(config.state_dir, base)
    config.inbox_dir = _resolve_config_path(config.inbox_dir, base)
    config.outbox_dir = _resolve_config_path(config.outbox_dir, base)
    config.archive_dir = _resolve_config_path(config.archive_dir, base)
    config.workspace_dir = _resolve_config_path(config.workspace_dir, base)


def _resolve_config_path(path: Path, base: Path) -> Path:
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        return expanded
    return (base / expanded).resolve()


def _is_local_or_private_url(value: str | None) -> bool:
    """Return True when a URL targets a local or private-network host."""

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
    """Read an integer env var, falling back when unset or invalid."""

    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    """Read a float env var, falling back when unset or invalid."""

    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _bool_with_default(value: Any, default: bool) -> bool:
    parsed = _optional_bool(value)
    return default if parsed is None else parsed


def _normalize_shell_command_policy(value: Any) -> str:
    text = str(value or "allow").strip().lower()
    if text in {"ask", "confirm", "prompt"}:
        return "ask"
    if text in {"deny", "disabled", "disable", "off", "false", "0"}:
        return "deny"
    return "allow"


def _expand_env_string(value: Any) -> Any:
    """Expand ${VAR} and ${VAR:-fallback} strings in JSON config values."""

    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        expression = match.group(1)
        if ":-" in expression:
            name, fallback = expression.split(":-", 1)
            return os.environ.get(name, fallback)
        return os.environ.get(expression, match.group(0))

    return re.sub(r"\$\{([^}]+)\}", replace, os.path.expandvars(value))
