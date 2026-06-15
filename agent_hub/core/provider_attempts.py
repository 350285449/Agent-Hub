from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..config import AgentConfig, HubConfig
from ..events import PROVIDER_SELECTED, ROUTER_FALLBACK
from ..models import FailoverEvent, HubRequest, HubResponse, ProviderResult
from ..providers import ProviderError
from ..response_normalization import safe_empty_provider_result


@dataclass(frozen=True, slots=True)
class ProviderAttemptHelpers:
    """Pure helper callbacks shared with the router facade."""

    routing_bool: Callable[[HubConfig, str, bool], bool]
    routing_float: Callable[[HubConfig, str, float], float]
    routing_int: Callable[[HubConfig, str, int], int]
    continuation_request: Callable[[HubRequest, str, str], HubRequest]
    merge_continuation_result: Callable[..., ProviderResult]
    token_limit_finish_reason: Callable[[str | None], bool]
    next_candidate_name: Callable[[list[AgentConfig], AgentConfig], str | None]
    no_fallback_reason: Callable[[list[FailoverEvent]], str]
    route_error_type: Callable[[list[FailoverEvent]], str | None]
    suggested_fix: Callable[[str | None, list[FailoverEvent]], str | None]
    route_status_code: Callable[[str | None], int | None]
    context_usage: Callable[[HubRequest], dict[str, Any]]


class ProviderAttemptExecutor:
    """Execute ranked provider candidates after the router has made a decision."""

    def __init__(
        self,
        router: Any,
        *,
        helpers: ProviderAttemptHelpers,
        router_error_type: type[Exception],
    ) -> None:
        self.router = router
        self.helpers = helpers
        self.router_error_type = router_error_type

    def execute(
        self,
        *,
        request_id: str,
        effective_request: HubRequest,
        decision: Any,
        candidates: list[AgentConfig],
    ) -> HubResponse:
        router = self.router
        helpers = self.helpers
        failover: list[FailoverEvent] = []
        tried_any = False
        provider_attempts = 0
        max_provider_attempts = helpers.routing_int(
            router.config,
            "max_provider_attempts",
            5,
        )
        max_provider_attempts = _request_max_provider_attempts(effective_request, max_provider_attempts)
        continuation_text = ""
        continuation_reason = ""

        for index, agent in enumerate(candidates):
            if provider_attempts >= max_provider_attempts:
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason=f"Max provider attempts reached ({max_provider_attempts})",
                        retryable=True,
                        error_type="max_provider_attempts_reached",
                    )
                )
                break
            if router._should_skip_cooldown_candidate(
                candidates,
                index,
                effective_request,
            ):
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason="Agent is in temporary cooldown from a previous failure",
                        unavailable_until=router._cooldown_until(agent.name),
                    )
                )
                continue

            base_request = (
                helpers.continuation_request(
                    effective_request,
                    continuation_text,
                    continuation_reason,
                )
                if continuation_text
                else effective_request
            )
            provider_request = router._request_for_agent(
                request_id=request_id,
                request=base_request,
                agent=agent,
                decision=decision,
            )
            skip_reason = router._preflight_skip_reason(agent, provider_request)
            if skip_reason:
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason=skip_reason,
                        retryable=False,
                        error_type=router._preflight_error_type(
                            agent,
                            provider_request,
                            skip_reason,
                        ),
                    )
                )
                continue

            permission = router._provider_permission_decision(agent, provider_request)
            if permission is not None and not permission.allowed:
                reason = permission.reason or "Permission required before using this provider."
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason=reason,
                        retryable=False,
                        error_type=(
                            "permission_required"
                            if permission.requires_approval
                            else "permission_denied"
                        ),
                        metadata={
                            "permission": permission.request.to_dict()
                            if permission.request
                            else None,
                            "trust_level": router.provider_permission_policy.trust_level(agent),
                        },
                    )
                )
                router._record_route_event(
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
            provider_attempts += 1
            started = time.perf_counter()
            try:
                result = router._chat_with_validation(
                    request_id=request_id,
                    agent=agent,
                    request=provider_request,
                    decision=decision,
                )
                latency = time.perf_counter() - started
                tool_loop = router._run_tool_loop(
                    request_id=request_id,
                    agent=agent,
                    request=provider_request,
                    initial_result=result,
                )
                result = tool_loop["result"]
                latency += float(tool_loop["latency_seconds"])
                if continuation_text:
                    result = helpers.merge_continuation_result(
                        continuation_text,
                        result,
                        model=result.model or agent.model,
                        raw_reason=continuation_reason,
                    )
                    continuation_text = ""
                    continuation_reason = ""
                if (
                    helpers.token_limit_finish_reason(result.finish_reason)
                    and helpers.routing_bool(
                        router.config,
                        "continue_after_output_limit",
                        True,
                    )
                    and result.text
                ):
                    continued_result, continuation_latency = (
                        router._continue_after_output_limit(
                            request_id=request_id,
                            agent=agent,
                            request=provider_request,
                            decision=decision,
                            result=result,
                        )
                    )
                    latency += continuation_latency
                    if continued_result is not None:
                        result = continued_result
                if helpers.token_limit_finish_reason(result.finish_reason) and agent != candidates[-1]:
                    reason = (
                        "Agent stopped because it hit an output token limit; "
                        "continuing with the next configured agent"
                    )
                    if (
                        helpers.routing_bool(
                            router.config,
                            "continue_after_output_limit",
                            True,
                        )
                        and result.text
                    ):
                        continuation_text = result.text
                        continuation_reason = "fallback_provider_output_limit"
                    unavailable_until = time.time() + agent.cooldown_seconds
                    router._record_failure(
                        agent,
                        error_type="output_too_large",
                        message=reason,
                        unavailable_until=unavailable_until,
                        metadata={},
                        request_id=request_id,
                        request=provider_request,
                        routing_mode=decision.routing_mode,
                        failover_attempts=len(failover),
                    )
                    router._cooldowns[agent.name] = unavailable_until
                    failover.append(
                        FailoverEvent(
                            agent=agent.name,
                            provider=agent.provider,
                            model=agent.model,
                            reason=reason,
                            error_type="output_too_large",
                            unavailable_until=router._cooldowns.get(agent.name),
                        )
                    )
                    router._record_internal_event(
                        ROUTER_FALLBACK,
                        request_id=request_id,
                        request=provider_request,
                        from_agent=agent.name,
                        from_provider=agent.provider,
                        from_model=agent.model,
                        reason=reason,
                        error_type="output_too_large",
                        next_agent=helpers.next_candidate_name(candidates, agent),
                        routing_mode=decision.routing_mode,
                    )
                    continue

                performance_reason = router._performance_failover_reason(
                    agent=agent,
                    request=provider_request,
                    result=result,
                    latency_seconds=latency,
                )
                if (
                    performance_reason
                    and agent != candidates[-1]
                    and helpers.routing_bool(router.config, "auto_failover", True)
                ):
                    unavailable_until = time.time() + helpers.routing_float(
                        router.config,
                        "cooldown_overload_seconds",
                        60.0,
                    )
                    router._record_failure(
                        agent,
                        error_type="provider_overloaded",
                        message=performance_reason,
                        unavailable_until=unavailable_until,
                        metadata={},
                        request_id=request_id,
                        request=provider_request,
                        routing_mode=decision.routing_mode,
                        failover_attempts=len(failover),
                    )
                    router._cooldowns[agent.name] = unavailable_until
                    failover.append(
                        FailoverEvent(
                            agent=agent.name,
                            provider=agent.provider,
                            model=agent.model,
                            reason=performance_reason,
                            error_type="provider_overloaded",
                            unavailable_until=unavailable_until,
                        )
                    )
                    router._record_internal_event(
                        ROUTER_FALLBACK,
                        request_id=request_id,
                        request=provider_request,
                        from_agent=agent.name,
                        from_provider=agent.provider,
                        from_model=agent.model,
                        reason=performance_reason,
                        error_type="provider_overloaded",
                        next_agent=helpers.next_candidate_name(candidates, agent),
                        routing_mode=decision.routing_mode,
                    )
                    continue

                confidence = router._confidence_score(
                    request=provider_request,
                    agent=agent,
                    result=result,
                    failover=failover,
                    latency_seconds=latency,
                )
                if confidence.get("should_escalate") and agent != candidates[-1]:
                    reason = (
                        "Provider response confidence was low "
                        f"({confidence.get('score')}); escalating to the next candidate."
                    )
                    router._record_failure(
                        agent,
                        error_type="low_confidence_response",
                        message=reason,
                        unavailable_until=None,
                        metadata={"confidence": confidence},
                        request_id=request_id,
                        request=provider_request,
                        routing_mode=decision.routing_mode,
                        failover_attempts=len(failover),
                    )
                    failover.append(
                        FailoverEvent(
                            agent=agent.name,
                            provider=agent.provider,
                            model=agent.model,
                            reason=reason,
                            retryable=True,
                            error_type="low_confidence_response",
                            metadata={"confidence": confidence},
                        )
                    )
                    router._record_internal_event(
                        ROUTER_FALLBACK,
                        request_id=request_id,
                        request=provider_request,
                        from_agent=agent.name,
                        from_provider=agent.provider,
                        from_model=agent.model,
                        reason=reason,
                        error_type="low_confidence_response",
                        next_agent=helpers.next_candidate_name(candidates, agent),
                        routing_mode=decision.routing_mode,
                    )
                    retry_planner = getattr(router, "_request_with_retry_plan", None)
                    if callable(retry_planner):
                        effective_request = retry_planner(
                            request=effective_request,
                            decision=decision,
                            retry_reason="low confidence response",
                            retry_strategy="add_full_files",
                            attempt=len(failover),
                            current_agent=agent.name,
                            next_agent=helpers.next_candidate_name(candidates, agent) or "",
                        )
                    continue

                quality = router._validate_provider_output(
                    request=provider_request,
                    agent=agent,
                    result=result,
                    decision=decision,
                )
                if (
                    quality.should_retry
                    and agent != candidates[-1]
                    and helpers.routing_bool(router.config, "auto_retry", True)
                ):
                    reason = (
                        f"Output validation failed: {quality.retry_reason}; "
                        f"retry strategy: {quality.retry_strategy}"
                    )
                    router._record_failure(
                        agent,
                        error_type="output_validation_failed",
                        message=reason,
                        unavailable_until=None,
                        metadata={"quality_check": quality.to_dict()},
                        request_id=request_id,
                        request=provider_request,
                        routing_mode=decision.routing_mode,
                        failover_attempts=len(failover),
                    )
                    failover.append(
                        FailoverEvent(
                            agent=agent.name,
                            provider=agent.provider,
                            model=agent.model,
                            reason=reason,
                            retryable=True,
                            error_type="output_validation_failed",
                            metadata={"quality_check": quality.to_dict()},
                        )
                    )
                    router._record_internal_event(
                        ROUTER_FALLBACK,
                        request_id=request_id,
                        request=provider_request,
                        from_agent=agent.name,
                        from_provider=agent.provider,
                        from_model=agent.model,
                        reason=reason,
                        error_type="output_validation_failed",
                        next_agent=helpers.next_candidate_name(candidates, agent),
                        routing_mode=decision.routing_mode,
                    )
                    retry_planner = getattr(router, "_request_with_retry_plan", None)
                    if callable(retry_planner):
                        effective_request = retry_planner(
                            request=effective_request,
                            decision=decision,
                            retry_reason=quality.retry_reason,
                            retry_strategy=quality.retry_strategy,
                            attempt=len(failover),
                            current_agent=agent.name,
                            next_agent=helpers.next_candidate_name(candidates, agent) or "",
                        )
                    continue

                router._record_success(
                    agent,
                    latency,
                    result,
                    provider_request,
                    failover_attempts=len(failover),
                    request_id=request_id,
                    routing_mode=decision.routing_mode,
                    decision=decision,
                    failover=failover,
                )
                response = router._response_from_result(
                    request_id=request_id,
                    request=provider_request,
                    agent=agent,
                    result=result,
                    failover=failover,
                    decision=decision,
                    tool_loop_metadata=tool_loop["metadata"],
                    latency_seconds=latency,
                )
                if provider_request.record_session:
                    router.session_store.record_turn(provider_request, response)
                router._record_route_event(
                    "routing_decision",
                    request_id=request_id,
                    request=provider_request,
                    agent=agent.name,
                    provider=agent.provider,
                    model=response.model,
                    latency_seconds=round(latency, 4),
                    failover=[event.to_dict() for event in failover],
                    routing_decision=decision.to_dict(),
                    boost_explanation=(
                        response.raw.get("agent_hub", {}).get("boost_explanation")
                        if isinstance(response.raw, dict) and isinstance(response.raw.get("agent_hub"), dict)
                        else {}
                    ),
                    quality_check=(
                        response.raw.get("agent_hub", {}).get("quality_check")
                        if isinstance(response.raw, dict) and isinstance(response.raw.get("agent_hub"), dict)
                        else {}
                    ),
                    optimization_trace=(
                        response.raw.get("agent_hub", {}).get("optimization_trace")
                        if isinstance(response.raw, dict) and isinstance(response.raw.get("agent_hub"), dict)
                        else {}
                    ),
                )
                router._record_internal_event(
                    PROVIDER_SELECTED,
                    request_id=request_id,
                    request=provider_request,
                    agent=agent.name,
                    provider=agent.provider,
                    model=response.model,
                    routing_mode=decision.routing_mode,
                    latency_seconds=round(latency, 4),
                    failover_count=len(failover),
                    estimated_tokens=helpers.context_usage(provider_request).get(
                        "estimated_input_tokens"
                    ),
                )
                return response
            except ProviderError as exc:
                cooldown_seconds = router._cooldown_seconds(agent, exc)
                unavailable_until = (
                    time.time() + cooldown_seconds
                    if exc.retryable and cooldown_seconds > 0
                    else None
                )
                router._record_failure(
                    agent,
                    error_type=exc.error_type,
                    message=str(exc),
                    unavailable_until=unavailable_until,
                    status_code=exc.status_code,
                    metadata=exc.metadata or {},
                    request_id=request_id,
                    request=provider_request,
                    routing_mode=decision.routing_mode,
                    failover_attempts=len(failover),
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
                if exc.retryable and helpers.routing_bool(router.config, "auto_failover", True):
                    router._cooldowns[agent.name] = unavailable_until or time.time()
                    router._record_internal_event(
                        ROUTER_FALLBACK,
                        request_id=request_id,
                        request=provider_request,
                        from_agent=agent.name,
                        from_provider=agent.provider,
                        from_model=agent.model,
                        reason=str(exc),
                        error_type=exc.error_type,
                        retryable=exc.retryable,
                        next_agent=helpers.next_candidate_name(candidates, agent),
                        routing_mode=decision.routing_mode,
                    )
                    continue
                router._record_route_event(
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
                self._record_ledger_failure(
                    request_id=request_id,
                    request=effective_request,
                    agent=agent,
                    failover=failover,
                    decision=decision,
                )
                error_type = helpers.route_error_type(failover) or exc.error_type
                raise self.router_error_type(
                    str(exc),
                    failover=failover,
                    error_type=error_type,
                    suggested_fix=helpers.suggested_fix(error_type, failover),
                    status_code=exc.status_code or helpers.route_status_code(error_type),
                ) from exc

        if not tried_any:
            return self._raise_no_fallback(
                request_id=request_id,
                request=effective_request,
                failover=failover,
                decision=decision,
            )

        reason = helpers.no_fallback_reason(failover)
        error_type = helpers.route_error_type(failover)
        router._record_route_event(
            "routing_failure",
            request_id=request_id,
            request=effective_request,
            message=reason,
            error_type=error_type,
            failover=[event.to_dict() for event in failover],
        )
        if error_type == "invalid_provider_response":
            agent = (
                router.config.agents.get(failover[-1].agent)
                if failover and failover[-1].agent in router.config.agents
                else candidates[0]
            )
            result = safe_empty_provider_result(
                model=agent.model,
                reason="all_provider_responses_invalid",
            )
            response = router._response_from_result(
                request_id=request_id,
                request=effective_request,
                agent=agent,
                result=result,
                failover=failover,
                decision=decision,
            )
            if effective_request.record_session:
                router.session_store.record_turn(effective_request, response)
            self._record_ledger_failure(
                request_id=request_id,
                request=effective_request,
                agent=agent,
                failover=failover,
                decision=decision,
            )
            router._record_route_event(
                "safe_empty_response_generated",
                request_id=request_id,
                request=effective_request,
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
                failover=[event.to_dict() for event in failover],
            )
            return response
        agent = (
            router.config.agents.get(failover[-1].agent)
            if failover and failover[-1].agent in router.config.agents
            else candidates[0]
        )
        self._record_ledger_failure(
            request_id=request_id,
            request=effective_request,
            agent=agent,
            failover=failover,
            decision=decision,
        )
        raise self.router_error_type(
            reason,
            failover=failover,
            error_type=error_type,
            suggested_fix=helpers.suggested_fix(error_type, failover),
            status_code=helpers.route_status_code(error_type),
        )

    def _raise_no_fallback(
        self,
        *,
        request_id: str,
        request: HubRequest,
        failover: list[FailoverEvent],
        decision: Any,
    ) -> Any:
        helpers = self.helpers
        reason = helpers.no_fallback_reason(failover)
        error_type = helpers.route_error_type(failover)
        self.router._record_route_event(
            "routing_failure",
            request_id=request_id,
            request=request,
            message=reason,
            error_type=error_type,
            failover=[event.to_dict() for event in failover],
        )
        agent = None
        if failover and failover[-1].agent in self.router.config.agents:
            agent = self.router.config.agents[failover[-1].agent]
        else:
            agent = next((item for item in self.router.config.agents.values() if item.enabled), None)
        if agent is not None:
            self._record_ledger_failure(
                request_id=request_id,
                request=request,
                agent=agent,
                failover=failover,
                decision=decision,
            )
        raise self.router_error_type(
            reason,
            failover=failover,
            error_type=error_type,
            suggested_fix=helpers.suggested_fix(error_type, failover),
            status_code=helpers.route_status_code(error_type),
        )

    def _record_ledger_failure(
        self,
        *,
        request_id: str,
        request: HubRequest,
        agent: AgentConfig,
        failover: list[FailoverEvent],
        decision: Any,
    ) -> None:
        recorder = getattr(self.router, "_record_usage_ledger_outcome", None)
        if not callable(recorder):
            return
        recorder(
            request_id=request_id,
            request=request,
            agent=agent,
            model=agent.model,
            result=ProviderResult(text="", model=agent.model, usage={}, finish_reason="error"),
            success=False,
            latency_seconds=None,
            failover=failover,
            decision=decision,
            task_type=getattr(decision, "task_type", "") or "general",
        )


def _request_max_provider_attempts(request: HubRequest, default: int) -> int:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    policy = hub.get("fallback_policy") if isinstance(hub.get("fallback_policy"), dict) else {}
    value = policy.get("max_provider_attempts")
    try:
        attempts = int(value)
    except (TypeError, ValueError):
        attempts = int(default or 5)
    return max(1, min(attempts, 20))


__all__ = ["ProviderAttemptExecutor", "ProviderAttemptHelpers"]
