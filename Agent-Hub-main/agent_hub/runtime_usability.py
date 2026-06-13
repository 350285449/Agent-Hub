from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import HubConfig, is_free_agent, normalize_provider
from .permissions import TRUSTED_CLOUD, UNTRUSTED_EXTERNAL, provider_trust_level


RUNTIME_USABILITY_STATE_FILE = "runtime_usability.json"


def runtime_usability_body(
    config: HubConfig,
    provider_health: dict[str, dict[str, Any]],
    *,
    backend_reachable: dict[str, Any] | None = None,
    local_servers: list[dict[str, Any]] | None = None,
    local_model_rows: list[dict[str, Any]] | None = None,
    route_smoke: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the honest live-usability state for this installation."""

    persisted = load_runtime_usability_record(config)
    smoke = route_smoke if isinstance(route_smoke, dict) else _dict(persisted.get("route_smoke"))
    backend_ok = True if backend_reachable is None else bool(backend_reachable.get("ok"))
    coding_candidates = _coding_candidate_agents(config)
    verified_coding = [
        _verified_provider_row(agent.name, agent, provider_health.get(agent.name, {}))
        for agent in coding_candidates
        if _verified_coding_provider(
            config,
            agent,
            provider_health.get(agent.name, {}),
            local_servers=local_servers or [],
            local_model_rows=local_model_rows or [],
        )
    ]
    degraded_verified = [
        row for row in verified_coding if row.get("degraded") or float(row.get("reliability_score") or 1.0) < 0.5
    ]
    research_ok = _research_route_available(config)
    coding_smoke = _dict(smoke.get("coding"))
    research_smoke = _dict(smoke.get("research"))
    coding_smoke_ok = bool(coding_smoke.get("ok"))
    research_smoke_ok = bool(research_smoke.get("ok"))
    route_smoke_ok = coding_smoke_ok and research_smoke_ok
    provider_approval_needed = _provider_approval_needed(config, coding_candidates, provider_health, verified_coding)

    checks = [
        _check(
            "backend_running",
            backend_ok,
            "Backend is reachable",
            _backend_detail(backend_reachable) if backend_reachable is not None else "In-process backend is running.",
            "agent-hub serve",
            weight=20,
        ),
        _check(
            "verified_coding_provider",
            bool(verified_coding),
            "Coding route has a verified provider",
            (
                "Verified coding provider(s): " + ", ".join(row["agent"] for row in verified_coding[:5])
                if verified_coding
                else "No coding-capable provider has proven it can answer from this runtime."
            ),
            "agent-hub checkup --fix-safe --verify",
            weight=30,
        ),
        _check(
            "research_route_available",
            research_ok,
            "Research route has a no-key local provider",
            "local-research is enabled." if research_ok else "Enable local-research on the research route.",
            "agent-hub doctor --fix-safe",
            weight=10,
        ),
        _check(
            "safe_mode_understood",
            config.approval_mode in {"safe", "ask", "readonly", "deny", "auto"},
            "Permission mode is explicit",
            f"approval_mode={config.approval_mode}.",
            None,
            weight=10,
        ),
        _check(
            "route_smoke_recorded",
            route_smoke_ok,
            "Route smoke result is recorded",
            _smoke_detail(smoke, coding_smoke_ok, research_smoke_ok),
            "agent-hub checkup --fix-safe --verify",
            weight=30,
        ),
    ]
    if not backend_ok:
        state = "needs_server"
    elif not verified_coding:
        state = "needs_provider_approval" if provider_approval_needed else "needs_local_model"
    elif not route_smoke_ok or degraded_verified:
        state = "degraded"
    else:
        state = "ready"
    if state == "ready":
        title = "Ready for real coding tasks"
    elif state == "needs_server":
        title = "Start Agent Hub"
    elif state == "needs_provider_approval":
        title = "Approve or choose a provider"
    elif state == "needs_local_model":
        title = "Connect a local coding model"
    else:
        title = "Runtime ready with warnings"
    score = _score(checks)
    if state == "degraded":
        score = min(score, 85)
    next_step = next((item for item in checks if item["status"] == "action"), None)
    if next_step is None:
        next_step = next((item for item in checks if item["status"] == "warn"), None)
    return {
        "object": "agent_hub.runtime_usability",
        "score": score,
        "rating": round(score / 10, 1),
        "state": state,
        "title": title,
        "ready": state == "ready",
        "backend_reachable": backend_reachable if isinstance(backend_reachable, dict) else {"ok": backend_ok},
        "verified_coding_providers": verified_coding,
        "degraded_verified_providers": degraded_verified,
        "research_route_available": research_ok,
        "provider_approval_needed": provider_approval_needed,
        "route_smoke": smoke,
        "next_step": next_step,
        "checks": checks,
        "honesty": (
            "Runtime usability requires a reachable backend, a verified coding-capable provider, "
            "a local research path, guarded permissions, and a recorded route smoke result."
        ),
    }


def load_runtime_usability_record(config: HubConfig) -> dict[str, Any]:
    path = _state_path(config)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_runtime_usability_record(config: HubConfig, body: dict[str, Any]) -> Path:
    path = _state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def runtime_route_smoke(
    *,
    research_ok: bool,
    coding_ok: bool,
    research_agent: str = "local-research",
    coding_agent: str = "",
    coding_error: str = "",
) -> dict[str, Any]:
    now = time.time()
    return {
        "recorded_at": now,
        "research": {
            "ok": bool(research_ok),
            "agent": research_agent,
        },
        "coding": {
            "ok": bool(coding_ok),
            "agent": coding_agent,
            "error": coding_error[:500],
        },
    }


def _coding_candidate_agents(config: HubConfig) -> list[Any]:
    names: list[str] = []
    for route in config.routes:
        if route.name in {"coding", "cloud-agent", "hybrid-agent", "local-agent"}:
            names.extend(route.agents)
    names.extend(config.default_route)
    result: list[Any] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        agent = config.agents.get(name)
        if agent is not None and _agent_allowed(config, agent) and not _excluded_for_coding(agent):
            result.append(agent)
    if result:
        return result
    return [
        agent
        for agent in config.agents.values()
        if _agent_allowed(config, agent) and not _excluded_for_coding(agent)
    ]


def _verified_coding_provider(
    config: HubConfig,
    agent: Any,
    health: dict[str, Any],
    *,
    local_servers: list[dict[str, Any]],
    local_model_rows: list[dict[str, Any]],
) -> bool:
    if not _agent_allowed(config, agent) or _excluded_for_coding(agent):
        return False
    provider = normalize_provider(agent.provider)
    provider_type = str(agent.provider_type or agent.provider or "").lower()
    if _local_model_verified(agent, local_model_rows):
        return True
    if not _route_ready(health):
        return False
    if _successful_health(health):
        return True
    if provider == "codex-cli" or provider_type == "codex-cli":
        return True
    if provider_type == "ollama-cloud" and _local_server_running(local_servers, "ollama"):
        return True
    if _is_remote_agent(agent) and getattr(agent, "resolved_api_key", None) and config.approval_mode == "auto":
        return True
    return False


def _provider_approval_needed(
    config: HubConfig,
    candidates: list[Any],
    provider_health: dict[str, dict[str, Any]],
    verified: list[dict[str, Any]],
) -> bool:
    if verified or config.approval_mode == "auto":
        return False
    for agent in candidates:
        if not _route_ready(provider_health.get(agent.name, {})):
            continue
        trust = provider_trust_level(agent)
        if trust in {TRUSTED_CLOUD, UNTRUSTED_EXTERNAL}:
            return True
    return False


def _verified_provider_row(name: str, agent: Any, health: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent": name,
        "provider": agent.provider,
        "provider_type": agent.provider_type or agent.provider,
        "model": agent.model,
        "degraded": bool(health.get("degraded")),
        "reliability_score": float(health.get("reliability_score") or 0.0),
        "success_count": int(health.get("success_count") or 0),
        "average_latency_ms": float(health.get("average_latency_ms") or health.get("latency_ms") or 0.0),
    }


def _agent_allowed(config: HubConfig, agent: Any) -> bool:
    return bool(getattr(agent, "enabled", False)) and (not config.free_only or is_free_agent(agent))


def _excluded_for_coding(agent: Any) -> bool:
    provider = normalize_provider(agent.provider)
    return provider in {"echo", "local-research"}


def _research_route_available(config: HubConfig) -> bool:
    agent = config.agents.get("local-research")
    if not (agent and agent.enabled and _agent_allowed(config, agent)):
        return False
    return any(
        getattr(route, "name", "") == "research"
        and "local-research" in list(getattr(route, "agents", []) or [])
        for route in config.routes
    )


def _route_ready(health: dict[str, Any]) -> bool:
    if not isinstance(health, dict) or not health.get("available"):
        return False
    now = time.time()
    if float(health.get("cooldown_until") or 0.0) > now:
        return False
    if float(health.get("unavailable_until") or 0.0) > now:
        return False
    return not (health.get("quota_exhausted") or health.get("rate_limited"))


def _successful_health(health: dict[str, Any]) -> bool:
    return int(health.get("success_count") or 0) > 0 and not health.get("last_error_type")


def _local_model_verified(agent: Any, rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if str(row.get("name") or "") != agent.name:
            continue
        if not row.get("online"):
            return False
        if row.get("configured_model_available") is False:
            return False
        return True
    return False


def _local_server_running(rows: list[dict[str, Any]], kind: str) -> bool:
    needle = kind.lower()
    return any(needle in str(row.get("name") or "").lower() and row.get("running") for row in rows)


def _is_remote_agent(agent: Any) -> bool:
    base_url = str(getattr(agent, "base_url", "") or "")
    return bool(base_url and not _is_local_url(base_url))


def _is_local_url(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered.startswith("http://127.0.0.1")
        or lowered.startswith("https://127.0.0.1")
        or lowered.startswith("http://localhost")
        or lowered.startswith("https://localhost")
        or lowered.startswith("http://[::1]")
        or lowered.startswith("https://[::1]")
    )


def _check(
    item_id: str,
    ok: bool,
    label: str,
    detail: str,
    command: str | None,
    *,
    weight: int,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "label": label,
        "status": "ok" if ok else "action",
        "ok": bool(ok),
        "weight": weight,
        "earned": weight if ok else 0,
        "detail": detail,
        **({"command": command} if command else {}),
    }


def _score(checks: list[dict[str, Any]]) -> int:
    total = sum(float(item.get("weight") or 0.0) for item in checks) or 1.0
    earned = sum(float(item.get("earned") or 0.0) for item in checks)
    return int(round((earned / total) * 100))


def _backend_detail(value: dict[str, Any] | None) -> str:
    if not isinstance(value, dict):
        return "Backend reachability was not checked."
    return f"{value.get('url', '')}: {value.get('detail', '')}".strip()


def _smoke_detail(smoke: dict[str, Any], coding_ok: bool, research_ok: bool) -> str:
    if coding_ok and research_ok:
        recorded = smoke.get("recorded_at")
        return f"Latest smoke is passing{f' at {recorded}' if recorded else ''}."
    if not smoke:
        return "No route smoke has been recorded yet."
    return "Latest smoke did not verify both research and coding routes."


def _state_path(config: HubConfig) -> Path:
    state_dir = Path(config.state_dir)
    if not state_dir.is_absolute():
        state_dir = Path(config.workspace_dir) / state_dir
    return state_dir / RUNTIME_USABILITY_STATE_FILE


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


__all__ = [
    "RUNTIME_USABILITY_STATE_FILE",
    "load_runtime_usability_record",
    "runtime_route_smoke",
    "runtime_usability_body",
    "save_runtime_usability_record",
]
