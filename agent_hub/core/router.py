from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, fields, replace
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import AgentConfig, HubConfig, is_free_agent, normalize_provider
from ..models import FailoverEvent, HubRequest, HubResponse, ProviderResult
from ..observability import record_event
from ..payloads import content_to_text, request_text
from ..permissions import (
    PermissionManager,
    approval_mode_from_request,
    provider_approval_granted_from_request,
    provider_permission_request,
)
from ..providers import Provider, ProviderError, create_provider
from ..session_store import SessionStore
from ..token_budget import TokenBudgetManager, estimate_messages_tokens
from .provider_manager import ProviderManager


ProviderFactory = Callable[[AgentConfig], Provider]
HEALTH_STATE_VERSION = 1
HEALTH_STATE_FILE = "provider_health.json"
HEALTH_STALE_SECONDS = 7 * 24 * 60 * 60
MAX_FAILOVER_HISTORY = 50
TRANSPARENT_API_SHAPES = {"openai-chat", "openai-responses", "anthropic-messages"}
NO_TOOL_CAPABLE_MODEL = "no_tool_capable_model"
ECHO_DISABLED = "echo_disabled"
CONFIGURATION_ERROR = "configuration_error"
ROUTING_MODES = {
    "manual",
    "fastest",
    "cheapest",
    "best_available",
    "coding",
    "long_context",
    "local_private",
}
DEFAULT_ROUTING_MODE = "best_available"
LONG_CONTEXT_TOKEN_THRESHOLD = 24_000


@dataclass(slots=True)
class RoutingDecision:
    """Explainable router selection before provider execution and failover."""

    selected_provider: str
    selected_model: str
    routing_mode: str
    reason: str
    fallback_chain: list[str] = field(default_factory=list)
    selected_agent: str | None = None
    task_type: str | None = None
    estimated_input_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_agent": self.selected_agent,
            "selected_provider": self.selected_provider,
            "selected_model": self.selected_model,
            "routing_mode": self.routing_mode,
            "task_type": self.task_type,
            "reason": self.reason,
            "fallback_chain": list(self.fallback_chain),
            "estimated_input_tokens": self.estimated_input_tokens,
        }


@dataclass(slots=True)
class ProviderHealth:
    """Rolling health data used for provider balancing and diagnostics."""

    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    tool_call_success_count: int = 0
    tool_call_failure_count: int = 0
    total_latency_seconds: float = 0.0
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
            tool_score = self.tool_call_success_count / tool_attempts
            score = (score * 0.75) + (tool_score * 0.25)
        if attempts:
            score -= min(0.35, (self.timeout_count / attempts) * 0.25)
        return max(0.0, min(1.0, score))

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

    def cooldown_deadline(self) -> float:
        return max(self.cooldown_until, self.unavailable_until)

    def is_available(self, now: float | None = None) -> bool:
        now = now or time.time()
        if self.cooldown_deadline() > now:
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
        if attempts >= 3 and self.reliability_score < 0.45:
            return True
        if self.timeout_count >= 2 and self.timeout_count >= self.success_count:
            return True
        if self.success_count >= 2 and self.average_latency_seconds > 45:
            return True
        return False


class RouterError(Exception):
    def __init__(
        self,
        message: str,
        failover: list[FailoverEvent] | None = None,
        *,
        error_type: str | None = None,
        suggested_fix: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.failover = failover or []
        self.error_type = error_type
        self.suggested_fix = suggested_fix
        self.status_code = status_code


class AgentRouter:
    def __init__(
        self,
        config: HubConfig,
        provider_factory: ProviderFactory = create_provider,
        session_store: SessionStore | None = None,
    ) -> None:
        self.config = config
        self._provider_factory = provider_factory
        self.session_store = session_store or SessionStore(config.state_dir)
        self._health_path = config.state_dir / HEALTH_STATE_FILE
        self._health: dict[str, ProviderHealth] = self._load_provider_health()
        self._cooldowns: dict[str, float] = {
            name: health.cooldown_deadline()
            for name, health in self._health.items()
            if health.cooldown_deadline() > time.time()
        }
        self.provider_manager = ProviderManager(
            config,
            provider_factory=self._provider_factory,
            health_snapshot=self.health_snapshot,
        )

    @property
    def provider_factory(self) -> ProviderFactory:
        return self._provider_factory

    @provider_factory.setter
    def provider_factory(self, value: ProviderFactory) -> None:
        self._provider_factory = value
        if hasattr(self, "provider_manager"):
            self.provider_manager.provider_factory = value

    def route(self, request: HubRequest) -> HubResponse:
        effective_request = self._with_session_history(request)
        request_id = f"hub-{uuid.uuid4().hex}"
        failover: list[FailoverEvent] = []
        decision = self.decide(effective_request)
        candidates = self._candidate_agents(effective_request, decision=decision)
        self._record_route_event(
            "request_started",
            request_id=request_id,
            request=effective_request,
            routing_decision=decision.to_dict(),
            candidates=[agent.name for agent in candidates],
        )
        if not candidates:
            raise RouterError(
                _no_model_available_message(),
                error_type=CONFIGURATION_ERROR,
                suggested_fix=_no_model_available_fix(),
                status_code=400,
            )

        tried_any = False
        for agent in candidates:
            if self._is_on_cooldown(agent.name) and len(candidates) > 1:
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason="Agent is in temporary cooldown from a previous failure",
                        unavailable_until=self._cooldown_until(agent.name),
                    )
                )
                continue

            skip_reason = self._preflight_skip_reason(agent, effective_request)
            if skip_reason:
                error_type = self._preflight_error_type(agent, effective_request, skip_reason)
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason=skip_reason,
                        retryable=False,
                        error_type=error_type,
                    )
                )
                continue

            permission = self._provider_permission_decision(agent, effective_request)
            if permission is not None and not permission.allowed:
                reason = permission.reason or "Permission required before using this provider."
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason=reason,
                        retryable=False,
                        error_type="permission_required" if permission.requires_approval else "permission_denied",
                        metadata={"permission": permission.request.to_dict() if permission.request else None},
                    )
                )
                self._record_route_event(
                    "provider_permission_blocked",
                    request_id=request_id,
                    request=effective_request,
                    agent=agent.name,
                    provider=agent.provider,
                    model=agent.model,
                    decision=permission.to_dict(),
                )
                continue

            tried_any = True
            started = time.perf_counter()
            try:
                result = self.provider_manager.chat(agent, effective_request)
                latency = time.perf_counter() - started
                if _token_limit_finish_reason(result.finish_reason) and agent != candidates[-1]:
                    reason = (
                        "Agent stopped because it hit a token limit; "
                        "retrying with the next configured agent"
                    )
                    self._record_failure(
                        agent,
                        error_type="context_limit",
                        message=reason,
                        unavailable_until=time.time() + agent.cooldown_seconds,
                        metadata={},
                    )
                    self._cooldowns[agent.name] = time.time() + agent.cooldown_seconds
                    failover.append(
                        FailoverEvent(
                            agent=agent.name,
                            provider=agent.provider,
                            model=agent.model,
                            reason=reason,
                            error_type="context_limit",
                            unavailable_until=self._cooldowns.get(agent.name),
                        )
                    )
                    continue
                self._record_success(agent, latency, result, effective_request)
                response = self._response_from_result(
                    request_id=request_id,
                    request=effective_request,
                    agent=agent,
                    result=result,
                    failover=failover,
                    decision=decision,
                )
                if effective_request.record_session:
                    self.session_store.record_turn(effective_request, response)
                self._record_route_event(
                    "routing_decision",
                    request_id=request_id,
                    request=effective_request,
                    agent=agent.name,
                    provider=agent.provider,
                    model=response.model,
                    latency_seconds=round(latency, 4),
                    failover=[event.to_dict() for event in failover],
                    routing_decision=decision.to_dict(),
                )
                return response
            except ProviderError as exc:
                cooldown_seconds = self._cooldown_seconds(agent, exc)
                unavailable_until = time.time() + cooldown_seconds if exc.retryable and cooldown_seconds > 0 else None
                self._record_failure(
                    agent,
                    error_type=exc.error_type,
                    message=str(exc),
                    unavailable_until=unavailable_until,
                    status_code=exc.status_code,
                    metadata=exc.metadata or {},
                )
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason=str(exc),
                        status_code=exc.status_code,
                        retryable=exc.retryable,
                        error_type=exc.error_type,
                        unavailable_until=unavailable_until,
                    )
                )
                if exc.retryable:
                    self._cooldowns[agent.name] = unavailable_until or time.time()
                    continue
                self._record_route_event(
                    "routing_failure",
                    request_id=request_id,
                    request=effective_request,
                    agent=agent.name,
                    provider=agent.provider,
                    model=agent.model,
                    error_type=exc.error_type,
                    message=str(exc),
                    failover=[event.to_dict() for event in failover],
                )
                raise RouterError(str(exc), failover=failover) from exc

        if not tried_any:
            reason = _no_fallback_reason(failover)
            error_type = _route_error_type(failover)
            self._record_route_event(
                "routing_failure",
                request_id=request_id,
                request=effective_request,
                message=reason,
                error_type=error_type,
                failover=[event.to_dict() for event in failover],
            )
            raise RouterError(
                reason,
                failover=failover,
                error_type=error_type,
                suggested_fix=_suggested_fix(error_type, failover),
                status_code=_route_status_code(error_type),
            )

        reason = _no_fallback_reason(failover)
        error_type = _route_error_type(failover)
        self._record_route_event(
            "routing_failure",
            request_id=request_id,
            request=effective_request,
            message=reason,
            error_type=error_type,
            failover=[event.to_dict() for event in failover],
        )
        raise RouterError(
            reason,
            failover=failover,
            error_type=error_type,
            suggested_fix=_suggested_fix(error_type, failover),
            status_code=_route_status_code(error_type),
        )

    def _provider_permission_decision(self, agent: AgentConfig, request: HubRequest):
        permission_request = provider_permission_request(agent, request)
        if permission_request is None:
            return None
        decision = PermissionManager(
            approval_mode_from_request(request, self.config.approval_mode),
            approval_granted=provider_approval_granted_from_request(request),
        ).check(permission_request)
        record_event(
            self.config.state_dir,
            "permissions",
            {
                "type": "provider_permission",
                "session_id": request.session_id,
                "agent": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "allowed": decision.allowed,
                "requires_approval": decision.requires_approval,
                "denied": decision.denied,
                "reason": decision.reason,
                "mode": decision.mode,
                "category": permission_request.category,
                "risk_level": permission_request.risk_level,
                "resource": permission_request.resource,
            },
        )
        return decision

    def _with_session_history(self, request: HubRequest) -> HubRequest:
        if not request.use_session_history:
            return request
        history = self.session_store.load(request.session_id).get("messages", [])
        if not history:
            return request
        if _is_prefix(history, request.messages):
            return request
        if _is_prefix(request.messages, history):
            return replace(request, messages=list(history))
        return replace(request, messages=[*history, *request.messages])

    def decide(self, request: HubRequest) -> RoutingDecision:
        """Choose a ranked fallback chain before execution."""

        mode = self._routing_mode(request)
        task_type = self._classify_task(request)
        agents = self._candidate_agent_pool(request, mode=mode)
        selected = agents[0] if agents else None
        return RoutingDecision(
            selected_agent=selected.name if selected else None,
            selected_provider=selected.provider if selected else "",
            selected_model=selected.model if selected else "",
            routing_mode=mode,
            task_type=task_type,
            reason=self._routing_decision_reason(
                mode=mode,
                task_type=task_type,
                selected=selected,
                request=request,
            ),
            fallback_chain=[agent.name for agent in agents],
            estimated_input_tokens=estimate_input_tokens(request),
        )

    def _candidate_agents(
        self,
        request: HubRequest,
        *,
        decision: RoutingDecision | None = None,
    ) -> list[AgentConfig]:
        if decision is None:
            decision = self.decide(request)
        return [
            self.config.agents[name]
            for name in decision.fallback_chain
            if name in self.config.agents and self.config.agents[name].enabled
        ]

    def _candidate_agent_pool(self, request: HubRequest, *, mode: str) -> list[AgentConfig]:
        names: list[str] = []
        if request.preferred_agent:
            names.append(request.preferred_agent)
        names.extend(self._manual_model_or_provider_agent_names(request))
        names.extend(self._route_names(request))
        if mode == "local_private":
            names.extend(
                agent.name
                for agent in self.config.agents.values()
                if _is_local_or_private_agent(agent)
            )

        seen: set[str] = set()
        agents: list[AgentConfig] = []
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            agent = self.config.agents.get(name)
            if agent and agent.enabled:
                agents.append(agent)
        if request.preferred_agent and agents and agents[0].name == request.preferred_agent:
            return [agents[0], *self._rank_agents_for_mode(agents[1:], request, mode)]
        return self._rank_agents_for_mode(agents, request, mode)

    def _route_names(self, request: HubRequest) -> list[str]:
        if request.route:
            for route in self.config.routes:
                if route.name == request.route:
                    return route.agents
        text = request_text(request)
        for route in self.config.routes:
            if route.matches(text):
                return route.agents
        return self.config.default_route

    def _manual_model_or_provider_agent_names(self, request: HubRequest) -> list[str]:
        model = _request_option(request, "model")
        provider = _request_option(request, "provider", "provider_type")
        names: list[str] = []
        if isinstance(model, str) and model.strip():
            normalized_model = model.strip().lower()
            for agent in self.config.agents.values():
                if agent.model.lower() == normalized_model or agent.name.lower() == normalized_model:
                    names.append(agent.name)
        if isinstance(provider, str) and provider.strip():
            normalized_provider = normalize_provider(provider.strip())
            raw_provider = provider.strip().lower()
            for agent in self.config.agents.values():
                agent_provider = normalize_provider(agent.provider)
                agent_type = (agent.provider_type or agent.provider).lower()
                if agent_provider == normalized_provider or agent_type == raw_provider:
                    names.append(agent.name)
        return names

    def _routing_mode(self, request: HubRequest) -> str:
        explicit = _request_option(
            request,
            "routing_mode",
            "route_mode",
            "routingMode",
            "routeMode",
        )
        if isinstance(explicit, str) and explicit.strip().lower() in ROUTING_MODES:
            return explicit.strip().lower()
        prefer = _request_option(request, "prefer", "preference")
        if isinstance(prefer, str):
            lowered = prefer.strip().lower()
            if lowered == "speed":
                return "fastest"
            if lowered in ROUTING_MODES:
                return lowered
        if request.preferred_agent or self._manual_model_or_provider_agent_names(request):
            return "manual"
        if _privacy_requested(request):
            return "local_private"
        task_type = self._classify_task(request)
        if task_type in {"coding", "long_context"}:
            return task_type
        return DEFAULT_ROUTING_MODE

    def _classify_task(self, request: HubRequest) -> str:
        if _privacy_requested(request):
            return "local_private"
        if estimate_input_tokens(request) >= LONG_CONTEXT_TOKEN_THRESHOLD:
            return "long_context"
        if _looks_like_coding_task(request_text(request).lower()):
            return "coding"
        return "general"

    def _rank_agents_for_mode(
        self,
        agents: list[AgentConfig],
        request: HubRequest,
        mode: str,
    ) -> list[AgentConfig]:
        if mode == "manual":
            return self._balanced_agents(agents, request)
        if mode == "local_private":
            private_agents = [agent for agent in agents if _is_local_or_private_agent(agent)]
            return self._rank_by_key(
                private_agents,
                request,
                key=lambda agent: (
                    float(agent.coding_score or 0.0) * 8,
                    float(agent.context_window or 0),
                    self._routing_score(agent, request),
                ),
            )
        if mode == "fastest":
            return self._rank_by_key(
                agents,
                request,
                key=lambda agent: (
                    float(agent.speed_score or 0.0) * 12,
                    self._streaming_speed_score(agent),
                    -self._average_latency_score(agent),
                    self._routing_score(agent, request),
                ),
            )
        if mode == "cheapest":
            return self._rank_by_key(
                agents,
                request,
                key=lambda agent: (
                    1.0 if is_free_agent(agent) else 0.0,
                    1.0 if _is_local_or_private_agent(agent) else 0.0,
                    self._routing_score(agent, request),
                ),
            )
        if mode == "coding":
            return self._rank_by_key(
                agents,
                request,
                key=lambda agent: (
                    float(agent.coding_score or 0.0) * 16,
                    4.0 if _agent_supports_tools(agent) else 0.0,
                    self._routing_score(agent, request),
                ),
            )
        if mode == "long_context":
            return self._rank_by_key(
                agents,
                request,
                key=lambda agent: (
                    float(agent.context_window or 0),
                    self._routing_score(agent, request),
                ),
            )
        return self._balanced_agents(agents, request)

    def _rank_by_key(
        self,
        agents: list[AgentConfig],
        request: HubRequest,
        *,
        key: Callable[[AgentConfig], tuple[Any, ...]],
    ) -> list[AgentConfig]:
        if not self.config.enable_load_balancing or len(agents) <= 1:
            return agents
        indexed = list(enumerate(agents))
        return [
            agent
            for _, agent in sorted(
                indexed,
                key=lambda item: (*_negated_sort_tuple(key(item[1])), item[0]),
            )
        ]

    def _streaming_speed_score(self, agent: AgentConfig) -> float:
        health = self._health.get(agent.name)
        if health and health.streaming_tokens_per_second:
            return health.streaming_tokens_per_second
        return 1.0 if agent.supports_streaming else 0.0

    def _average_latency_score(self, agent: AgentConfig) -> float:
        health = self._health.get(agent.name)
        return health.average_latency_seconds if health else 0.0

    def _routing_decision_reason(
        self,
        *,
        mode: str,
        task_type: str,
        selected: AgentConfig | None,
        request: HubRequest,
    ) -> str:
        if selected is None:
            return "No enabled provider matched the requested route and routing mode."
        if mode == "manual":
            return "Manual model/provider preference was applied before fallback candidates."
        if mode == "fastest":
            return "Selected the highest-ranked low-latency candidate using speed score and observed latency."
        if mode == "cheapest":
            return "Selected the highest-ranked free or local/private candidate."
        if mode == "coding":
            return "Prompt was classified as coding-related and ranked by coding/tool capability."
        if mode == "long_context":
            return "Prompt was classified as long-context and ranked by context window."
        if mode == "local_private":
            return "Privacy/local mode was requested, so only local/private providers were considered."
        if request.stream and selected.supports_streaming:
            return "Selected best available streaming-capable route candidate."
        if task_type != "general":
            return f"Selected best available candidate for {task_type} task."
        return "Selected best available route candidate using priority, health, and capability scores."

    def _response_from_result(
        self,
        request_id: str,
        request: HubRequest,
        agent: AgentConfig,
        result: ProviderResult,
        failover: list[FailoverEvent],
        decision: RoutingDecision | None = None,
    ) -> HubResponse:
        raw = result.raw
        if self.config.expose_routing_details and isinstance(raw, dict):
            raw = dict(raw)
            agent_metadata = dict(raw.get("agent_hub") or {})
            selected_health = self.health_snapshot().get(agent.name, {})
            agent_metadata["selected_health"] = selected_health
            agent_metadata["active_model"] = {
                "agent": agent.name,
                "provider": agent.provider,
                "provider_name": agent.provider,
                "provider_type": agent.provider_type or normalize_provider(agent.provider),
                "model": result.model or agent.model,
            }
            agent_metadata["limits"] = _agent_limit_metadata(agent, selected_health)
            agent_metadata["failed_models"] = [
                {
                    "agent": event.agent,
                    "provider": event.provider,
                    "model": event.model,
                    "reason": event.reason,
                    "retryable": event.retryable,
                }
                for event in failover
            ]
            agent_metadata["fallback_models"] = [
                {
                    "agent": event.agent,
                    "provider": event.provider,
                    "model": event.model,
                    "reason": event.reason,
                    "retryable": event.retryable,
                }
                for event in failover
            ]
            if decision is not None:
                agent_metadata["routing_decision"] = decision.to_dict()
            raw["agent_hub"] = agent_metadata
        return HubResponse(
            request_id=request_id,
            session_id=request.session_id,
            agent=agent.name,
            provider=agent.provider,
            model=result.model or agent.model,
            public_model=_public_model_name(request),
            text=result.text,
            usage=result.usage,
            raw=raw,
            finish_reason=result.finish_reason,
            failover=list(failover),
            citations=result.citations,
            search_results=result.search_results,
            images=result.images,
            related_questions=result.related_questions,
        )

    def _is_on_cooldown(self, agent_name: str) -> bool:
        return self._cooldown_until(agent_name) > time.time()

    def _cooldown_until(self, agent_name: str) -> float:
        health = self._health.get(agent_name)
        return max(
            self._cooldowns.get(agent_name, 0.0),
            health.cooldown_deadline() if health else 0.0,
        )

    def cooldown_agent(self, agent_name: str, seconds: float | None = None) -> None:
        agent = self.config.agents.get(agent_name)
        duration = seconds if seconds is not None else (agent.cooldown_seconds if agent else 0)
        if duration <= 0:
            return
        cooldown_until = time.time() + duration
        self._cooldowns[agent_name] = cooldown_until
        health = self._health.setdefault(agent_name, ProviderHealth())
        health.cooldown_until = max(health.cooldown_until, cooldown_until)
        health.unavailable_until = max(health.unavailable_until, cooldown_until)
        health.last_checked_at = time.time()
        self._save_provider_health()

    def health_snapshot(self, *, include_history: bool = False) -> dict[str, dict[str, Any]]:
        """Return normalized provider health for diagnostics and tests."""

        now = time.time()
        names = sorted(set(self.config.agents) | set(self._health))
        snapshot: dict[str, dict[str, Any]] = {}
        for name in names:
            health = self._health.get(name, ProviderHealth())
            agent = self.config.agents.get(name)
            cooldown_until = max(self._cooldowns.get(name, 0.0), health.cooldown_deadline())
            available = bool(agent.enabled) if agent else False
            if agent and self.config.free_only and not is_free_agent(agent):
                available = False
            if agent and _requires_missing_api_key(agent):
                available = False
            if agent and _is_echo_agent(agent) and not self.config.debug_echo_enabled:
                available = False
            row: dict[str, Any] = {
                "agent": name,
                "provider": agent.provider if agent else "",
                "provider_name": agent.provider if agent else "",
                "provider_type": (
                    agent.provider_type or normalize_provider(agent.provider)
                    if agent else ""
                ),
                "model": agent.model if agent else "",
                "available": available,
                "degraded": health.is_degraded(now),
                "quota_remaining": health.quota_remaining,
                "requests_remaining": health.requests_remaining,
                "tokens_remaining": health.tokens_remaining,
                "credits_remaining": health.credits_remaining,
                "cooldown_until": cooldown_until,
                "unavailable_until": cooldown_until,
                "rate_limit_reset_at": health.rate_limit_reset_at,
                "average_latency_ms": round(health.average_latency_ms, 2),
                "average_latency_seconds": round(health.average_latency_seconds, 4),
                "streaming_tokens_per_second": round(health.streaming_tokens_per_second, 4),
                "reliability_score": round(health.reliability_score, 4),
                "success_count": health.success_count,
                "failure_count": health.failure_count,
                "timeout_count": health.timeout_count,
                "tool_call_success_count": health.tool_call_success_count,
                "tool_call_failure_count": health.tool_call_failure_count,
                "success_rate": round(health.success_rate, 4),
                "last_success_at": health.last_success_at,
                "last_failure_at": health.last_failure_at,
                "last_checked_at": health.last_checked_at,
                "tokens_in": health.tokens_in,
                "tokens_out": health.tokens_out,
                "last_error_type": health.last_error_type,
                "last_error_message": health.last_error_message,
            }
            if cooldown_until > now:
                row["available"] = False
            if health.quota_remaining is not None and health.quota_remaining <= 0:
                row["available"] = False
            if health.requests_remaining is not None and health.requests_remaining <= 0:
                row["available"] = False
            if health.tokens_remaining is not None and health.tokens_remaining <= 0:
                row["available"] = False
            if include_history:
                row["failover_events"] = list(health.failover_events)
            snapshot[name] = row
        return snapshot

    def capability_graph(self) -> dict[str, Any]:
        """Expose provider/model capabilities for transparent routing decisions."""

        health = self.health_snapshot(include_history=False)
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for route in self.config.routes:
            for index, agent_name in enumerate(route.agents):
                agent = self.config.agents.get(agent_name)
                if not agent:
                    continue
                edges.append(
                    {
                        "route": route.name,
                        "agent": agent.name,
                        "order": index,
                        "available": bool(health.get(agent.name, {}).get("available")),
                    }
                )
        for agent in self.config.agents.values():
            row = health.get(agent.name, {})
            nodes.append(
                {
                    "agent": agent.name,
                    "provider": agent.provider,
                    "provider_type": agent.provider_type or normalize_provider(agent.provider),
                    "model": agent.model,
                    "enabled": agent.enabled,
                    "available": bool(row.get("available")),
                    "capabilities": {
                        "tools": bool(agent.supports_tools or agent.supports_function_calling),
                        "json": bool(agent.supports_json),
                        "streaming": bool(agent.supports_streaming),
                        "vision": bool(agent.supports_vision),
                        "context_window": agent.context_window,
                    },
                    "benchmark_memory": {
                        "reliability_score": row.get("reliability_score"),
                        "average_latency_ms": row.get("average_latency_ms"),
                        "streaming_tokens_per_second": row.get("streaming_tokens_per_second"),
                        "success_count": row.get("success_count"),
                        "failure_count": row.get("failure_count"),
                    },
                }
            )
        return {"object": "agent_hub.capability_graph", "nodes": nodes, "edges": edges}

    def recommend(
        self,
        request: HubRequest,
        *,
        limit: int = 5,
        needs_tools: bool | None = None,
        prefer: str | None = None,
        require_free: bool | None = None,
        include_unavailable: bool = False,
    ) -> list[dict[str, Any]]:
        """Return ranked model/agent proposals for a task without making a provider call."""

        text = request_text(request)
        route_names = self._route_names(request)
        candidates = [
            self.config.agents[name]
            for name in route_names
            if name in self.config.agents
        ]
        if not self.config.debug_echo_enabled:
            candidates = [agent for agent in candidates if not _is_echo_agent(agent)]
        if request.preferred_agent and request.preferred_agent in self.config.agents:
            preferred = self.config.agents[request.preferred_agent]
            if self.config.debug_echo_enabled or not _is_echo_agent(preferred):
                candidates = [preferred, *[agent for agent in candidates if agent.name != preferred.name]]

        rows: list[dict[str, Any]] = []
        for index, agent in enumerate(candidates):
            free = is_free_agent(agent)
            health = self._health.get(agent.name)
            unavailable_reason = ""
            if not agent.enabled:
                unavailable_reason = "disabled"
            elif require_free is True and not free:
                unavailable_reason = "not free"
            elif self.config.free_only and not free:
                unavailable_reason = "skipped by free_only"
            elif self._is_on_cooldown(agent.name):
                unavailable_reason = "temporarily unavailable"
            else:
                unavailable_reason = self._preflight_skip_reason(agent, request) or ""

            available = not unavailable_reason
            if unavailable_reason and not include_unavailable:
                continue
            score = self._recommendation_score(
                agent,
                text=text,
                needs_tools=needs_tools,
                prefer=prefer,
            )
            if not available:
                score -= 1000
            rows.append(
                {
                    "rank": 0,
                    "agent": agent.name,
                    "provider": agent.provider,
                    "provider_type": agent.provider_type or normalize_provider(agent.provider),
                    "model": agent.model,
                    "score": round(score, 3),
                    "free": free,
                    "enabled": agent.enabled,
                    "available": available,
                    "unavailable_reason": unavailable_reason,
                    "context_window": agent.context_window,
                    "coding_score": agent.coding_score,
                    "reasoning_score": agent.reasoning_score,
                    "speed_score": agent.speed_score,
                    "supports_tools": bool(agent.supports_tools or agent.supports_function_calling),
                    "reliability_score": round(health.reliability_score, 4) if health else 0.7,
                    "average_latency_ms": round(health.average_latency_ms, 2) if health else 0.0,
                    "degraded": health.is_degraded() if health else False,
                    "cooldown_until": self._cooldown_until(agent.name),
                    "quota_remaining": health.quota_remaining if health else None,
                    "requests_remaining": health.requests_remaining if health else None,
                    "tokens_remaining": health.tokens_remaining if health else None,
                    "credits_remaining": health.credits_remaining if health else None,
                    "rate_limit_reset_at": health.rate_limit_reset_at if health else None,
                    "why": _recommendation_reason(agent, text=text, prefer=prefer, index=index),
                }
            )
        rows = sorted(rows, key=lambda row: (-float(row["score"]), route_names.index(row["agent"]) if row["agent"] in route_names else 999))
        for rank, row in enumerate(rows[: max(1, limit)], start=1):
            row["rank"] = rank
        return rows[: max(1, limit)]

    def _preflight_skip_reason(self, agent: AgentConfig, request: HubRequest) -> str | None:
        if _requires_tool_capable_model(request) and not _agent_supports_tools(agent):
            if _is_echo_agent(agent):
                return (
                    "Echo is a diagnostic provider and cannot satisfy Cline, Claude Code, "
                    "or OpenAI-compatible tool calls."
                )
            return (
                "This request includes tools, but the configured agent does not advertise "
                "tool/function-call support."
            )

        if _is_echo_agent(agent) and not self.config.debug_echo_enabled:
            return (
                "Echo is disabled by default because it only repeats the task and is not a real model. "
                "Configure a real provider or set debug_echo_enabled=true for diagnostics."
            )

        if self.config.free_only and not is_free_agent(agent):
            return (
                "Agent provider is disabled because free_only is enabled; "
                "only agents marked free, echo, and local/private openai-compatible agents are allowed"
            )

        if _requires_missing_api_key(agent):
            return f"Agent is missing API key env {agent.api_key_env}"

        input_tokens = estimate_input_tokens(request)
        output_tokens = expected_output_tokens(request, agent)
        required_tokens = input_tokens + output_tokens
        health = self._health.get(agent.name)
        quota_reason = _quota_skip_reason(health, required_tokens=required_tokens)
        if quota_reason:
            return quota_reason

        if agent.context_window is None:
            return None

        if required_tokens > agent.context_window:
            return (
                "Agent context window is too small: "
                f"needs about {required_tokens} tokens "
                f"({input_tokens} input + {output_tokens} output), "
                f"has {agent.context_window}"
            )
        return None

    def _preflight_error_type(
        self,
        agent: AgentConfig,
        request: HubRequest,
        reason: str,
    ) -> str | None:
        if _requires_tool_capable_model(request):
            if (
                not _agent_supports_tools(agent)
                or _requires_missing_api_key(agent)
                or "free_only" in reason
            ):
                return NO_TOOL_CAPABLE_MODEL
        if _is_echo_agent(agent) and not self.config.debug_echo_enabled:
            return ECHO_DISABLED
        if "missing API key" in reason:
            return CONFIGURATION_ERROR
        return None

    def _balanced_agents(self, agents: list[AgentConfig], request: HubRequest | None = None) -> list[AgentConfig]:
        if not self.config.enable_load_balancing or len(agents) <= 1:
            return agents
        return [
            agent
            for _, agent in sorted(
                enumerate(agents),
                key=lambda item: (-self._routing_score(item[1], request), item[0]),
            )
        ]

    def _routing_score(self, agent: AgentConfig, request: HubRequest | None = None) -> float:
        score = float(agent.priority or 0.0)
        has_tools = _request_has_tools(request) if request is not None else False
        if normalize_provider(agent.provider) == "echo":
            score -= 5000.0
        if request is not None:
            text = request_text(request).lower()
            if has_tools and (agent.supports_tools or agent.supports_function_calling):
                score += 18
            if _looks_like_coding_task(text):
                score += float(agent.coding_score or 0.0) * 12
            if _looks_like_reasoning_task(text):
                score += float(agent.reasoning_score or 0.0) * 8
            score += float(agent.speed_score or 0.0) * 3
        health = self._health.get(agent.name)
        if health:
            score += health.reliability_score * 12
            score += min(3.0, health.success_count * 0.25)
            score -= min(6.0, health.failure_count * 0.75)
            score -= min(8.0, health.timeout_count * 1.5)
            if health.average_latency_seconds:
                score -= min(5.0, health.average_latency_seconds / 5)
            if health.is_degraded():
                score -= 20.0
            if health.requests_remaining is not None and health.requests_remaining <= 1:
                score -= 25.0
            if health.quota_remaining is not None and health.quota_remaining <= 0:
                score -= 100.0
            if request is not None:
                required_tokens = estimate_input_tokens(request) + expected_output_tokens(request, agent)
                if health.tokens_remaining is not None and health.tokens_remaining < required_tokens:
                    score -= 80.0
                elif health.tokens_remaining is not None and health.tokens_remaining < required_tokens * 2:
                    score -= 18.0
            if has_tools and health.tool_call_failure_count:
                score -= min(12.0, health.tool_call_failure_count * 2.0)
            if request is not None and request.stream and agent.supports_streaming and health.streaming_tokens_per_second:
                score += min(4.0, health.streaming_tokens_per_second / 25.0)
            if health.tokens_in > 0:
                token_efficiency = health.tokens_out / max(1, health.tokens_in)
                score += min(3.0, token_efficiency)
        if self._is_on_cooldown(agent.name):
            score -= 100.0
        if not self.config.free_only and not is_free_agent(agent):
            score -= 2.5
        return score

    def _record_route_event(self, event_type: str, *, request_id: str, request: HubRequest, **data: Any) -> None:
        try:
            record_event(
                self.config.state_dir,
                "routing",
                {
                    "type": event_type,
                    "request_id": request_id,
                    "session_id": request.session_id,
                    "route": request.route,
                    "preferred_agent": request.preferred_agent,
                    "api_shape": request.api_shape,
                    **data,
                },
            )
        except Exception:
            return

    def _record_success(
        self,
        agent: AgentConfig,
        latency_seconds: float,
        result: ProviderResult,
        request: HubRequest,
    ) -> None:
        health = self._health.setdefault(agent.name, ProviderHealth())
        now = time.time()
        health.success_count += 1
        health.total_latency_seconds += max(0.0, latency_seconds)
        health.last_success_at = now
        health.last_checked_at = now
        tokens_in = _usage_int(result.usage, "prompt_tokens", "input_tokens")
        tokens_out = _usage_int(result.usage, "completion_tokens", "output_tokens")
        health.tokens_in += tokens_in
        health.tokens_out += tokens_out
        if request.stream and latency_seconds > 0 and tokens_out > 0:
            health.total_streaming_tokens_per_second += tokens_out / latency_seconds
            health.streaming_sample_count += 1
        _apply_provider_metadata(
            health,
            _provider_metadata_from_raw(result.raw),
            agent=agent,
        )
        self._save_provider_health()

    def _record_failure(
        self,
        agent: AgentConfig,
        *,
        error_type: str = "",
        message: str = "",
        unavailable_until: float | None = None,
        status_code: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        health = self._health.setdefault(agent.name, ProviderHealth())
        now = time.time()
        health.failure_count += 1
        health.last_failure_at = now
        health.last_checked_at = now
        if error_type == "timeout" or "timed out" in message.lower() or "timeout" in message.lower():
            health.timeout_count += 1
        if unavailable_until is not None:
            health.unavailable_until = max(health.unavailable_until, unavailable_until)
            health.cooldown_until = max(health.cooldown_until, unavailable_until)
        if error_type:
            health.last_error_type = error_type
        if message:
            health.last_error_message = message[:500]
        _apply_provider_metadata(health, metadata or {}, agent=agent)
        health.failover_events.append(
            {
                "time": now,
                "agent": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "reason": message[:500],
                "status_code": status_code,
                "error_type": error_type,
                "unavailable_until": unavailable_until,
            }
        )
        health.failover_events = health.failover_events[-MAX_FAILOVER_HISTORY:]
        self._save_provider_health()

    def record_tool_result(self, agent_name: str, ok: bool) -> None:
        """Record whether an agent-produced tool call completed successfully."""

        health = self._health.setdefault(agent_name, ProviderHealth())
        if ok:
            health.tool_call_success_count += 1
        else:
            health.tool_call_failure_count += 1
        health.last_checked_at = time.time()
        self._save_provider_health()

    def _load_provider_health(self) -> dict[str, ProviderHealth]:
        path = self._health_path
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        agents = raw.get("agents") if isinstance(raw, dict) else None
        if not isinstance(agents, dict):
            return {}
        valid_fields = {item.name for item in fields(ProviderHealth)}
        now = time.time()
        health_by_agent: dict[str, ProviderHealth] = {}
        for name, data in agents.items():
            if not isinstance(name, str) or not isinstance(data, dict):
                continue
            values = {key: data[key] for key in valid_fields if key in data}
            try:
                health = ProviderHealth(**values)
            except TypeError:
                continue
            if not isinstance(health.failover_events, list):
                health.failover_events = []
            last_seen = max(health.last_checked_at, health.last_success_at, health.last_failure_at)
            if last_seen and last_seen < now - HEALTH_STALE_SECONDS and health.cooldown_deadline() <= now:
                continue
            health_by_agent[name] = health
        return health_by_agent

    def _save_provider_health(self) -> None:
        data = {
            "version": HEALTH_STATE_VERSION,
            "updated_at": time.time(),
            "agents": {
                name: _provider_health_to_state(health)
                for name, health in sorted(self._health.items())
            },
        }
        try:
            self._health_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = _temporary_health_path(self._health_path)
            tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(self._health_path)
        except OSError:
            return

    def _cooldown_seconds(self, agent: AgentConfig, error: ProviderError) -> float:
        if error.cooldown_seconds is not None:
            return max(0.0, error.cooldown_seconds)
        if error.error_type == "quota_exhausted":
            return max(agent.cooldown_seconds, float(self.config.quota_cooldown_seconds))
        if error.error_type == "rate_limited":
            return max(agent.cooldown_seconds, float(self.config.rate_limit_cooldown_seconds))
        return max(0.0, agent.cooldown_seconds)

    def _recommendation_score(
        self,
        agent: AgentConfig,
        *,
        text: str,
        needs_tools: bool | None,
        prefer: str | None,
    ) -> float:
        lowered = text.lower()
        coding_need = _looks_like_coding_task(lowered)
        reasoning_need = _looks_like_reasoning_task(lowered)
        speed_need = prefer == "speed" or any(word in lowered for word in ("quick", "fast", "brief"))
        tool_need = bool(needs_tools) or any(
            word in lowered for word in ("edit", "file", "repo", "workspace", "test", "command")
        )

        score = float(agent.priority or 0.0)
        if normalize_provider(agent.provider) == "echo":
            score -= 50.0
        score += float(agent.coding_score or 0.0) * (32 if coding_need or prefer == "coding" else 8)
        score += float(agent.reasoning_score or 0.0) * (
            32 if reasoning_need or prefer == "reasoning" else 10
        )
        score += float(agent.speed_score or 0.0) * (28 if speed_need else 8)
        score += min(12.0, float(agent.context_window or 0) / 16_000)
        if tool_need and (agent.supports_tools or agent.supports_function_calling):
            score += 10
        if is_free_agent(agent):
            score += 4
        health = self._health.get(agent.name)
        if health:
            score += health.reliability_score * 10
            score -= min(8.0, health.failure_count * 0.8)
            score -= min(6.0, health.timeout_count * 1.5)
            if health.average_latency_seconds:
                score -= min(5.0, health.average_latency_seconds / 4)
            if health.is_degraded():
                score -= 18
            if health.requests_remaining is not None and health.requests_remaining <= 1:
                score -= 20
            if health.quota_remaining is not None and health.quota_remaining <= 0:
                score -= 100
            if tool_need and health.tool_call_failure_count:
                score -= min(10.0, health.tool_call_failure_count * 2.0)
            if agent.supports_streaming and health.streaming_tokens_per_second:
                score += min(4.0, health.streaming_tokens_per_second / 25.0)
        return score


def _provider_health_to_state(health: ProviderHealth) -> dict[str, Any]:
    return {
        item.name: getattr(health, item.name)
        for item in fields(ProviderHealth)
    }


def _request_option(request: HubRequest, *keys: str) -> Any:
    sources = []
    raw = request.raw if isinstance(request.raw, dict) else {}
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    hub_options = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    sources.extend([raw, hub_options, metadata])
    for source in sources:
        for key in keys:
            if key in source and source[key] not in (None, ""):
                return source[key]
    return None


def _privacy_requested(request: HubRequest) -> bool:
    value = _request_option(
        request,
        "local_private",
        "private",
        "privacy",
        "privacy_mode",
        "local_only",
    )
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "local", "private", "local_private"}
    return False


def _negated_sort_tuple(values: tuple[Any, ...]) -> tuple[float, ...]:
    negated: list[float] = []
    for value in values:
        try:
            negated.append(-float(value))
        except (TypeError, ValueError):
            negated.append(0.0)
    return tuple(negated)


def _agent_limit_metadata(agent: AgentConfig, health: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": agent.provider,
        "provider_name": agent.provider,
        "provider_type": agent.provider_type or normalize_provider(agent.provider),
        "model": agent.model,
        "requests_remaining": health.get("requests_remaining"),
        "tokens_remaining": health.get("tokens_remaining"),
        "credits_remaining": health.get("credits_remaining"),
        "quota_remaining": health.get("quota_remaining"),
        "rate_limit_reset_at": health.get("rate_limit_reset_at"),
        "cooldown_until": health.get("cooldown_until"),
        "unavailable_until": health.get("unavailable_until"),
    }


def _temporary_health_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.tmp")


def _provider_metadata_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    provider_metadata = raw.get("agent_hub_provider")
    if not isinstance(provider_metadata, dict):
        return {}
    quota = provider_metadata.get("quota")
    return dict(quota) if isinstance(quota, dict) else {}


def _apply_provider_metadata(
    health: ProviderHealth,
    metadata: dict[str, Any],
    *,
    agent: AgentConfig,
) -> None:
    if not metadata:
        return
    _assign_float(health, "quota_remaining", metadata.get("quota_remaining"))
    _assign_int(health, "requests_remaining", metadata.get("requests_remaining"))
    _assign_int(health, "tokens_remaining", metadata.get("tokens_remaining"))
    _assign_float(health, "credits_remaining", metadata.get("credits_remaining"))
    _assign_float(health, "rate_limit_reset_at", metadata.get("rate_limit_reset_at"))
    cooldown_until = _optional_timestamp(metadata.get("cooldown_until"))
    if cooldown_until is None:
        cooldown_seconds = _optional_float(metadata.get("cooldown_seconds"))
        if cooldown_seconds is not None:
            cooldown_until = time.time() + max(0.0, cooldown_seconds)
    if cooldown_until is None:
        reset_at = _optional_timestamp(metadata.get("rate_limit_reset_at"))
        if reset_at is not None and (
            health.requests_remaining == 0
            or health.quota_remaining == 0
        ):
            cooldown_until = reset_at
    if cooldown_until is not None:
        health.cooldown_until = max(health.cooldown_until, cooldown_until)
        health.unavailable_until = max(health.unavailable_until, cooldown_until)
    if health.requests_remaining == 0 and health.cooldown_until <= time.time():
        health.cooldown_until = max(
            health.cooldown_until,
            time.time() + max(0.0, agent.cooldown_seconds),
        )


def _quota_skip_reason(health: ProviderHealth | None, *, required_tokens: int) -> str | None:
    if health is None:
        return None
    now = time.time()
    if health.rate_limit_reset_at is not None and health.rate_limit_reset_at <= now:
        return None
    if health.requests_remaining is not None and health.requests_remaining <= 0:
        return _availability_reason("Provider has no remaining requests from last observed quota metadata", health)
    if health.quota_remaining is not None and health.quota_remaining <= 0:
        return _availability_reason("Provider appears to be out of free-tier quota or credits", health)
    if health.credits_remaining is not None and health.credits_remaining <= 0:
        return _availability_reason("Provider appears to be out of free-tier credits", health)
    if health.tokens_remaining is not None and health.tokens_remaining < required_tokens:
        return (
            "Provider has too few observed remaining tokens: "
            f"needs about {required_tokens}, has {health.tokens_remaining}"
        )
    return None


def _availability_reason(prefix: str, health: ProviderHealth) -> str:
    deadline = max(health.cooldown_deadline(), health.rate_limit_reset_at or 0.0)
    if deadline > time.time():
        return f"{prefix}; retry after {int(deadline - time.time())}s"
    return prefix


def _assign_int(health: ProviderHealth, field_name: str, value: Any) -> None:
    parsed = _optional_int(value)
    if parsed is not None:
        setattr(health, field_name, parsed)


def _assign_float(health: ProviderHealth, field_name: str, value: Any) -> None:
    parsed = _optional_float(value)
    if parsed is not None:
        setattr(health, field_name, parsed)


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_timestamp(value: Any) -> float | None:
    parsed = _optional_float(value)
    if parsed is None:
        return None
    return parsed


def _is_prefix(prefix: list[dict], messages: list[dict]) -> bool:
    if len(prefix) > len(messages):
        return False
    return all(
        left.get("role") == right.get("role") and left.get("content") == right.get("content")
        for left, right in zip(prefix, messages, strict=False)
    )


def estimate_input_tokens(request: HubRequest) -> int:
    return estimate_messages_tokens(request.messages)


def expected_output_tokens(request: HubRequest, agent: AgentConfig) -> int:
    if request.max_tokens is not None:
        return _non_negative_int(request.max_tokens, default=4096)
    if agent.max_tokens is not None:
        return _non_negative_int(agent.max_tokens, default=4096)
    return 4096


def _non_negative_int(value: object, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _public_model_name(request: HubRequest) -> str:
    raw_model = request.raw.get("model") if isinstance(request.raw, dict) else None
    if isinstance(raw_model, str) and raw_model.strip():
        return raw_model.strip()
    if request.route:
        return request.route
    return "agent-hub-local"


def _token_limit_finish_reason(reason: str | None) -> bool:
    if not reason:
        return False
    normalized = reason.lower()
    return normalized in {"length", "max_tokens", "max_output_tokens", "token_limit"}


def _usage_int(usage: dict[str, object], *keys: str) -> int:
    for key in keys:
        try:
            return max(0, int(usage.get(key, 0)))
        except (TypeError, ValueError):
            continue
    return 0


def _requires_missing_api_key(agent: AgentConfig) -> bool:
    if not agent.api_key_env or agent.resolved_api_key:
        return False
    provider = normalize_provider(agent.provider)
    if provider in {"openai", "anthropic", "gemini"}:
        return True
    if provider == "openai-compatible" and agent.base_url:
        return not _is_local_or_private_agent(agent)
    return False


def _is_local_or_private_agent(agent: AgentConfig) -> bool:
    from ..config import _is_local_or_private_url

    provider = normalize_provider(agent.provider)
    provider_type = (agent.provider_type or agent.provider).lower()
    if provider in {"echo", "local-research"}:
        return True
    if provider_type == "ollama-cloud":
        return False
    return _is_local_or_private_url(agent.base_url)


def _is_echo_agent(agent: AgentConfig) -> bool:
    return normalize_provider(agent.provider) == "echo"


def _agent_supports_tools(agent: AgentConfig) -> bool:
    return bool(agent.supports_tools or agent.supports_function_calling)


def _requires_tool_capable_model(request: HubRequest) -> bool:
    return request.api_shape in TRANSPARENT_API_SHAPES and _request_has_tools(request)


def _no_fallback_reason(failover: list[FailoverEvent]) -> str:
    if not failover:
        return _no_model_available_message()
    no_tool_events = [
        event
        for event in failover
        if event.error_type == NO_TOOL_CAPABLE_MODEL
    ]
    if no_tool_events and len(no_tool_events) == len(failover):
        return _no_tool_capable_message(no_tool_events)
    permission_events = [
        event
        for event in failover
        if event.error_type in {"permission_required", "permission_denied"}
    ]
    if permission_events and len(permission_events) == len(failover):
        latest = permission_events[-1]
        if latest.error_type == "permission_denied":
            return f"Permission denied before using {latest.agent}: {latest.reason}"
        return (
            "Approval required before Agent Hub can use an external provider "
            f"or send workspace content. Provider: {latest.agent}. {latest.reason}"
        )
    echo_events = [
        event
        for event in failover
        if event.error_type == ECHO_DISABLED
    ]
    if echo_events and len(echo_events) == len(failover):
        return (
            "Echo is disabled by default and no real provider is available for this route. "
            "Configure an OpenAI-compatible, Anthropic, Gemini, or local provider, or set "
            "debug_echo_enabled=true only for diagnostics."
        )
    quota_events = [
        event
        for event in failover
        if event.error_type in {"quota_exhausted", "rate_limited"}
    ]
    if quota_events and len(quota_events) == len([event for event in failover if event.retryable]):
        latest = quota_events[-1]
        return (
            "No fallback model is currently available; providers are rate-limited "
            f"or out of free-tier quota. Last failure from {latest.agent}: {latest.reason}"
        )
    real_failures = [event for event in failover if event.error_type != ECHO_DISABLED]
    if echo_events and real_failures:
        latest = real_failures[-1]
        return (
            "No real fallback model is available; echo is disabled by default. "
            f"Last real provider failure from {latest.agent}: {latest.reason}"
        )
    return failover[-1].reason


def _route_error_type(failover: list[FailoverEvent]) -> str | None:
    if not failover:
        return None
    no_tool_events = [event for event in failover if event.error_type == NO_TOOL_CAPABLE_MODEL]
    if no_tool_events and len(no_tool_events) == len(failover):
        return NO_TOOL_CAPABLE_MODEL
    echo_events = [event for event in failover if event.error_type == ECHO_DISABLED]
    if echo_events and len(echo_events) == len(failover):
        return CONFIGURATION_ERROR
    permission_events = [
        event
        for event in failover
        if event.error_type in {"permission_required", "permission_denied"}
    ]
    if permission_events and len(permission_events) == len(failover):
        return permission_events[-1].error_type
    return None


def _route_status_code(error_type: str | None) -> int | None:
    if error_type in {NO_TOOL_CAPABLE_MODEL, CONFIGURATION_ERROR}:
        return 400
    return None


def _suggested_fix(error_type: str | None, failover: list[FailoverEvent]) -> str | None:
    if error_type == NO_TOOL_CAPABLE_MODEL:
        return _no_tool_capable_fix(failover)
    if error_type == CONFIGURATION_ERROR:
        return _no_model_available_fix()
    missing_keys = _missing_key_names(failover)
    if missing_keys:
        return (
            f"Set {', '.join(missing_keys)} or disable that provider. "
            "For Cline, use model agent-hub-coding against the Agent Hub OpenAI endpoint."
        )
    return None


def _no_model_available_message() -> str:
    return (
        "No usable model is available for this request. Enable a provider in Agent Hub "
        "settings, add an API key, or start a local Ollama/LM Studio model. For Cline, "
        "use model agent-hub-coding."
    )


def _no_model_available_fix() -> str:
    return (
        "Open the Agent Hub sidebar, add an API key or start Ollama/LM Studio, then click "
        "Start Server. Cline base URL: http://127.0.0.1:8787/v1, model: agent-hub-coding. "
        "Claude Code endpoint: http://127.0.0.1:8787/v1/messages."
    )


def _no_tool_capable_message(events: list[FailoverEvent]) -> str:
    checked = _checked_model_summary(events)
    fix = _no_tool_capable_fix(events)
    if checked:
        return (
            "No tool-capable model is available for this Cline/OpenAI-compatible request. "
            f"Checked: {checked}. Suggested fix: {fix}"
        )
    return (
        "No tool-capable model is available for this Cline/OpenAI-compatible request. "
        f"Suggested fix: {fix}"
    )


def _no_tool_capable_fix(events: list[FailoverEvent]) -> str:
    missing_keys = _missing_key_names(events)
    if missing_keys:
        keys = ", ".join(missing_keys)
        return (
            f"Set {keys}, enable that provider, or configure a local OpenAI-compatible "
            "coding model with supports_tools=true on the selected route."
        )
    return (
        "Configure an enabled non-echo provider on the selected route with "
        "supports_tools=true or supports_function_calling=true, such as OpenAI, "
        "Anthropic, Gemini, or a local OpenAI-compatible server that supports tools."
    )


def _checked_model_summary(events: list[FailoverEvent]) -> str:
    parts: list[str] = []
    for event in events[:6]:
        parts.append(f"{event.agent} ({event.provider}/{event.model}: {event.reason})")
    if len(events) > 6:
        parts.append(f"{len(events) - 6} more")
    return "; ".join(parts)


def _missing_key_names(events: list[FailoverEvent]) -> list[str]:
    names: list[str] = []
    marker = "missing API key env "
    for event in events:
        if marker not in event.reason:
            continue
        key = event.reason.split(marker, 1)[1].strip().split()[0].strip(".,;:")
        if key and key not in names:
            names.append(key)
    return names


def _looks_like_coding_task(text: str) -> bool:
    return any(
        word in text
        for word in (
            "bug",
            "code",
            "debug",
            "edit",
            "error",
            "fix",
            "implement",
            "refactor",
            "repo",
            "test",
            "workspace",
        )
    )


def _looks_like_reasoning_task(text: str) -> bool:
    return any(
        word in text
        for word in (
            "analyze",
            "compare",
            "explain",
            "plan",
            "prove",
            "reason",
            "review",
            "tradeoff",
            "why",
        )
    )


def _request_has_tools(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    if isinstance(raw.get("tools"), list) and raw["tools"]:
        return True
    if isinstance(raw.get("functions"), list) and raw["functions"]:
        return True
    if isinstance(raw.get("agent_hub_tools"), list) and raw["agent_hub_tools"]:
        return True
    if isinstance(raw.get("tool_choice"), (str, dict)):
        return True
    if isinstance(raw.get("function_call"), (str, dict)):
        return True
    hub_options = raw.get("agent_hub")
    return isinstance(hub_options, dict) and bool(hub_options.get("agent_mode"))


def _recommendation_reason(
    agent: AgentConfig,
    *,
    text: str,
    prefer: str | None,
    index: int,
) -> str:
    reasons: list[str] = []
    lowered = text.lower()
    if _looks_like_coding_task(lowered) and agent.coding_score is not None:
        reasons.append(f"coding {agent.coding_score:g}")
    if (_looks_like_reasoning_task(lowered) or prefer == "reasoning") and agent.reasoning_score is not None:
        reasons.append(f"reasoning {agent.reasoning_score:g}")
    if prefer == "speed" and agent.speed_score is not None:
        reasons.append(f"speed {agent.speed_score:g}")
    if agent.context_window:
        reasons.append(f"{agent.context_window} token context")
    if agent.supports_tools or agent.supports_function_calling:
        reasons.append("tool support")
    if is_free_agent(agent):
        reasons.append("free/local eligible")
    if not reasons:
        reasons.append(f"route position {index + 1}")
    return ", ".join(reasons[:4])
