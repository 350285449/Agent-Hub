from __future__ import annotations

import time
import uuid
from dataclasses import replace
from collections.abc import Callable

from .config import AgentConfig, HubConfig
from .models import FailoverEvent, HubRequest, HubResponse, ProviderResult
from .payloads import request_text
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

            tried_any = True
            try:
                result = self.provider_factory(agent).complete(effective_request)
                response = self._response_from_result(
                    request_id=request_id,
                    request=effective_request,
                    agent=agent,
                    result=result,
                    failover=failover,
                )
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
            self._cooldowns.clear()
            return self.route(request)

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
            text=result.text,
            usage=result.usage,
            raw=result.raw,
            finish_reason=result.finish_reason,
            failover=list(failover),
        )

    def _is_on_cooldown(self, agent_name: str) -> bool:
        return self._cooldowns.get(agent_name, 0) > time.time()


def _is_prefix(prefix: list[dict], messages: list[dict]) -> bool:
    if len(prefix) > len(messages):
        return False
    return all(
        left.get("role") == right.get("role") and left.get("content") == right.get("content")
        for left, right in zip(prefix, messages, strict=False)
    )
