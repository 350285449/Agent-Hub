from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from ..capabilities import agent_capabilities
from ..config import AgentConfig, is_free_agent, normalize_provider
from ..models import HubRequest
from ..payloads import request_text
from ..providers.base import ProviderHealth as AdapterHealth


@dataclass(slots=True)
class ProviderHealth:
    """Serializable provider health record for score calculation and persistence."""

    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    tool_call_success_count: int = 0
    tool_call_failure_count: int = 0
    total_latency_seconds: float = 0.0
    total_tokens_per_second: float = 0.0
    tokens_per_second_sample_count: int = 0
    total_streaming_tokens_per_second: float = 0.0
    streaming_sample_count: int = 0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    last_checked_at: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    unavailable_until: float = 0.0
    cooldown_until: float = 0.0
    last_error_type: str = ""
    last_error_message: str = ""
    quota_remaining: float | None = None
    requests_remaining: int | None = None
    tokens_remaining: int | None = None
    credits_remaining: float | None = None
    rate_limit_reset_at: float | None = None
    rate_limited: bool = False
    quota_exhausted: bool = False
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_streaming: bool | None = None
    supports_tools: bool | None = None
    supports_json: bool | None = None
    supports_function_calling: bool | None = None
    last_request_source: str = ""
    last_route: str = ""
    last_request_started_at: float = 0.0
    last_first_token_latency_seconds: float = 0.0
    last_total_latency_seconds: float = 0.0
    last_input_tokens: int = 0
    last_output_tokens: int = 0
    last_tokens_per_second: float = 0.0
    last_finish_reason: str = ""
    last_failover_attempts: int = 0
    last_context_compaction_usage: dict[str, Any] = field(default_factory=dict)
    stream_interruption_count: int = 0
    quota_state: str = "unknown"
    failover_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        attempts = self.success_count + self.failure_count
        return 0.5 if attempts == 0 else self.success_count / attempts

    @property
    def reliability_score(self) -> float:
        attempts = self.success_count + self.failure_count
        score = 0.7 if attempts == 0 else self.success_count / attempts
        tool_attempts = self.tool_call_success_count + self.tool_call_failure_count
        if tool_attempts:
            score = (score * 0.75) + ((self.tool_call_success_count / tool_attempts) * 0.25)
        if attempts:
            score -= min(0.35, (self.timeout_count / attempts) * 0.25)
        return _clamp(score)

    @property
    def average_latency_seconds(self) -> float:
        return 0.0 if self.success_count == 0 else self.total_latency_seconds / self.success_count

    @property
    def average_latency_ms(self) -> float:
        return self.average_latency_seconds * 1000

    @property
    def streaming_tokens_per_second(self) -> float:
        if self.streaming_sample_count <= 0:
            return 0.0
        return self.total_streaming_tokens_per_second / self.streaming_sample_count

    @property
    def average_tokens_per_second(self) -> float:
        if self.tokens_per_second_sample_count <= 0:
            return 0.0
        return self.total_tokens_per_second / self.tokens_per_second_sample_count

    def cooldown_deadline(self) -> float:
        return max(self.cooldown_until, self.unavailable_until)

    def is_available(self, now: float | None = None) -> bool:
        now = now or time.time()
        deadline = self.cooldown_deadline()
        if deadline > now:
            return False
        if self.quota_exhausted and deadline > now:
            return False
        if self.quota_remaining is not None and self.quota_remaining <= 0:
            return False
        if self.requests_remaining is not None and self.requests_remaining <= 0:
            return False
        return True

    def is_degraded(self, now: float | None = None) -> bool:
        now = now or time.time()
        attempts = self.success_count + self.failure_count
        if self.cooldown_deadline() > now:
            return True
        if self.rate_limited:
            return True
        if self.quota_exhausted and self.cooldown_deadline() > now:
            return True
        if attempts >= 3 and self.reliability_score < 0.45:
            return True
        if self.timeout_count >= 2 and self.timeout_count >= self.success_count:
            return True
        if self.success_count >= 2 and self.average_latency_seconds > 45:
            return True
        return False


@dataclass(slots=True)
class ProviderScore:
    total: float
    reliability: float
    latency: float
    context: float
    coding: float
    tool_support: float
    streaming: float
    free_local: float
    quota: float
    cost_efficiency: float
    token_efficiency: float
    cooldown: float
    capability_score: float = 0.0
    health_score: float = 0.0
    speed_score: float = 0.0
    quota_score: float = 0.0
    context_score: float = 0.0
    user_preference_score: float = 0.0
    cost_penalty: float = 0.0
    recent_failure_penalty: float = 0.0
    cooldown_penalty: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {item.name: round(float(getattr(self, item.name)), 4) for item in fields(self)}


class ProviderHealthManager:
    """Small persistence and scoring facade used by routers and future dashboards."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, ProviderHealth]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        agents = raw.get("agents") if isinstance(raw, dict) else None
        if not isinstance(agents, dict):
            return {}
        valid = {item.name for item in fields(ProviderHealth)}
        result: dict[str, ProviderHealth] = {}
        for name, data in agents.items():
            if not isinstance(name, str) or not isinstance(data, dict):
                continue
            values = {key: data[key] for key in valid if key in data}
            try:
                result[name] = ProviderHealth(**values)
            except TypeError:
                continue
        return result

    def save(self, health: dict[str, Any]) -> None:
        payload = {
            "version": 1,
            "updated_at": time.time(),
            "agents": {
                name: health_to_state(value)
                for name, value in sorted(health.items())
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f"{self.path.name}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.path)

    def score(
        self,
        agent: AgentConfig,
        health: Any,
        *,
        request: HubRequest | None = None,
        now: float | None = None,
    ) -> ProviderScore:
        return calculate_provider_score(agent, health, request=request, now=now)


class ProviderHealthTracker(ProviderHealthManager):
    """Canonical provider-health facade shared by diagnostics and routing code."""


def calculate_provider_score(
    agent: AgentConfig,
    health: Any = None,
    *,
    request: HubRequest | None = None,
    now: float | None = None,
) -> ProviderScore:
    now = now or time.time()
    capabilities = agent_capabilities(agent)
    reliability = _float_attr(health, "reliability_score", 0.7) * 30.0
    latency_seconds = _float_attr(health, "average_latency_seconds", 0.0)
    latency = 12.0 if latency_seconds <= 0 else max(0.0, 12.0 - min(12.0, latency_seconds / 2.5))
    context = min(14.0, float(capabilities.context_window or 0) / 16_000)
    coding = float(agent.coding_score or 0.0) * 12.0
    tool_support = 8.0 if capabilities.tool_capable else 0.0
    streaming = 6.0 if capabilities.supports_streaming else 0.0
    streaming_speed = _float_attr(health, "streaming_tokens_per_second", 0.0)
    if streaming_speed:
        streaming += min(4.0, streaming_speed / 25.0)
    free_local = 6.0 if is_free_agent(agent) or _is_local_or_private_agent(agent) else 0.0
    cost_efficiency = provider_cost_efficiency_score(agent)
    quota = 0.0
    token_efficiency = 0.0
    cooldown = 0.0
    deadline = max(
        _float_attr(health, "cooldown_until", 0.0),
        _float_attr(health, "unavailable_until", 0.0),
    )

    if bool(getattr(health, "quota_exhausted", False)) and deadline > now:
        quota -= 80.0
    if _number_attr(health, "quota_remaining") is not None and _number_attr(health, "quota_remaining") <= 0:
        quota -= 80.0
    if _number_attr(health, "requests_remaining") is not None and _number_attr(health, "requests_remaining") <= 0:
        quota -= 80.0
    if _number_attr(health, "credits_remaining") is not None and _number_attr(health, "credits_remaining") <= 0:
        quota -= 80.0
    if request is not None:
        required = _estimated_required_tokens(request, agent)
        remaining = _number_attr(health, "tokens_remaining")
        if remaining is not None and remaining < required:
            quota -= 60.0
        text = request_text(request).lower()
        if any(word in text for word in ("bug", "code", "debug", "edit", "fix", "refactor", "test")):
            coding *= 1.35
        if request.stream and capabilities.supports_streaming:
            streaming += 4.0
    tokens_in = _number_attr(health, "tokens_in")
    tokens_out = _number_attr(health, "tokens_out")
    if tokens_in is not None and tokens_in > 0 and tokens_out is not None:
        token_efficiency = min(3.0, max(0.0, tokens_out / tokens_in))
    average_tps = _float_attr(health, "average_tokens_per_second", 0.0)
    if average_tps:
        token_efficiency += min(3.0, average_tps / 25.0)

    if deadline > now:
        cooldown -= 100.0

    total = (
        float(agent.priority or 0.0)
        + reliability
        + latency
        + context
        + coding
        + tool_support
        + streaming
        + free_local
        + cost_efficiency
        + quota
        + token_efficiency
        + cooldown
    )
    if normalize_provider(agent.provider) == "echo":
        total -= 5000.0
    return ProviderScore(
        total=total,
        reliability=reliability,
        latency=latency,
        context=context,
        coding=coding,
        tool_support=tool_support,
        streaming=streaming,
        free_local=free_local,
        quota=quota,
        cost_efficiency=cost_efficiency,
        token_efficiency=token_efficiency,
        cooldown=cooldown,
        capability_score=coding + tool_support + streaming,
        health_score=reliability,
        speed_score=latency + token_efficiency,
        quota_score=quota,
        context_score=context,
        user_preference_score=free_local,
        cost_penalty=min(0.0, cost_efficiency),
        recent_failure_penalty=0.0,
        cooldown_penalty=cooldown,
    )


def provider_cost_efficiency_score(agent: AgentConfig) -> float:
    """Return a small routing bonus for low known token cost."""

    input_cost = _optional_cost(getattr(agent, "cost_per_million_input", None))
    output_cost = _optional_cost(getattr(agent, "cost_per_million_output", None))
    costs = [value for value in (input_cost, output_cost) if value is not None]
    if not costs:
        return 0.0
    average = sum(costs) / len(costs)
    if average <= 0:
        return 5.0
    if average <= 0.25:
        return 4.0
    if average <= 1.0:
        return 3.0
    if average <= 5.0:
        return 1.5
    if average <= 15.0:
        return 0.5
    return -2.0


def _optional_cost(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def health_to_state(health: Any) -> dict[str, Any]:
    if isinstance(health, dict):
        return dict(health)
    return {
        item.name: getattr(health, item.name)
        for item in fields(health)
    }


def health_state_label(row: dict[str, Any]) -> str:
    if not row.get("available"):
        return "cooldown" if row.get("cooldown_until") else "unavailable"
    if row.get("degraded"):
        return "degraded"
    if row.get("failure_count", 0):
        return "recovering"
    return "healthy"


def _estimated_required_tokens(request: HubRequest, agent: AgentConfig) -> int:
    input_tokens = max(1, len(request_text(request)) // 4)
    output_tokens = request.max_tokens or agent.max_tokens or 0
    try:
        return input_tokens + max(0, int(output_tokens))
    except (TypeError, ValueError):
        return input_tokens


def _is_local_or_private_agent(agent: AgentConfig) -> bool:
    from ..config import _is_local_or_private_url

    provider = normalize_provider(agent.provider)
    provider_type = (agent.provider_type or agent.provider).lower()
    if provider in {"echo", "local-research"}:
        return True
    if provider_type == "ollama-cloud":
        return False
    return _is_local_or_private_url(agent.base_url)


def _number_attr(value: Any, name: str) -> float | None:
    raw = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _float_attr(value: Any, name: str, default: float) -> float:
    raw = value.get(name) if isinstance(value, dict) else getattr(value, name, default)
    if callable(raw):
        raw = raw()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


__all__ = [
    "AdapterHealth",
    "ProviderHealth",
    "ProviderHealthTracker",
    "ProviderHealthManager",
    "ProviderScore",
    "calculate_provider_score",
    "health_state_label",
    "health_to_state",
    "provider_cost_efficiency_score",
]
