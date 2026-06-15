from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import AgentConfig, HubConfig


@dataclass(slots=True)
class TokenPoolSimulationRequest:
    estimated_tokens: int = 0
    provider: str = ""
    model: str = ""
    agent: str = ""


def simulate_token_pooling(config: HubConfig, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a policy-safe token-pool recommendation without spending tokens.

    Token pooling is intentionally limited to configured, user-owned quotas. This
    function never discovers accounts, rotates hidden credentials, scrapes quota
    sources, or changes router execution order.
    """

    payload = payload if isinstance(payload, dict) else {}
    request = _simulation_request(payload)
    pools = [_normalize_pool(item) for item in getattr(config, "token_pooling_pools", []) or []]
    pools = [pool for pool in pools if pool]
    candidates = [
        _pool_candidate(pool, config=config, request=request)
        for pool in pools
        if _pool_matches_request(pool, config=config, request=request)
    ]
    ranked = sorted(
        candidates,
        key=lambda item: (
            not item["eligible"],
            -float(item.get("remaining_tokens") or 0),
            float(item.get("cost_per_million_input") or 0),
            item["id"],
        ),
    )
    selected = next((item for item in ranked if item["eligible"]), None)
    enabled = bool(getattr(config, "token_pooling_enabled", False))
    warnings: list[str] = []
    if not enabled:
        warnings.append("token_pooling_disabled")
    if not pools:
        warnings.append("no_token_pools_configured")
    if pools and not ranked:
        warnings.append("no_token_pools_match_request")
    if ranked and selected is None:
        warnings.append("no_eligible_token_pool")
    return {
        "object": "agent_hub.token_pool_simulation",
        "enabled": enabled,
        "dry_run": True,
        "request": {
            "estimated_tokens": request.estimated_tokens,
            "provider": request.provider,
            "model": request.model,
            "agent": request.agent,
        },
        "policy": {
            "user_owned_quotas_only": True,
            "terms_confirmed_required": True,
            "no_scraping": True,
            "no_limit_bypass": True,
            "execution_changes": False,
        },
        "selected": selected if enabled else None,
        "candidates": ranked,
        "warnings": warnings,
    }


def _simulation_request(payload: dict[str, Any]) -> TokenPoolSimulationRequest:
    estimated = payload.get("estimated_tokens", payload.get("tokens", payload.get("max_tokens", 0)))
    try:
        estimated_tokens = int(estimated)
    except (TypeError, ValueError):
        estimated_tokens = 0
    return TokenPoolSimulationRequest(
        estimated_tokens=max(0, estimated_tokens),
        provider=str(payload.get("provider") or "").strip().lower(),
        model=str(payload.get("model") or "").strip(),
        agent=str(payload.get("agent") or payload.get("agent_name") or "").strip(),
    )


def _normalize_pool(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    pool_id = str(value.get("id") or value.get("name") or "").strip()
    if not pool_id:
        return {}
    return {
        "id": pool_id,
        "enabled": _bool_value(value.get("enabled"), True),
        "provider": str(value.get("provider") or "").strip().lower(),
        "agents": _string_list(value.get("agents")),
        "models": _string_list(value.get("models")),
        "remaining_tokens": _int_value(value.get("remaining_tokens", value.get("quota_remaining"))),
        "remaining_requests": _int_value(value.get("remaining_requests", value.get("requests_remaining"))),
        "cost_per_million_input": _float_value(value.get("cost_per_million_input")),
        "user_owned_quota": _bool_value(value.get("user_owned_quota"), False),
        "terms_confirmed": _bool_value(value.get("terms_confirmed"), False),
        "notes": str(value.get("notes") or ""),
    }


def _pool_matches_request(
    pool: dict[str, Any],
    *,
    config: HubConfig,
    request: TokenPoolSimulationRequest,
) -> bool:
    if request.agent:
        return request.agent in set(pool.get("agents") or [])
    if request.provider and pool.get("provider") and request.provider != pool.get("provider"):
        return False
    if request.model and pool.get("models") and request.model not in set(pool.get("models") or []):
        return False
    if not request.provider and not request.model:
        return True
    for agent_name in pool.get("agents") or []:
        agent = config.agents.get(agent_name)
        if not agent:
            continue
        if _agent_matches(agent, request):
            return True
    return bool(pool.get("provider") or pool.get("models"))


def _pool_candidate(
    pool: dict[str, Any],
    *,
    config: HubConfig,
    request: TokenPoolSimulationRequest,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not pool["enabled"]:
        reasons.append("pool_disabled")
    if not pool["user_owned_quota"]:
        reasons.append("user_owned_quota_not_confirmed")
    if not pool["terms_confirmed"]:
        reasons.append("provider_terms_not_confirmed")
    if request.estimated_tokens and pool["remaining_tokens"] is not None and pool["remaining_tokens"] < request.estimated_tokens:
        reasons.append("insufficient_remaining_tokens")
    if pool["remaining_requests"] is not None and pool["remaining_requests"] <= 0:
        reasons.append("no_remaining_requests")
    agents = [
        _agent_summary(config.agents[name])
        for name in pool.get("agents") or []
        if name in config.agents
    ]
    return {
        "id": pool["id"],
        "eligible": not reasons,
        "reasons": reasons,
        "provider": pool["provider"],
        "agents": agents,
        "models": list(pool.get("models") or []),
        "remaining_tokens": pool["remaining_tokens"],
        "remaining_requests": pool["remaining_requests"],
        "cost_per_million_input": pool["cost_per_million_input"],
        "user_owned_quota": pool["user_owned_quota"],
        "terms_confirmed": pool["terms_confirmed"],
        "notes": pool["notes"],
    }


def _agent_matches(agent: AgentConfig, request: TokenPoolSimulationRequest) -> bool:
    if request.provider and request.provider != str(agent.provider or "").lower():
        return False
    if request.model and request.model != agent.model:
        return False
    return True


def _agent_summary(agent: AgentConfig) -> dict[str, Any]:
    return {
        "name": agent.name,
        "provider": agent.provider,
        "model": agent.model,
        "free": agent.free,
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _bool_value(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def _int_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _float_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


__all__ = ["simulate_token_pooling"]
