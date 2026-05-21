from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, replace
from collections.abc import Callable

from .config import AgentConfig, HubConfig, is_free_agent, normalize_provider
from .models import FailoverEvent, HubRequest, HubResponse, ProviderResult
from .payloads import content_to_text, request_text
from .providers import Provider, ProviderError, create_provider
from .session_store import SessionStore


ProviderFactory = Callable[[AgentConfig], Provider]


@dataclass(slots=True)
class ProviderHealth:
    """Rolling in-memory health data used for provider balancing."""

    success_count: int = 0
    failure_count: int = 0
    total_latency_seconds: float = 0.0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def success_rate(self) -> float:
        attempts = self.success_count + self.failure_count
        return 0.5 if attempts == 0 else self.success_count / attempts

    @property
    def average_latency_seconds(self) -> float:
        return 0.0 if self.success_count == 0 else self.total_latency_seconds / self.success_count


class RouterError(Exception):
    def __init__(self, message: str, failover: list[FailoverEvent] | None = None) -> None:
        super().__init__(message)
        self.failover = failover or []


class AgentRouter:
    def __init__(
        self,
        config: HubConfig,
        provider_factory: ProviderFactory = create_provider,
        session_store: SessionStore | None = None,
    ) -> None:
        self.config = config
        self.provider_factory = provider_factory
        self.session_store = session_store or SessionStore(config.state_dir)
        self._cooldowns: dict[str, float] = {}
        self._health: dict[str, ProviderHealth] = {}

    def route(self, request: HubRequest) -> HubResponse:
        effective_request = self._with_session_history(request)
        request_id = f"hub-{uuid.uuid4().hex}"
        failover: list[FailoverEvent] = []
        candidates = self._candidate_agents(effective_request)
        if not candidates:
            raise RouterError("No enabled agents are configured")

        tried_any = False
        for agent in candidates:
            if self._is_on_cooldown(agent.name) and len(candidates) > 1:
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason="Agent is in temporary cooldown from a previous failure",
                    )
                )
                continue

            skip_reason = self._preflight_skip_reason(agent, effective_request)
            if skip_reason:
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason=skip_reason,
                        retryable=False,
                    )
                )
                continue

            tried_any = True
            started = time.perf_counter()
            try:
                result = self.provider_factory(agent).complete(effective_request)
                latency = time.perf_counter() - started
                if _token_limit_finish_reason(result.finish_reason) and agent != candidates[-1]:
                    self._record_failure(agent)
                    failover.append(
                        FailoverEvent(
                            agent=agent.name,
                            provider=agent.provider,
                            model=agent.model,
                            reason=(
                                "Agent stopped because it hit a token limit; "
                                "retrying with the next configured agent"
                            ),
                        )
                    )
                    continue
                self._record_success(agent, latency, result)
                response = self._response_from_result(
                    request_id=request_id,
                    request=effective_request,
                    agent=agent,
                    result=result,
                    failover=failover,
                )
                if effective_request.record_session:
                    self.session_store.record_turn(effective_request, response)
                return response
            except ProviderError as exc:
                self._record_failure(agent)
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason=str(exc),
                        status_code=exc.status_code,
                        retryable=exc.retryable,
                    )
                )
                if exc.retryable:
                    self._cooldowns[agent.name] = time.time() + agent.cooldown_seconds
                    continue
                raise RouterError(str(exc), failover=failover) from exc

        if not tried_any:
            if failover and all(
                event.reason.startswith("Agent is in temporary cooldown") for event in failover
            ):
                self._cooldowns.clear()
                return self.route(request)
            reason = failover[-1].reason if failover else "No agent produced a response"
            raise RouterError(reason, failover=failover)

        reason = failover[-1].reason if failover else "No agent produced a response"
        raise RouterError(reason, failover=failover)

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

    def _candidate_agents(self, request: HubRequest) -> list[AgentConfig]:
        names: list[str] = []
        if request.preferred_agent:
            names.append(request.preferred_agent)
        names.extend(self._route_names(request))

        seen: set[str] = set()
        agents: list[AgentConfig] = []
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            agent = self.config.agents.get(name)
            if agent and agent.enabled:
                agents.append(agent)
        if request.preferred_agent:
            return agents
        return self._balanced_agents(agents)

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

    def _response_from_result(
        self,
        request_id: str,
        request: HubRequest,
        agent: AgentConfig,
        result: ProviderResult,
        failover: list[FailoverEvent],
    ) -> HubResponse:
        return HubResponse(
            request_id=request_id,
            session_id=request.session_id,
            agent=agent.name,
            provider=agent.provider,
            model=result.model or agent.model,
            public_model=_public_model_name(request),
            text=result.text,
            usage=result.usage,
            raw=result.raw,
            finish_reason=result.finish_reason,
            failover=list(failover),
            citations=result.citations,
            search_results=result.search_results,
            images=result.images,
            related_questions=result.related_questions,
        )

    def _is_on_cooldown(self, agent_name: str) -> bool:
        return self._cooldowns.get(agent_name, 0) > time.time()

    def cooldown_agent(self, agent_name: str, seconds: float | None = None) -> None:
        agent = self.config.agents.get(agent_name)
        duration = seconds if seconds is not None else (agent.cooldown_seconds if agent else 0)
        if duration <= 0:
            return
        self._cooldowns[agent_name] = time.time() + duration

    def health_snapshot(self) -> dict[str, dict[str, float | int]]:
        """Return in-memory provider health for diagnostics and tests."""

        return {
            name: {
                "success_count": health.success_count,
                "failure_count": health.failure_count,
                "success_rate": round(health.success_rate, 4),
                "average_latency_seconds": round(health.average_latency_seconds, 4),
                "last_success_at": health.last_success_at,
                "last_failure_at": health.last_failure_at,
                "tokens_in": health.tokens_in,
                "tokens_out": health.tokens_out,
            }
            for name, health in self._health.items()
        }

    def _preflight_skip_reason(self, agent: AgentConfig, request: HubRequest) -> str | None:
        if self.config.free_only and not is_free_agent(agent):
            return (
                "Agent provider is disabled because free_only is enabled; "
                "only agents marked free, echo, and local/private openai-compatible agents are allowed"
            )

        if _requires_missing_api_key(agent):
            return f"Agent is missing API key env {agent.api_key_env}"

        if agent.context_window is None:
            return None

        input_tokens = estimate_input_tokens(request)
        output_tokens = expected_output_tokens(request, agent)
        required_tokens = input_tokens + output_tokens
        if required_tokens > agent.context_window:
            return (
                "Agent context window is too small: "
                f"needs about {required_tokens} tokens "
                f"({input_tokens} input + {output_tokens} output), "
                f"has {agent.context_window}"
            )
        return None

    def _balanced_agents(self, agents: list[AgentConfig]) -> list[AgentConfig]:
        if not self.config.enable_load_balancing or len(agents) <= 1:
            return agents
        return [
            agent
            for _, agent in sorted(
                enumerate(agents),
                key=lambda item: (-self._routing_score(item[1]), item[0]),
            )
        ]

    def _routing_score(self, agent: AgentConfig) -> float:
        score = float(agent.priority or 0.0)
        health = self._health.get(agent.name)
        if health:
            score += health.success_rate * 10
            score += min(3.0, health.success_count * 0.25)
            score -= min(6.0, health.failure_count * 0.75)
            if health.average_latency_seconds:
                score -= min(5.0, health.average_latency_seconds / 5)
        if self._is_on_cooldown(agent.name):
            score -= 100.0
        return score

    def _record_success(
        self,
        agent: AgentConfig,
        latency_seconds: float,
        result: ProviderResult,
    ) -> None:
        health = self._health.setdefault(agent.name, ProviderHealth())
        health.success_count += 1
        health.total_latency_seconds += max(0.0, latency_seconds)
        health.last_success_at = time.time()
        health.tokens_in += _usage_int(result.usage, "prompt_tokens", "input_tokens")
        health.tokens_out += _usage_int(result.usage, "completion_tokens", "output_tokens")

    def _record_failure(self, agent: AgentConfig) -> None:
        health = self._health.setdefault(agent.name, ProviderHealth())
        health.failure_count += 1
        health.last_failure_at = time.time()


def _is_prefix(prefix: list[dict], messages: list[dict]) -> bool:
    if len(prefix) > len(messages):
        return False
    return all(
        left.get("role") == right.get("role") and left.get("content") == right.get("content")
        for left, right in zip(prefix, messages, strict=False)
    )


def estimate_input_tokens(request: HubRequest) -> int:
    total = 0
    for message in request.messages:
        role = str(message.get("role", "user"))
        content = content_to_text(message.get("content"))
        total += max(1, (len(role) + len(content) + 3) // 4) + 4
    return max(1, total)


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
    from .config import _is_local_or_private_url

    return _is_local_or_private_url(agent.base_url)
