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
    is_free_agent,
    load_config,
    normalize_provider,
)
from .core.router import AgentRouter, RouterError
from .discovery import fetch_openai_models
from .evaluation import BenchmarkRunner, ProviderScoreStore, default_benchmark_tasks
from .evaluation.benchmark_suite import BenchmarkSuiteRunner
from .payloads import request_from_payload
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
        if preset["name"] == "fallback-safe":
            routing["max_provider_attempts"] = max(3, int(routing.get("max_provider_attempts") or 3))
    if preset["name"] in {"private", "local-only"}:
        data["auto_enable_available_providers"] = False

    for route_name in ("cloud-agent", "coding", "hybrid-agent"):
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
    candidates = enabled or agents
    selector = str(preset["selector"])

    if selector == "private":
        selected = [agent for agent in candidates if _agent_is_private(agent)]
    elif selector == "cheap-local":
        selected = [agent for agent in candidates if _agent_is_free(agent) and _agent_is_private(agent)]
    elif selector == "best-coding":
        selected = sorted(candidates, key=_coding_agent_rank, reverse=True)
    elif selector == "fastest":
        selected = sorted(candidates, key=_speed_agent_rank, reverse=True)
    elif selector == "fallback-safe":
        selected = sorted(candidates, key=_fallback_safe_agent_rank, reverse=True)
    else:
        selected = candidates

    if not selected:
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
        allowed = agent.enabled and (free or not config.free_only)
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
        "fallback_chain": list(decision.fallback_chain),
        "candidates": candidates,
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
    }


def _diagnostic_fallback_reason(skipped: list[dict[str, Any]]) -> str:
    for row in skipped:
        reason = str(row.get("fallback_reason") or row.get("reason") or "").strip()
        if reason:
            return reason
    return ""


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
