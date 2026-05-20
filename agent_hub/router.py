from __future__ import annotations

import time
import uuid
from dataclasses import replace
from collections.abc import Callable

from .config import AgentConfig, HubConfig, is_free_agent
from .models import FailoverEvent, HubRequest, HubResponse, ProviderResult
from .payloads import content_to_text, request_text
from .providers import Provider, ProviderError, create_provider
from .session_store import SessionStore


ProviderFactory = Callable[[AgentConfig], Provider]


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
            try:
                result = self.provider_factory(agent).complete(effective_request)
                if _token_limit_finish_reason(result.finish_reason) and agent != candidates[-1]:
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
        return agents

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

    def _preflight_skip_reason(self, agent: AgentConfig, request: HubRequest) -> str | None:
        if self.config.free_only and not is_free_agent(agent):
            return (
                "Agent provider is disabled because free_only is enabled; "
                "only agents marked free, echo, and local/private openai-compatible agents are allowed"
            )

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
