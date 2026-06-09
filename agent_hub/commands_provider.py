from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .adaptive import estimate_known_cost_usd
from .application import DiagnosticsApplicationService
from .config import (
    _is_local_or_private_url,
    cloud_route_agent_names,
    config_to_dict,
    default_agent_names,
    free_local_config,
    agent_allowed_by_cost_policy,
    is_free_agent,
    load_config,
    normalize_provider,
)
from .core.router import AgentRouter, RouterError
from .discovery import fetch_openai_models
from .evaluation import BenchmarkResult, BenchmarkRunner, ProviderScoreStore, _score_text, default_benchmark_tasks
from .evaluation.benchmark_suite import BenchmarkSuiteRunner
from .evaluation.proof_benchmark import BenchmarkProofRunner
from .explainability import explain_route_body, format_route_explanation
from .learning_proof import format_route_history, route_history_body
from .measurement import estimate_named_baselines
from .payloads import request_from_payload
from .permissions import mark_trusted_approval
from .proof_artifacts import (
    benchmark_evolution_body,
    benchmark_share_card_body,
    case_study_body,
    format_benchmark_card,
    format_benchmark_evolution,
    format_case_study_markdown,
    format_route_replay,
    replay_route_body,
)
from .provider_presets import (
    FREE_PROVIDER_PRESETS,
    agent_dict_from_preset,
    provider_metadata,
    preset_rows,
)
from .commands_config import (
    _agent_name_from_provider_model,
    _append_agent_to_route,
    _cloud_example_agents,
    _cloud_provider_defaults,
    _drop_empty,
    _ensure_cloud_routes,
    _load_or_default_config_dict,
    _merge_agent_examples,
    _move_agent_to_front,
    _upsert_agent,
    _write_config_dict,
)
from .output import _print_route_error, _print_table


ROUTING_PRESETS: dict[str, dict[str, Any]] = {
    "cheap-local": {
        "name": "cheap-local",
        "label": "Cheap local mode",
        "description": "Prefer free local or user-controlled endpoints.",
        "selector": "cheap-local",
        "free_only": True,
        "approval_mode": "ask",
        "free_first": True,
    },
    "cheap": {
        "name": "cheap",
        "label": "Cheap mode",
        "description": "Prefer free, low-cost local or user-controlled endpoints.",
        "selector": "cheap-local",
        "free_only": True,
        "approval_mode": "ask",
        "free_first": True,
    },
    "free-only": {
        "name": "free-only",
        "label": "Free only mode",
        "description": "Disable Codex CLI, paid API-key models, and other non-free fallbacks.",
        "selector": "free-only",
        "free_only": True,
        "approval_mode": "safe",
        "free_first": True,
    },
    "token-saver": {
        "name": "token-saver",
        "label": "Token saver mode",
        "description": "Let confident free models handle safe work while keeping Codex as fallback.",
        "selector": "fallback-safe",
        "free_only": False,
        "approval_mode": "safe",
        "free_first": True,
    },
    "token-safe": {
        "name": "token-safe",
        "label": "Token safe mode",
        "description": "Let confident free models handle safe work while keeping Codex as fallback.",
        "selector": "fallback-safe",
        "free_only": False,
        "approval_mode": "safe",
        "free_first": True,
    },
    "best-coding": {
        "name": "best-coding",
        "label": "Best coding mode",
        "description": "Prefer tool-capable agents with strong coding scores.",
        "selector": "best-coding",
        "free_only": False,
        "approval_mode": "ask",
        "free_first": False,
    },
    "private": {
        "name": "private",
        "label": "Private mode",
        "description": "Use local/private endpoints only.",
        "selector": "private",
        "free_only": True,
        "approval_mode": "ask",
        "free_first": True,
    },
    "local-only": {
        "name": "local-only",
        "label": "Local only mode",
        "description": "Use only local model servers and built-in local providers.",
        "selector": "private",
        "free_only": True,
        "approval_mode": "ask",
        "free_first": True,
    },
    "fast": {
        "name": "fast",
        "label": "Fast mode",
        "description": "Prefer the lowest-latency configured agents.",
        "selector": "fastest",
        "free_only": False,
        "approval_mode": "ask",
        "free_first": False,
    },
    "fastest": {
        "name": "fastest",
        "label": "Fastest mode",
        "description": "Prefer the lowest-latency configured agents.",
        "selector": "fastest",
        "free_only": False,
        "approval_mode": "ask",
        "free_first": False,
    },
    "fallback-safe": {
        "name": "fallback-safe",
        "label": "Fallback-safe mode",
        "description": "Keep broad fallback enabled while using safe approvals.",
        "selector": "fallback-safe",
        "free_only": False,
        "approval_mode": "safe",
        "free_first": True,
    },
}

LOCAL_PROVIDER_TYPES = {
    "echo",
    "local-research",
    "lm-studio",
    "localai",
    "llama-cpp",
    "ollama",
    "ollama-local",
    "vllm",
}

LOCAL_URL_PREFIXES = (
    "http://127.0.0.1",
    "https://127.0.0.1",
    "http://localhost",
    "https://localhost",
    "http://[::1]",
    "https://[::1]",
)


def _enable_cloud_provider(
    path: str,
    *,
    provider: str,
    model: str,
    route: str,
    api_key_env: str | None,
    paid: bool = False,
) -> int:
    config_path = Path(path)
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            print(f"{config_path} does not contain a JSON object.")
            return 1
    else:
        data = config_to_dict(free_local_config())
        _merge_agent_examples(data, _cloud_example_agents())

    if paid:
        data["free_only"] = False
    _ensure_cloud_routes(data)

    agent_name, provider_name, default_env = _cloud_provider_defaults(provider)
    agents = data.setdefault("agents", [])
    if not isinstance(agents, list):
        print("Config field 'agents' must be a list.")
        return 1

    agent = next(
        (item for item in agents if isinstance(item, dict) and item.get("name") == agent_name),
        None,
    )
    if agent is None:
        agent = {
            "name": agent_name,
            "provider": provider_name,
            "free": not paid,
        }
        agents.append(agent)

    agent.update(
        {
            "provider": provider_name,
            "model": model,
            "enabled": True,
            "free": not paid,
            "api_key_env": api_key_env or default_env,
        }
    )

    _move_agent_to_front(data, route, agent_name)
    if route in {"cloud-agent", "hybrid-agent"}:
        data["cloud_control_selection"] = {
            "route_mode": "api-key",
            "api_key_models_enabled": True,
        }
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Enabled {agent_name} on route {route} in {config_path}.")
    print(f"Set {agent['api_key_env']} before starting Agent-Hub.")
    if not paid:
        print("Provider is marked free=true, so it remains eligible while free_only is enabled.")
    print("Restart the Agent-Hub server if it is already running.")
    return 0


def _add_provider(
    path: str,
    *,
    provider_type: str,
    model: str,
    name: str | None,
    route: str,
    base_url: str | None,
    api_key_env: str | None,
    enabled: bool,
    paid: bool,
) -> int:
    config_path = Path(path)
    data = _load_or_default_config_dict(config_path)
    metadata = provider_metadata(provider_type)
    normalized_provider_type = provider_type.lower()
    agent_name = name or _agent_name_from_provider_model(normalized_provider_type, model)
    provider_name = metadata.provider if metadata else "openai-compatible"
    agent = {
        "name": agent_name,
        "provider": provider_name,
        "provider_type": normalized_provider_type,
        "model": model,
        "enabled": enabled,
        "free": not paid,
        "api_key_env": api_key_env or (metadata.api_key_env if metadata else None),
        "base_url": base_url or (metadata.base_url if metadata else None),
        "headers": dict(metadata.default_headers) if metadata else {},
        "chat_completions_path": metadata.chat_completions_path if metadata else None,
        "timeout_seconds": 120,
        "cooldown_seconds": 120,
        "supports_tools": metadata.supports_tools if metadata else None,
        "supports_json": metadata.supports_json if metadata else None,
        "supports_streaming": metadata.supports_streaming if metadata else None,
        "supports_vision": metadata.supports_vision if metadata else None,
        "supports_function_calling": metadata.supports_function_calling if metadata else None,
    }
    agent = _drop_empty(agent)
    _upsert_agent(data, agent)
    _ensure_cloud_routes(data)
    _move_agent_to_front(data, route, agent_name)
    if paid:
        data["free_only"] = False
    _write_config_dict(config_path, data)
    print(f"Added {agent_name} ({provider_type}) to {config_path}.")
    if agent.get("api_key_env"):
        print(f"Set {agent['api_key_env']} before enabling or routing to it.")
    if not agent.get("base_url"):
        print("No base_url is known for this provider type; edit the config before enabling it.")
    return 0


def _add_free_presets(path: str, *, route: str, enabled: bool) -> int:
    config_path = Path(path)
    data = _load_or_default_config_dict(config_path)
    _ensure_cloud_routes(data)
    added: list[str] = []
    for preset in FREE_PROVIDER_PRESETS:
        agent = agent_dict_from_preset(preset, enabled=enabled)
        if _upsert_agent(data, agent, replace_existing=False):
            added.append(agent["name"])
        _append_agent_to_route(data, route, agent["name"])
    _write_config_dict(config_path, data)
    print(f"Merged {len(added)} free provider preset(s) into {config_path}.")
    if added:
        print("Added: " + ", ".join(added))
    print("Preset model IDs are editable; if a free model disappears, change or disable that agent.")
    return 0


def _routing_preset_rows() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "label": preset["label"],
            "free_only": preset["free_only"],
            "approval_mode": preset["approval_mode"],
            "description": preset["description"],
        }
        for name, preset in ROUTING_PRESETS.items()
    ]


def _apply_routing_preset(path: str, preset_name: str | None, *, as_json: bool) -> int:
    preset = _routing_preset_from_name(preset_name)
    if preset is None:
        known = ", ".join(ROUTING_PRESETS)
        if preset_name:
            print(f"Unknown routing preset {preset_name!r}. Known presets: {known}.")
        else:
            print(f"Choose a routing preset: {known}.")
        return 2

    config_path = Path(path)
    data = _load_or_default_config_dict(config_path)
    agent_names = _select_routing_preset_agents(data, preset)
    if not agent_names:
        print("No configured agents are available for that preset.")
        return 1

    data["default_route"] = agent_names
    data["free_only"] = bool(preset["free_only"])
    data["approval_mode"] = str(preset["approval_mode"])
    routing = data.setdefault("routing", {})
    if isinstance(routing, dict):
        routing["auto_failover"] = True
        routing["free_first"] = bool(preset["free_first"])
        if preset["name"] == "free-only":
            data["disable_non_free_models"] = True
            routing["token_saver_enabled"] = False
        if preset["name"] in {"token-saver", "token-safe"}:
            routing["token_saver_enabled"] = True
            routing["token_saver_confidence_threshold"] = 0.74
            routing["token_saver_max_productivity_loss"] = 0.08
            routing["max_provider_attempts"] = max(4, int(routing.get("max_provider_attempts") or 4))
        if preset["name"] in {"fallback-safe", "token-saver", "token-safe"}:
            routing["max_provider_attempts"] = max(3, int(routing.get("max_provider_attempts") or 3))
    if preset["name"] in {"private", "local-only"}:
        data["auto_enable_available_providers"] = False
    if preset["name"] == "free-only":
        selection = data.setdefault("cloud_control_selection", {})
        if isinstance(selection, dict):
            selection["api_key_models_enabled"] = False
            selection["disable_non_free_models"] = True
        _disable_non_free_config_agents(data)

    route_names = ["cloud-agent", "coding", "hybrid-agent"]
    if preset["name"] == "free-only":
        route_names.extend(["codex-cli", "research"])
    for route_name in route_names:
        _replace_route_agents(data, route_name, agent_names)
    if preset["name"] in {"cheap-local", "private", "local-only"}:
        _replace_route_agents(data, "local-agent", agent_names)

    _write_config_dict(config_path, data)
    result = {
        "preset": preset["name"],
        "config": str(config_path),
        "default_route": agent_names,
        "free_only": data["free_only"],
        "approval_mode": data["approval_mode"],
    }
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Applied {preset['label']} to {config_path}.")
        print("default_route: " + ", ".join(agent_names))
        print(f"free_only: {data['free_only']}")
        print(f"approval_mode: {data['approval_mode']}")
    return 0


def _routing_preset_from_name(name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    key = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if key.endswith("-mode"):
        key = key[: -len("-mode")]
    return ROUTING_PRESETS.get(key)


def _select_routing_preset_agents(data: dict[str, Any], preset: dict[str, Any]) -> list[str]:
    raw_agents = data.get("agents", [])
    if not isinstance(raw_agents, list):
        return []
    agents = [agent for agent in raw_agents if isinstance(agent, dict) and isinstance(agent.get("name"), str)]
    enabled = [agent for agent in agents if _agent_enabled(agent)]
    selector = str(preset["selector"])
    candidates = agents if selector == "free-only" else enabled or agents

    if selector == "private":
        selected = [agent for agent in candidates if _agent_is_private(agent)]
    elif selector == "cheap-local":
        selected = [agent for agent in candidates if _agent_is_free(agent) and _agent_is_private(agent)]
    elif selector == "free-only":
        selected = [agent for agent in candidates if _agent_is_strict_free(agent)]
    elif selector == "best-coding":
        selected = sorted(candidates, key=_coding_agent_rank, reverse=True)
    elif selector == "fastest":
        selected = sorted(candidates, key=_speed_agent_rank, reverse=True)
    elif selector == "fallback-safe":
        selected = sorted(candidates, key=_fallback_safe_agent_rank, reverse=True)
    else:
        selected = candidates

    if not selected and selector != "free-only":
        selected = sorted(candidates, key=_fallback_safe_agent_rank, reverse=True)
    names: list[str] = []
    for agent in selected:
        name = str(agent.get("name"))
        if name not in names:
            names.append(name)
    return names


def _replace_route_agents(data: dict[str, Any], route_name: str, agent_names: list[str]) -> None:
    routes = data.setdefault("routes", [])
    if not isinstance(routes, list):
        data["routes"] = routes = []
    route = next(
        (item for item in routes if isinstance(item, dict) and item.get("name") == route_name),
        None,
    )
    if route is None:
        route = {"name": route_name, "keywords": _default_route_keywords(route_name), "agents": []}
        routes.append(route)
    route["agents"] = list(agent_names)


def _default_route_keywords(route_name: str) -> list[str]:
    if route_name == "coding":
        return ["code", "bug", "fix", "refactor", "test", "repo"]
    if route_name == "local-agent":
        return ["agent", "workspace", "edit", "implement"]
    return []


def _agent_enabled(agent: dict[str, Any]) -> bool:
    return agent.get("enabled", True) is not False


def _agent_is_free(agent: dict[str, Any]) -> bool:
    return agent.get("free", True) is not False


def _agent_is_strict_free(agent: dict[str, Any]) -> bool:
    name = str(agent.get("name") or "").lower()
    provider = normalize_provider(str(agent.get("provider") or ""))
    provider_type = str(agent.get("provider_type") or agent.get("provider") or "").lower()
    if name in {"codex", "codex-cli", "chatgpt", "claude", "gemini"}:
        return False
    if provider in {"openai", "anthropic", "gemini", "codex-cli"}:
        return False
    if provider_type in {"openai", "anthropic", "gemini", "codex-cli"}:
        return False
    if provider in {"echo", "local-research"}:
        return True
    if provider_type in LOCAL_PROVIDER_TYPES or provider in LOCAL_PROVIDER_TYPES:
        return True
    if provider_type == "ollama-cloud" or name.endswith("-cloud"):
        return True
    base_url = str(agent.get("base_url") or "").lower()
    if base_url.startswith(LOCAL_URL_PREFIXES):
        return True
    return agent.get("free") is True


def _disable_non_free_config_agents(data: dict[str, Any]) -> None:
    agents = data.get("agents")
    if not isinstance(agents, list):
        return
    for agent in agents:
        if isinstance(agent, dict) and not _agent_is_strict_free(agent):
            agent["enabled"] = False
            agent["free"] = False


def _agent_is_private(agent: dict[str, Any]) -> bool:
    provider_type = str(agent.get("provider_type") or "").lower()
    provider = str(agent.get("provider") or "").lower()
    name = str(agent.get("name") or "").lower()
    if provider_type == "ollama-cloud" or name.endswith("-cloud"):
        return False
    if provider_type in LOCAL_PROVIDER_TYPES or provider in LOCAL_PROVIDER_TYPES:
        return True
    base_url = str(agent.get("base_url") or "").lower()
    return base_url.startswith(LOCAL_URL_PREFIXES)


def _coding_agent_rank(agent: dict[str, Any]) -> tuple[float, float, float, float, float]:
    return (
        _safe_float(agent.get("coding_score")),
        1.0 if agent.get("supports_tools") or agent.get("supports_function_calling") else 0.0,
        _safe_float(agent.get("reasoning_score")),
        _safe_float(agent.get("priority")),
        _safe_float(agent.get("context_window")),
    )


def _speed_agent_rank(agent: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        _safe_float(agent.get("speed_score")),
        _safe_float(agent.get("priority")),
        1.0 if _agent_is_private(agent) else 0.0,
        _safe_float(agent.get("coding_score")),
    )


def _fallback_safe_agent_rank(agent: dict[str, Any]) -> tuple[float, float, float, float, float]:
    return (
        1.0 if _agent_is_free(agent) else 0.0,
        1.0 if _agent_is_private(agent) else 0.0,
        _safe_float(agent.get("priority")),
        _safe_float(agent.get("coding_score")),
        _safe_float(agent.get("speed_score")),
    )


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _agent_rows(config: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for agent in config.agents.values():
        normalized = normalize_provider(agent.provider)
        free = is_free_agent(agent)
        allowed = agent.enabled and agent_allowed_by_cost_policy(config, agent)
        status = _agent_status(agent, free=free, allowed=allowed, normalized=normalized)
        rows.append(
            {
                "name": agent.name,
                "provider": agent.provider,
                "provider_type": agent.provider_type,
                "model": agent.model,
                "enabled": agent.enabled,
                "free": free,
                "allowed": allowed,
                "tokens": agent.context_window or "?",
                "status": status,
                "base_url": agent.base_url,
                "api_key_env": agent.api_key_env,
                "priority": agent.priority,
                "coding_score": agent.coding_score,
                "reasoning_score": agent.reasoning_score,
                "speed_score": agent.speed_score,
            }
        )
    return rows


def _agent_status(agent: Any, *, free: bool, allowed: bool, normalized: str) -> str:
    if not agent.enabled:
        return "disabled"
    if not allowed:
        return "skipped by free_only"
    if agent.api_key_env and not agent.resolved_api_key and normalized in {"openai", "anthropic", "gemini", "openai-compatible"}:
        return f"missing {agent.api_key_env or 'api key'}"
    if normalized == "openai-compatible":
        if not agent.base_url:
            return "missing base_url"
        return "configured"
    return "ready"


def _health_rows(provider_health: Any) -> list[dict[str, Any]]:
    if not isinstance(provider_health, dict):
        return []
    rows: list[dict[str, Any]] = []
    for name, health in provider_health.items():
        if not isinstance(health, dict):
            continue
        status = "ready"
        if health.get("cooldown_until", 0) and float(health.get("cooldown_until") or 0) > time.time():
            status = "cooldown"
        elif health.get("requests_remaining") == 0:
            status = "quota"
        elif health.get("quota_remaining") == 0:
            status = "quota"
        elif health.get("degraded"):
            status = "degraded"
        rows.append(
            {
                "name": name,
                "available": health.get("available"),
                "degraded": health.get("degraded"),
                "reliability": health.get("reliability_score"),
                "avg_ms": health.get("average_latency_ms"),
                "cooldown": _future_seconds(health.get("cooldown_until")),
                "quota": _unknown_if_none(health.get("quota_remaining")),
                "requests": _unknown_if_none(health.get("requests_remaining")),
                "status": status,
            }
        )
    return rows


def _metrics_rows(provider_health: Any) -> list[dict[str, Any]]:
    if not isinstance(provider_health, dict):
        return []
    rows: list[dict[str, Any]] = []
    for name, health in provider_health.items():
        if not isinstance(health, dict):
            continue
        rows.append(
            {
                "name": name,
                "success": health.get("success_count", 0),
                "failure": health.get("failure_count", 0),
                "timeouts": health.get("timeout_count", 0),
                "tool_ok": health.get("tool_call_success_count", 0),
                "tool_fail": health.get("tool_call_failure_count", 0),
                "avg_ms": health.get("average_latency_ms", 0),
                "stream_tps": health.get("streaming_tokens_per_second", 0),
                "tokens": f"{health.get('tokens_in', 0)}/{health.get('tokens_out', 0)}",
            }
        )
    return rows


def _recent_failover_events(provider_health: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for health in provider_health.values():
        if not isinstance(health, dict):
            continue
        for event in health.get("failover_events", []):
            if isinstance(event, dict):
                events.append(
                    {
                        "time": event.get("time", 0),
                        "age": _age_seconds(event.get("time")),
                        "agent": event.get("agent", ""),
                        "error_type": event.get("error_type", ""),
                        "status_code": event.get("status_code", ""),
                        "reason": str(event.get("reason", ""))[:100],
                    }
                )
    return sorted(events, key=lambda item: float(item.get("time") or 0), reverse=True)


def _future_seconds(timestamp: Any) -> str:
    try:
        value = float(timestamp or 0)
    except (TypeError, ValueError):
        return ""
    remaining = int(value - time.time())
    return f"{remaining}s" if remaining > 0 else ""


def _age_seconds(timestamp: Any) -> str:
    try:
        value = float(timestamp or 0)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    return f"{max(0, int(time.time() - value))}s"


def _unknown_if_none(value: Any) -> Any:
    return "?" if value is None else value


def _health_report(config: Any, *, route: str, include_history: bool) -> dict[str, Any]:
    router = AgentRouter(config)
    request = request_from_payload(
        {
            "session_id": f"health-{uuid.uuid4().hex}",
            "route": route,
            "task": "Choose the best available model for an agent workflow.",
            "use_session_history": False,
            "record_session": False,
        }
    )
    recommendations = router.recommend(
        request,
        limit=8,
        needs_tools=True,
        include_unavailable=True,
    )
    health = router.health_snapshot(include_history=include_history)
    readiness = DiagnosticsApplicationService(config).readiness_body(
        router,
        provider_health=health,
    )
    return {
        "status": "ok",
        "route": route,
        "provider_health": health,
        "readiness": readiness,
        "recommendations": recommendations,
        "routing_decisions": [
            {
                "rank": row["rank"],
                "agent": row["agent"],
                "available": row["available"],
                "degraded": row["degraded"],
                "score": row["score"],
                "reason": row.get("unavailable_reason") or row.get("why"),
            }
            for row in recommendations
        ],
        "failover_history": _recent_failover_events(health),
    }


def _production_check_report(config: Any) -> dict[str, Any]:
    router = AgentRouter(config)
    return DiagnosticsApplicationService(config).production_check_body(router)


def _feature_scorecard_report(config: Any) -> dict[str, Any]:
    router = AgentRouter(config)
    return DiagnosticsApplicationService(config).feature_scorecard_body(router)


def _print_health(report: dict[str, Any]) -> None:
    print("Agent-Hub health")
    print(f"Route: {report['route']}")
    readiness = report.get("readiness") if isinstance(report.get("readiness"), dict) else {}
    if readiness:
        state = str(readiness.get("state") or "unknown").replace("_", " ")
        print(f"Readiness: {readiness.get('score', '?')}/100 ({state})")
        next_step = readiness.get("next_step") if isinstance(readiness.get("next_step"), dict) else {}
        if next_step:
            print(f"Next step: {next_step.get('label')} - {next_step.get('detail')}")
    print()
    _print_table(
        _health_rows(report.get("provider_health", {})),
        ["name", "available", "degraded", "reliability", "avg_ms", "cooldown", "quota", "requests", "status"],
    )
    recommendations = report.get("recommendations")
    if isinstance(recommendations, list) and recommendations:
        print()
        print("Best candidates:")
        _print_table(
            recommendations[:5],
            ["rank", "agent", "provider", "model", "score", "available", "why"],
        )


def _print_production_check(report: dict[str, Any]) -> None:
    print("Agent-Hub production check")
    print(f"Score: {report.get('score', '?')}/100 ({report.get('state', 'unknown')})")
    print(f"Rating: {report.get('rating', '?')}/10")
    failed = report.get("failed") if isinstance(report.get("failed"), list) else []
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    if failed:
        print()
        print("Failed checks:")
        _print_table(
            failed,
            ["id", "severity", "detail", "command"],
        )
    if warnings:
        print()
        print("Warnings:")
        _print_table(
            warnings,
            ["id", "severity", "detail", "command"],
        )
    if not failed and not warnings:
        print("All production checks passed.")


def _print_feature_scorecard(report: dict[str, Any]) -> None:
    print("Agent-Hub feature scorecard")
    print(f"Rating: {report.get('rating', '?')}/10 ({report.get('state', 'unknown')})")
    print(f"All local areas 10/10: {str(bool(report.get('all_local_areas_10'))).lower()}")
    print()
    areas = report.get("areas") if isinstance(report.get("areas"), list) else []
    rows = [
        {
            "area": area.get("area"),
            "rating": area.get("rating"),
            "state": area.get("state"),
            "checks": f"{area.get('passed_required', 0)}/{area.get('required_count', 0)}",
            "honest_take": area.get("honest_take"),
        }
        for area in areas
        if isinstance(area, dict)
    ]
    _print_table(rows, ["area", "rating", "state", "checks", "honest_take"])
    blockers = report.get("blockers") if isinstance(report.get("blockers"), list) else []
    if blockers:
        print()
        print("Blockers:")
        blocker_rows = []
        for blocker in blockers:
            if not isinstance(blocker, dict):
                continue
            missing = blocker.get("missing") if isinstance(blocker.get("missing"), list) else []
            blocker_rows.append(
                {
                    "area": blocker.get("area"),
                    "missing": ", ".join(str(row.get("id")) for row in missing if isinstance(row, dict)),
                }
            )
        _print_table(blocker_rows, ["area", "missing"])


def _print_metrics(report: dict[str, Any]) -> None:
    print("Agent-Hub metrics")
    print(f"Route: {report['route']}")
    print()
    _print_table(
        _metrics_rows(report.get("provider_health", {})),
        [
            "name",
            "success",
            "failure",
            "timeouts",
            "tool_ok",
            "tool_fail",
            "avg_ms",
            "stream_tps",
            "tokens",
        ],
    )
    history = report.get("failover_history")
    if isinstance(history, list) and history:
        print()
        print("Recent failover:")
        _print_table(history[:10], ["age", "agent", "error_type", "status_code", "reason"])


def _local_models_report(config: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for agent in config.agents.values():
        if (
            normalize_provider(agent.provider) != "openai-compatible"
            or not is_free_agent(agent)
            or (agent.provider_type or "").lower() == "ollama-cloud"
            or not _is_local_or_private_url(agent.base_url)
        ):
            continue
        row = {
            "name": agent.name,
            "base_url": agent.base_url,
            "configured_model": agent.model,
            "online": False,
            "models": [],
            "error": "",
        }
        if not agent.base_url:
            row["error"] = "missing base_url"
            rows.append(row)
            continue
        try:
            timeout = max(0.05, float(getattr(config, "local_model_probe_timeout_seconds", 3.0) or 3.0))
            models = fetch_openai_models(
                agent.base_url,
                timeout=timeout,
                api_key=agent.resolved_api_key,
                headers=agent.headers,
            )
            row["online"] = True
            row["models"] = models
            row["configured_model_available"] = agent.model in models
        except Exception as exc:
            row["error"] = str(exc)
            row["configured_model_available"] = False
        rows.append(row)
    return rows


def _recommend(
    config: Any,
    *,
    route: str,
    prompt: str,
    limit: int,
    prefer: str,
    needs_tools: bool,
    include_unavailable: bool,
    as_json: bool,
) -> int:
    router = AgentRouter(config)
    request = request_from_payload(
        {
            "session_id": f"recommend-{uuid.uuid4().hex}",
            "route": route,
            "task": prompt or "Recommend a model.",
            "use_session_history": False,
            "record_session": False,
        }
    )
    rows = router.recommend(
        request,
        limit=max(1, limit),
        needs_tools=needs_tools or None,
        prefer=None if prefer == "balanced" else prefer,
        include_unavailable=include_unavailable,
    )
    if as_json:
        print(json.dumps({"route": route, "recommendations": rows}, indent=2, ensure_ascii=False))
    else:
        if not rows:
            print("No configured agents are available for that route.")
            return 1
        _print_table(rows, ["rank", "agent", "provider", "model", "score", "free", "available", "why"])
        unavailable = [row for row in rows if not row.get("available")]
        if unavailable:
            print()
            print("Unavailable:")
            for row in unavailable:
                print(f"- {row['agent']}: {row['unavailable_reason']}")
    return 0


def _estimate(
    config: Any,
    *,
    route: str,
    prompt: str,
    limit: int,
    prefer: str,
    needs_tools: bool,
    output_tokens: int,
    as_json: bool,
) -> int:
    router = AgentRouter(config)
    request = request_from_payload(
        {
            "session_id": f"estimate-{uuid.uuid4().hex}",
            "route": route,
            "task": prompt or "Estimate routing.",
            "max_tokens": max(1, int(output_tokens)),
            "use_session_history": False,
            "record_session": False,
        }
    )
    rows = router.recommend(
        request,
        limit=max(1, limit),
        needs_tools=needs_tools or None,
        prefer=None if prefer == "balanced" else prefer,
        include_unavailable=True,
    )
    input_tokens = _estimate_request_tokens(request)
    output_estimate = max(1, int(output_tokens))
    enriched: list[dict[str, Any]] = []
    for row in rows:
        agent = config.agents.get(row.get("agent"))
        cost = (
            estimate_known_cost_usd(agent, input_tokens=input_tokens, output_tokens=output_estimate)
            if agent is not None
            else None
        )
        enriched.append(
            {
                **row,
                "estimated_input_tokens": input_tokens,
                "estimated_output_tokens": output_estimate,
                "estimated_cost_usd": cost,
                "estimated_latency_ms": row.get("average_latency_ms") or None,
                "routing_explanation": row.get("unavailable_reason") or row.get("why") or "",
            }
        )
    report = {
        "object": "agent_hub.routing_estimate",
        "route": route,
        "input_tokens": input_tokens,
        "output_tokens": output_estimate,
        "recommendations": enriched,
        "baseline_comparisons": _baseline_estimate(
            config,
            selected=next((row for row in enriched if row.get("available")), enriched[0] if enriched else None),
            candidates=enriched,
            input_tokens=input_tokens,
            output_tokens=output_estimate,
        ),
    }
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Route estimate: {route}")
        print(f"Estimated tokens: input={input_tokens} output={output_estimate}")
        _print_table(
            enriched,
            [
                "rank",
                "agent",
                "provider",
                "model",
                "score",
                "available",
                "estimated_cost_usd",
                "estimated_latency_ms",
                "routing_explanation",
            ],
        )
        _print_baseline_estimate(report.get("baseline_comparisons"))
    return 0


def _route_diagnose(
    config: Any,
    *,
    route: str,
    prompt: str,
    output_tokens: int,
    prefer: str,
    needs_tools: bool,
    as_json: bool,
) -> int:
    router = AgentRouter(config)
    output_estimate = max(1, int(output_tokens))
    request = request_from_payload(
        {
            "session_id": f"route-diagnose-{uuid.uuid4().hex}",
            "route": route,
            "task": prompt or "Diagnose routing.",
            "max_tokens": output_estimate,
            "use_session_history": False,
            "record_session": False,
        }
    )
    decision = router.decide(request)
    rows = router.recommend(
        request,
        limit=max(1, len(config.agents)),
        needs_tools=needs_tools or None,
        prefer=None if prefer == "balanced" else prefer,
        include_unavailable=True,
    )
    input_tokens = _estimate_request_tokens(request)
    candidates = [
        _diagnostic_candidate(
            config,
            row,
            input_tokens=input_tokens,
            output_tokens=output_estimate,
        )
        for row in rows
    ]
    selected = next((row for row in candidates if row.get("available")), None)
    skipped = [row for row in candidates if not row.get("available")]
    fallback_reason = _diagnostic_fallback_reason(skipped)
    decision_scorecards = {
        row.get("agent"): row
        for row in decision.candidate_scores
        if isinstance(row, dict) and row.get("agent")
    }
    for row in candidates:
        scorecard = decision_scorecards.get(row.get("agent"))
        if isinstance(scorecard, dict):
            row["token_saver"] = scorecard.get("token_saver")
            row["routing_score"] = scorecard.get("final_routing_score", scorecard.get("routing_score"))
    selection_warnings = _selected_diagnostic_warnings(selected)
    report = {
        "object": "agent_hub.route_diagnosis",
        "route": route,
        "routing_mode": decision.routing_mode,
        "task_type": decision.task_type,
        "selected_agent": selected.get("agent") if selected else None,
        "selected_provider": selected.get("provider") if selected else None,
        "selected_model": selected.get("model") if selected else None,
        "skipped_providers": skipped,
        "fallback_reason": fallback_reason,
        "latency_ms": selected.get("latency_ms") if selected else None,
        "estimated_cost_usd": selected.get("estimated_cost_usd") if selected else None,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_estimate,
        "why_provider_chosen": selected.get("why") if selected else decision.reason,
        "selection_warnings": selection_warnings,
        "selection_honesty": _selection_honesty_summary(selected, selection_warnings),
        "token_saver": (decision_scorecards.get(selected.get("agent")) or {}).get("token_saver") if selected else None,
        "fallback_chain": list(decision.fallback_chain),
        "candidates": candidates,
        "baseline_comparisons": _baseline_estimate(
            config,
            selected=selected,
            candidates=candidates,
            input_tokens=input_tokens,
            output_tokens=output_estimate,
        ),
    }
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_route_diagnosis(report)
    return 0


def _diagnostic_candidate(
    config: Any,
    row: dict[str, Any],
    *,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, Any]:
    agent = config.agents.get(row.get("agent"))
    cost = (
        estimate_known_cost_usd(agent, input_tokens=input_tokens, output_tokens=output_tokens)
        if agent is not None
        else None
    )
    latency_ms = row.get("average_latency_ms") or None
    return {
        "rank": row.get("rank"),
        "agent": row.get("agent"),
        "provider": row.get("provider"),
        "provider_type": row.get("provider_type"),
        "model": row.get("model"),
        "available": bool(row.get("available")),
        "reason": row.get("unavailable_reason") or row.get("why") or "",
        "fallback_reason": row.get("unavailable_reason") or "",
        "latency_ms": latency_ms,
        "estimated_cost_usd": cost,
        "score": row.get("score"),
        "free": row.get("free"),
        "why": row.get("why") or "",
        "quota_state": row.get("quota_state"),
        "remaining": row.get("remaining"),
        "reliability_score": row.get("reliability_score"),
        "degraded": bool(row.get("degraded")),
        "cooldown_until": row.get("cooldown_until"),
        "token_saver": row.get("token_saver"),
    }


def _diagnostic_fallback_reason(skipped: list[dict[str, Any]]) -> str:
    for row in skipped:
        reason = str(row.get("fallback_reason") or row.get("reason") or "").strip()
        if reason:
            return reason
    return ""


def _selected_diagnostic_warnings(selected: dict[str, Any] | None) -> list[str]:
    if not selected:
        return []
    warnings: list[str] = []
    if selected.get("degraded"):
        warnings.append("Selected provider is currently marked degraded by health history.")
    reliability = _safe_float(selected.get("reliability_score"))
    if reliability and reliability < 0.5:
        warnings.append(f"Selected provider reliability is low ({reliability:.2f}).")
    latency = _safe_float(selected.get("latency_ms"))
    if latency and latency >= 15_000:
        warnings.append(f"Selected provider average latency is high ({latency:.0f} ms).")
    cooldown = _safe_float(selected.get("cooldown_until"))
    if cooldown and cooldown > time.time():
        warnings.append("Selected provider has a recent cooldown marker; fallback may occur at execution time.")
    return warnings


def _selection_honesty_summary(selected: dict[str, Any] | None, warnings: list[str]) -> str:
    if not selected:
        return "No available provider was selected."
    if not warnings:
        return "Selected provider has no active health warnings in the diagnostic snapshot."
    return "Selected despite warnings because its route priority, capability, context window, or fallback role still ranked highest."


def _print_route_diagnosis(report: dict[str, Any]) -> None:
    print(f"Route diagnosis: {report['route']}")
    print(f"Selected provider: {report.get('selected_provider') or 'none'}")
    print(f"Selected model: {report.get('selected_model') or 'none'}")
    print(f"Selected agent: {report.get('selected_agent') or 'none'}")
    print(f"Fallback reason: {report.get('fallback_reason') or 'none'}")
    print(f"Latency: {_display_latency(report.get('latency_ms'))}")
    print(f"Estimated cost: {_display_cost(report.get('estimated_cost_usd'))}")
    if report.get("why_provider_chosen"):
        print(f"Why: {report['why_provider_chosen']}")
    if report.get("selection_honesty"):
        print(f"Selection honesty: {report['selection_honesty']}")
    warnings = report.get("selection_warnings")
    if isinstance(warnings, list) and warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    token_saver = report.get("token_saver")
    if isinstance(token_saver, dict):
        state = "active" if token_saver.get("active") else "inactive"
        confidence = token_saver.get("confidence")
        summary = token_saver.get("summary") or ""
        print(f"Token saver: {state} (confidence {confidence}) {summary}")
    skipped = report.get("skipped_providers")
    if isinstance(skipped, list) and skipped:
        print()
        print("Skipped providers:")
        _print_table(skipped, ["agent", "provider", "model", "reason", "latency_ms", "estimated_cost_usd"])
    candidates = report.get("candidates")
    if isinstance(candidates, list) and candidates:
        print()
        print("Candidates:")
        _print_table(candidates, ["rank", "agent", "provider", "model", "available", "score", "latency_ms"])
    _print_baseline_estimate(report.get("baseline_comparisons"))


def _baseline_estimate(
    config: Any,
    *,
    selected: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    input_tokens: int,
    output_tokens: int,
) -> dict[str, Any]:
    selected_agent = str((selected or {}).get("agent") or "")
    if not selected_agent:
        return {
            "selected_agent": "",
            "selected_cost_usd": None,
            "measurement_source": "estimated",
            "named_baselines": [],
        }
    return estimate_named_baselines(
        config,
        selected_agent=selected_agent,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        candidate_agents=[
            str(row.get("agent") or "")
            for row in candidates
            if isinstance(row, dict) and row.get("agent")
        ],
    )


def _print_baseline_estimate(value: Any) -> None:
    report = value if isinstance(value, dict) else {}
    rows = report.get("named_baselines") if isinstance(report.get("named_baselines"), list) else []
    if not rows:
        return
    print()
    print("Named baselines:")
    _print_table(
        rows,
        [
            "baseline_name",
            "baseline_agent",
            "baseline_provider",
            "baseline_model",
            "cost_usd",
            "savings_usd",
            "savings_pct",
        ],
    )


def _display_latency(value: Any) -> str:
    if value is None or value == "" or value == 0 or value == 0.0:
        return "unavailable"
    return f"{value} ms"


def _display_cost(value: Any) -> str:
    if value is None:
        return "unavailable"
    return f"${float(value):.6f}"


def _estimate_request_tokens(request: Any) -> int:
    try:
        from .token_budget import estimate_messages_tokens
    except Exception:
        return 0
    return estimate_messages_tokens(request.messages)


def _benchmark(config: HubConfig, *, route: str, prompt: str, as_json: bool) -> int:
    router = AgentRouter(config)
    request = request_from_payload(
        {
            "session_id": f"benchmark-{uuid.uuid4().hex}",
            "route": route,
            "task": prompt,
            "max_tokens": 128,
            "use_session_history": False,
            "record_session": False,
        }
    )
    try:
        response = router.route(request)
    except RouterError as exc:
        _print_route_error(exc)
        return 1
    data = {
        "route": route,
        "agent": response.agent,
        "provider": response.provider,
        "model": response.model,
        "usage": response.usage,
        "health": router.health_snapshot(),
        "failover": [event.to_dict() for event in response.failover],
    }
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"Route: {route}")
        print(f"Selected: {response.agent} ({response.provider}) model={response.model}")
        if response.failover:
            print("Failover:")
            for event in response.failover:
                print(f"- {event.agent}: {event.reason}")
        print("Health:")
        for name, health in data["health"].items():
            print(
                f"- {name}: success={health['success_count']} failure={health['failure_count']} "
                f"avg_latency={health['average_latency_seconds']}s"
            )
    return 0


def _benchmark_suite(
    config: HubConfig,
    *,
    route: str,
    limit: int,
    as_json: bool,
    output: str | None = None,
) -> int:
    report = BenchmarkSuiteRunner(config).run(route=route, limit=limit)
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        report["report_path"] = str(target)
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Benchmark suite for route {route}")
        print(f"Report: {report.get('report_path')}")
        print("Static routing:")
        _print_table([report["static_routing"]], ["task_count", "success_rate", "average_score", "average_latency_ms", "failover_frequency", "average_cost_usd"])
        print("Adaptive routing:")
        _print_table([report["adaptive_routing"]], ["task_count", "success_rate", "average_score", "average_latency_ms", "failover_frequency", "average_cost_usd"])
        print("Comparison:")
        _print_table([report["comparison"]], ["winner", "success_rate_delta", "average_score_delta", "latency_delta_ms", "failover_frequency_delta", "cost_savings_usd"])
    return 0 if report.get("comparison", {}).get("winner") else 1


def _benchmark_run(
    config: HubConfig,
    *,
    route: str,
    baseline: str,
    limit: int,
    corpus: str,
    output_dir: str,
    as_json: bool,
) -> int:
    try:
        report = BenchmarkProofRunner(config).run(
            route=route,
            baseline=baseline,
            limit=limit,
            corpus_dir=corpus or None,
            output_dir=output_dir or None,
        )
    except (RouterError, ValueError) as exc:
        if isinstance(exc, RouterError):
            _print_route_error(exc)
        else:
            print(f"Benchmark failed: {exc}")
        return 1
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        comparison = report.get("comparison", {}) if isinstance(report.get("comparison"), dict) else {}
        baseline_info = report.get("baseline", {}) if isinstance(report.get("baseline"), dict) else {}
        print(f"Benchmark proof for route {route}")
        print(
            "Baseline: "
            f"{baseline_info.get('agent')} ({baseline_info.get('provider')}) model={baseline_info.get('model')}"
        )
        print(f"Tasks: {report.get('task_count')}")
        print(f"JSON report: {report.get('report_paths', {}).get('json')}")
        print(f"Markdown report: {report.get('report_paths', {}).get('markdown')}")
        print()
        _print_table(
            [
                {
                    "cost_reduction": comparison.get("cost_reduction"),
                    "latency_reduction": comparison.get("latency_reduction"),
                    "success_delta": comparison.get("success_delta"),
                    "average_score_delta": comparison.get("average_score_delta"),
                }
            ],
            ["cost_reduction", "latency_reduction", "success_delta", "average_score_delta"],
        )
    return 0


def _explain_route(
    config: HubConfig,
    *,
    route: str,
    prompt: str,
    output_tokens: int,
    prefer: str,
    needs_tools: bool,
    as_json: bool,
) -> int:
    report = explain_route_body(
        config,
        route=route,
        prompt=prompt,
        output_tokens=output_tokens,
        prefer=prefer,
        needs_tools=needs_tools,
    )
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_route_explanation(report), end="")
    return 0


def _route_history(config: HubConfig, *, weeks: int, as_json: bool) -> int:
    report = route_history_body(config, weeks=weeks)
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_route_history(report), end="")
    return 0


def _replay_route(config: HubConfig, *, request_id: str, as_json: bool) -> int:
    report = replay_route_body(config, request_id)
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_route_replay(report), end="")
    return 0 if report.get("found") else 1


def _benchmark_card(
    config: HubConfig,
    *,
    report_path: str,
    variant: str,
    as_json: bool,
) -> int:
    report = benchmark_share_card_body(config, report_path or None)
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_benchmark_card(report, variant=variant), end="")
    return 0 if report.get("report_path") else 1


def _generate_case_study(
    config: HubConfig,
    *,
    output: str,
    as_json: bool,
) -> int:
    report = case_study_body(config)
    if as_json:
        text = json.dumps(report, indent=2, ensure_ascii=False)
    else:
        text = format_case_study_markdown(report)
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def _benchmark_evolution(config: HubConfig, *, months: int, as_json: bool) -> int:
    report = benchmark_evolution_body(config, months=months)
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_benchmark_evolution(report), end="")
    return 0


def _eval_providers(config: HubConfig, *, route: str, limit: int, as_json: bool) -> int:
    router = AgentRouter(config)
    tasks = default_benchmark_tasks(route=route)[: max(1, min(limit, 20))]
    runner = BenchmarkRunner(router, store=ProviderScoreStore(config.state_dir))
    results = runner.run(tasks)
    scores = ProviderScoreStore(config.state_dir).load()
    data = {
        "object": "agent_hub.provider_evaluation",
        "route": route,
        "results": [result.to_dict() for result in results],
        "provider_scores": scores,
    }
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"Provider evaluation for route {route}")
        _print_table(
            data["results"],
            ["agent", "provider", "model", "task_type", "score", "latency_ms", "ok", "error"],
        )
        print(f"Stored scores: {config.state_dir / 'provider_scores.json'}")
    return 0 if any(result.ok for result in results) else 1


def _calibrate_models(
    config: HubConfig,
    *,
    route: str,
    limit: int,
    max_agents: int,
    agents: str,
    as_json: bool,
) -> int:
    router = AgentRouter(config)
    route_names = _route_agent_names(config, route)
    requested = [name.strip() for name in agents.split(",") if name.strip()]
    names = requested or route_names
    selected_agents = [
        config.agents[name]
        for name in names
        if name in config.agents
        and config.agents[name].enabled
        and agent_allowed_by_cost_policy(config, config.agents[name])
    ][: max(1, int(max_agents or 1))]
    tasks = default_benchmark_tasks(route=route)[: max(1, min(int(limit or 1), 20))]
    results: list[BenchmarkResult] = []
    errors: list[dict[str, Any]] = []
    for agent in selected_agents:
        for task in tasks:
            request = request_from_payload(
                {
                    "session_id": f"calibrate-{uuid.uuid4().hex}",
                    "route": route,
                    "agent": agent.name,
                    "task": task.prompt,
                    "max_tokens": 192,
                    "use_session_history": False,
                    "record_session": False,
                    "agent_hub": {
                        "benchmark_task_type": task.type,
                        "model_calibration": True,
                        "provider_approval_granted": True,
                    },
                }
            )
            request = mark_trusted_approval(request, source="cli-calibrate-models")
            started = time.perf_counter()
            try:
                response = router.route(request)
                latency_ms = (time.perf_counter() - started) * 1000
                results.append(
                    BenchmarkResult(
                        agent=response.agent,
                        provider=response.provider,
                        model=response.model,
                        task_type=task.type,
                        score=_score_text(response.text, task),
                        latency_ms=round(latency_ms, 2),
                        ok=bool(response.text.strip()),
                    )
                )
            except Exception as exc:
                errors.append(
                    {
                        "agent": agent.name,
                        "provider": agent.provider,
                        "model": agent.model,
                        "task_type": task.type,
                        "error": str(exc),
                    }
                )
    scores = ProviderScoreStore(config.state_dir).save_results(results) if results else ProviderScoreStore(config.state_dir).load()
    report = {
        "object": "agent_hub.model_calibration",
        "route": route,
        "agent_count": len(selected_agents),
        "task_count": len(tasks),
        "result_count": len(results),
        "error_count": len(errors),
        "results": [result.to_dict() for result in results],
        "errors": errors,
        "provider_scores_path": str(config.state_dir / "provider_scores.json"),
        "provider_scores": scores,
    }
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Model calibration for route {route}")
        print(f"Agents: {len(selected_agents)}; tasks per agent: {len(tasks)}; results: {len(results)}")
        _print_table(report["results"], ["agent", "provider", "model", "task_type", "score", "latency_ms", "ok"])
        if errors:
            print()
            print("Calibration errors:")
            _print_table(errors, ["agent", "provider", "model", "task_type", "error"])
        print(f"Stored scores: {report['provider_scores_path']}")
    return 0 if results else 1


def _route_agent_names(config: HubConfig, route_name: str) -> list[str]:
    for route in config.routes:
        if route.name == route_name:
            return list(route.agents)
    return list(config.default_route)


def _route_test(config: HubConfig, *, route: str, prompt: str, as_json: bool) -> int:
    router = AgentRouter(config)
    request = request_from_payload(
        {
            "session_id": f"route-test-{uuid.uuid4().hex}",
            "route": route,
            "task": prompt,
            "max_tokens": 256,
            "use_session_history": False,
            "record_session": False,
        }
    )
    try:
        response = router.route(request)
    except RouterError as exc:
        _print_route_error(exc)
        return 1
    data = response.to_native_dict(include_routing_details=True)
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"Selected {response.agent} ({response.provider}) model={response.model}")
        print(response.text)
        if response.failover:
            print("Failover:")
            for event in response.failover:
                print(f"- {event.agent}: {event.reason}")
    return 0


def _print_local_models(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No free local OpenAI-compatible agents are configured.")
        return
    print("Free local model endpoints:")
    for row in rows:
        status = "online" if row["online"] else "offline"
        print(f"- {row['name']} ({status}) {row['base_url']} model={row['configured_model']}")
        if row["online"]:
            models = row.get("models", [])
            if models:
                print(f"  available: {', '.join(models[:10])}")
                if len(models) > 10:
                    print(f"  ...and {len(models) - 10} more")
            else:
                print("  available: endpoint returned no model IDs")
        elif row.get("error"):
            print(f"  error: {row['error']}")
