from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any

from .config import (
    AgentConfig,
    HubConfig,
    RouteRule,
    _expand_env_string,
    _is_local_or_private_url,
    is_free_agent,
    normalize_provider,
)
from .provider_presets import FREE_PROVIDER_PRESETS, agent_dict_from_preset


PLACEHOLDER_MODELS = {
    "",
    "local-model",
    "your-gemma-model",
    "replace-with-openai-compatible-replicate-model",
    "replace-with-openai-compatible-kluster-model",
}


def auto_configure_config(config: HubConfig) -> dict[str, Any]:
    """Enable keyed providers and fill local model IDs without requiring edits."""

    report: dict[str, Any] = {
        "created_default_config": False,
        "added_provider_presets": [],
        "enabled_from_environment": [],
        "detected_local_models": {},
        "selected_local_models": {},
        "probe_errors": {},
    }
    if config.auto_enable_available_providers:
        _add_keyed_provider_presets(config, report)
        _enable_keyed_agents(config, report)
        _refresh_free_cloud_routes(config, report)
    if config.auto_detect_local_models:
        _detect_local_models(config, report)
    return report


def fetch_openai_models(
    base_url: str,
    *,
    timeout: float = 0.35,
    api_key: str | None = None,
    headers: dict[str, str] | None = None,
) -> list[str]:
    """Fetch `/v1/models` from an OpenAI-compatible endpoint."""

    request_headers = {"Accept": "application/json", **(headers or {})}
    if api_key and not any(key.lower() in {"authorization", "x-api-key", "api-key"} for key in request_headers):
        request_headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        _openai_url(base_url, "/v1/models"),
        headers=request_headers,
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=max(0.05, timeout)) as response:
        text = response.read().decode("utf-8")
    data = json.loads(text) if text else {}
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return sorted(
        item["id"]
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    )


def _enable_keyed_agents(config: HubConfig, report: dict[str, Any]) -> None:
    for agent in config.agents.values():
        if agent.enabled or not agent.api_key_env or not agent.resolved_api_key:
            continue
        provider = normalize_provider(agent.provider)
        if provider in {"openai", "anthropic", "gemini", "openai-compatible"}:
            agent.enabled = True
            report["enabled_from_environment"].append(
                {
                    "agent": agent.name,
                    "provider": agent.provider,
                    "provider_type": agent.provider_type,
                    "api_key_env": agent.api_key_env,
                }
            )


def _add_keyed_provider_presets(config: HubConfig, report: dict[str, Any]) -> None:
    for preset in FREE_PROVIDER_PRESETS:
        if preset.name in config.agents or preset.model in PLACEHOLDER_MODELS:
            continue
        data = agent_dict_from_preset(preset, enabled=True)
        api_key_env = data.get("api_key_env")
        if not isinstance(api_key_env, str) or not api_key_env or not _env_present(api_key_env):
            continue
        base_url = _expand_env_string(data.get("base_url"))
        if not isinstance(base_url, str) or not base_url or "${" in base_url:
            continue
        agent = AgentConfig(
            name=str(data["name"]),
            provider=str(data["provider"]),
            provider_type=str(data.get("provider_type") or data["provider"]),
            model=str(data["model"]),
            enabled=True,
            free=bool(data.get("free", True)),
            api_key_env=api_key_env,
            base_url=base_url,
            chat_completions_path=data.get("chat_completions_path"),
            timeout_seconds=float(data.get("timeout_seconds", 120.0)),
            max_tokens=data.get("max_tokens"),
            headers={str(key): str(_expand_env_string(value)) for key, value in dict(data.get("headers", {})).items()},
            cooldown_seconds=float(data.get("cooldown_seconds", 120.0)),
            context_window=data.get("context_window"),
            coding_score=_optional_float(data.get("coding_score")),
            reasoning_score=_optional_float(data.get("reasoning_score")),
            speed_score=_optional_float(data.get("speed_score")),
            supports_tools=_optional_bool(data.get("supports_tools")),
            supports_json=_optional_bool(data.get("supports_json")),
            supports_streaming=_optional_bool(data.get("supports_streaming")),
            supports_vision=_optional_bool(data.get("supports_vision")),
            supports_function_calling=_optional_bool(data.get("supports_function_calling")),
            priority=float(data.get("priority", 0.0)),
        )
        config.agents[agent.name] = agent
        report["added_provider_presets"].append(
            {
                "agent": agent.name,
                "provider_type": agent.provider_type,
                "model": agent.model,
                "api_key_env": agent.api_key_env,
            }
        )


def _refresh_free_cloud_routes(config: HubConfig, report: dict[str, Any]) -> None:
    candidates = sorted(
        [agent for agent in config.agents.values() if _is_free_cloud_agent(agent)],
        key=lambda agent: (-_route_priority(agent), agent.name),
    )
    names = [agent.name for agent in candidates]
    if not names:
        return
    echo = ["echo"] if "echo" in config.agents else []
    _merge_route_names(config, "cloud-agent", [*names, *echo])
    _merge_route_names(config, "hybrid-agent", [*names, *_enabled_free_local_agent_names(config), *echo])
    _merge_route_names(config, "coding", [*names, *echo])
    config.default_route = _merge_names(config.default_route, [*names, *echo])
    report["free_cloud_route_agents"] = names


def _merge_route_names(config: HubConfig, route_name: str, agent_names: list[str]) -> None:
    route = next((item for item in config.routes if item.name == route_name), None)
    if route is None:
        route = RouteRule(name=route_name, agents=[])
        config.routes.append(route)
    route.agents = _merge_names(route.agents, agent_names)


def _merge_names(existing: list[str], additions: list[str]) -> list[str]:
    result = [name for name in existing if name]
    seen = set(result)
    insert_at = result.index("echo") if "echo" in result else len(result)
    for name in additions:
        if not name or name in seen:
            continue
        if name == "echo":
            result.append(name)
        else:
            result.insert(insert_at, name)
            insert_at += 1
        seen.add(name)
    return result


def _enabled_free_local_agent_names(config: HubConfig) -> list[str]:
    return [
        agent.name
        for agent in config.agents.values()
        if agent.enabled and is_free_agent(agent) and _is_local_openai_agent(agent)
    ]


def _is_free_cloud_agent(agent: AgentConfig) -> bool:
    if not agent.enabled or not is_free_agent(agent) or agent.provider == "echo":
        return False
    if normalize_provider(agent.provider) == "local-research":
        return False
    provider_type = (agent.provider_type or agent.provider).lower()
    if provider_type == "ollama-cloud":
        return True
    provider = normalize_provider(agent.provider)
    if provider in {"openai", "anthropic", "gemini"}:
        return True
    if provider == "openai-compatible":
        return bool(agent.base_url and not _is_local_or_private_url(agent.base_url))
    return False


def _is_local_openai_agent(agent: AgentConfig) -> bool:
    return (
        normalize_provider(agent.provider) == "openai-compatible"
        and (agent.provider_type or "").lower() != "ollama-cloud"
        and bool(agent.base_url and _is_local_or_private_url(agent.base_url))
    )


def _route_priority(agent: AgentConfig) -> float:
    score = float(agent.priority or 0.0)
    if agent.supports_tools or agent.supports_function_calling:
        score += 12
    score += float(agent.coding_score or 0.0) * 6
    score += float(agent.reasoning_score or 0.0) * 4
    score += float(agent.speed_score or 0.0) * 2
    return score


def _detect_local_models(config: HubConfig, report: dict[str, Any]) -> None:
    seen_base_urls: dict[str, list[str]] = {}
    timeout = max(0.05, float(config.local_model_probe_timeout_seconds or 0.35))
    for agent in config.agents.values():
        if not _should_probe_local_agent(agent):
            continue
        assert agent.base_url is not None
        try:
            models = seen_base_urls.get(agent.base_url)
            if models is None:
                models = fetch_openai_models(
                    agent.base_url,
                    timeout=timeout,
                    api_key=agent.resolved_api_key,
                    headers=agent.headers,
                )
                seen_base_urls[agent.base_url] = models
        except (OSError, TimeoutError, socket.timeout, urllib.error.URLError, json.JSONDecodeError) as exc:
            report["probe_errors"][agent.name] = _short_error(exc)
            continue

        report["detected_local_models"][agent.name] = models
        if not models:
            continue
        selected = _select_local_model(agent, models)
        if selected and selected != agent.model:
            agent.model = selected
            report["selected_local_models"][agent.name] = selected
        agent.enabled = True


def _should_probe_local_agent(agent: AgentConfig) -> bool:
    if normalize_provider(agent.provider) != "openai-compatible":
        return False
    if (agent.provider_type or "").lower() == "ollama-cloud":
        return False
    if not agent.base_url or not _is_local_or_private_url(agent.base_url):
        return False
    return is_free_agent(agent)


def _select_local_model(agent: AgentConfig, models: list[str]) -> str:
    if agent.model in models and agent.model not in PLACEHOLDER_MODELS:
        return agent.model
    lowered_name = agent.name.lower()
    coding = any(marker in lowered_name for marker in ("coder", "code", "dev", "fix"))
    preferred_markers = (
        ("coder", "code", "qwen", "deepseek", "starcoder", "granite")
        if coding
        else ("qwen", "llama", "gemma", "mistral", "phi", "deepseek")
    )
    return sorted(
        models,
        key=lambda model: (
            -sum(marker in model.lower() for marker in preferred_markers),
            len(model),
            model.lower(),
        ),
    )[0]


def _openai_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        return f"{base}{path[3:]}"
    return f"{base}{path}"


def _short_error(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    text = str(reason if reason is not None else exc)
    return text[:240]


def _env_present(name: str) -> bool:
    value = os.environ.get(name)
    return isinstance(value, str) and bool(value.strip())


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
