from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, fields, replace
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..adaptive import AdaptiveLearningStore, estimate_known_cost_usd
from ..capabilities import agent_capabilities
from ..config import AgentConfig, HubConfig, is_free_agent, normalize_provider
from ..context import estimate_message_tokens, is_protected_context_message
from ..debug import debug_dir_for_state, provider_debug_context
from ..events import (
    CONTEXT_TRUNCATED,
    PROVIDER_FAILED,
    PROVIDER_SELECTED,
    RouterEventRecorder,
    STREAM_FAILED,
    STREAM_STARTED,
    request_source,
)
from ..evaluation import ProviderScoreStore
from ..mcp import MCPServerRegistry
from ..models import ErrorCategory, FailoverEvent, HubRequest, HubResponse, ProviderResult, StructuredError
from ..payloads import content_to_text, request_text
from ..providers import Provider, ProviderError, create_provider
from ..response_normalization import validate_provider_result
from ..repository import repo_context_for_request
from ..security.provider_permissions import ProviderPermissionPolicy
from ..session_store import SessionStore
from ..streaming import normalize_stream_chunk
from ..token_optimizer import ContextCache, TokenOptimizer
from ..tools import ToolExecutionPipeline, ToolLoopRunner, create_builtin_registry
from ..tools.loop import (
    ToolLoopMetadata,
    merge_tool_loop_metadata,
)
from .health import (
    ProviderHealth,
    ProviderHealthTracker,
    calculate_provider_score,
    health_state_label,
    provider_cost_efficiency_score,
)
from .provider_manager import ProviderManager
from .provider_attempts import ProviderAttemptExecutor, ProviderAttemptHelpers
from .router_diagnostics import build_capability_graph, build_provider_status
from .routing_policy import (
    CONFIGURATION_ERROR,
    ECHO_DISABLED,
    NO_TOOL_CAPABLE_MODEL,
    RouterPreflightPolicy,
    estimate_input_tokens,
    expected_output_tokens,
    _agent_supports_tools,
    _is_echo_agent,
    _is_local_or_private_agent,
    _request_has_client_tool_specs,
    _request_has_tools,
    _requires_missing_api_key,
    _requires_tool_capable_model,
)


ProviderFactory = Callable[[AgentConfig], Provider]
HEALTH_STATE_VERSION = 1
HEALTH_STATE_FILE = "provider_health.json"
HEALTH_STALE_SECONDS = 7 * 24 * 60 * 60
MAX_FAILOVER_HISTORY = 50
ERROR_TYPE_ALIASES = {
    "rate_limited": "temporary_rate_limit",
    "context_limit": "context_too_large",
    "temporary_unavailable": "provider_overloaded",
    "authentication": "authentication_error",
    "model_unavailable": "provider_unavailable",
    "network": "provider_unavailable",
    "timeout": "provider_unavailable",
    "provider_error": "unknown_error",
}
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
    candidate_scores: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "selected_agent": self.selected_agent,
            "selected_provider": self.selected_provider,
            "selected_model": self.selected_model,
            "routing_mode": self.routing_mode,
            "task_type": self.task_type,
            "reason": self.reason,
            "fallback_chain": list(self.fallback_chain),
            "estimated_input_tokens": self.estimated_input_tokens,
        }
        if self.candidate_scores:
            data["candidate_scores"] = list(self.candidate_scores)
        return data


@dataclass(slots=True)
class StreamingRoute:
    """Native streaming route selected before HTTP SSE emission."""

    request_id: str
    session_id: str
    agent: AgentConfig
    public_model: str
    decision: RoutingDecision
    failover: list[FailoverEvent]
    request: HubRequest
    chunks: Any

    @property
    def provider(self) -> str:
        return self.agent.provider

    @property
    def model(self) -> str:
        return self.agent.model


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

    def to_structured_error(self) -> StructuredError:
        details: dict[str, Any] = {}
        if self.failover:
            details["failover"] = [event.to_dict() for event in self.failover]
        if self.suggested_fix:
            details["suggested_fix"] = self.suggested_fix
        return StructuredError(
            category=_router_error_category(self.error_type),
            code=self.error_type or "router_error",
            message=str(self),
            retryable=any(event.retryable for event in self.failover),
            user_message=_router_user_message(str(self), self.suggested_fix),
            status_code=self.status_code,
            details=details,
        )


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
        self.health_tracker = ProviderHealthTracker(self._health_path)
        self._health: dict[str, ProviderHealth] = self._load_provider_health()
        self.preflight_policy = RouterPreflightPolicy(config, self._health)
        self.provider_permission_policy = ProviderPermissionPolicy(config)
        self.event_recorder = RouterEventRecorder(config.state_dir)
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
        self.provider_attempt_executor = ProviderAttemptExecutor(
            self,
            helpers=ProviderAttemptHelpers(
                routing_bool=_routing_bool,
                routing_float=_routing_float,
                routing_int=_routing_int,
                continuation_request=_continuation_request,
                merge_continuation_result=_merge_continuation_result,
                token_limit_finish_reason=_token_limit_finish_reason,
                next_candidate_name=_next_candidate_name,
                no_fallback_reason=_no_fallback_reason,
                route_error_type=_route_error_type,
                suggested_fix=_suggested_fix,
                route_status_code=_route_status_code,
                context_usage=_context_usage,
            ),
            router_error_type=RouterError,
        )
        self.tool_registry = create_builtin_registry(config)
        try:
            self.tool_registry.extend(MCPServerRegistry(config).agent_hub_tools())
        except Exception:
            pass
        self.tool_pipeline = ToolExecutionPipeline(self.tool_registry)
        self.tool_loop_runner = ToolLoopRunner(
            config=config,
            registry=self.tool_registry,
            pipeline=self.tool_pipeline,
            chat_provider=self.provider_manager.chat,
            record_tool_result=self.record_tool_result,
            record_event=self._record_route_event,
        )
        self.provider_scores = ProviderScoreStore(config.state_dir).load()
        self.adaptive_learning = AdaptiveLearningStore(config.state_dir)
        self.context_cache = ContextCache(
            config.state_dir / "context_cache.json",
            enabled=getattr(config, "context_cache_enabled", True),
            max_entries=getattr(config, "context_cache_max_entries", 128),
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
        effective_request = self._prepare_request(self._with_session_history(request))
        request_id = f"hub-{uuid.uuid4().hex}"
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

        return self.provider_attempt_executor.execute(
            request_id=request_id,
            effective_request=effective_request,
            decision=decision,
            candidates=candidates,
        )

    def native_stream(self, request: HubRequest) -> StreamingRoute | None:
        """Return a provider-native stream route, or None for compatibility streaming."""

        if getattr(self.config, "force_compatibility_streaming", False) or (
            _request_is_cline(request) and getattr(self.config, "cline_compatibility_mode", True)
        ):
            return None
        effective_request = self._prepare_request(self._with_session_history(request), include_tools=False)
        request_id = f"hub-{uuid.uuid4().hex}"
        decision = self.decide(effective_request)
        candidates = self._candidate_agents(effective_request, decision=decision)
        failover: list[FailoverEvent] = []
        self._record_route_event(
            "stream_request_started",
            request_id=request_id,
            request=effective_request,
            routing_decision=decision.to_dict(),
            candidates=[agent.name for agent in candidates],
        )

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

            stream_request = self._request_for_agent(
                request_id=request_id,
                request=effective_request,
                agent=agent,
                decision=decision,
                stream=True,
            )

            skip_reason = self._preflight_skip_reason(agent, stream_request)
            if skip_reason:
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason=skip_reason,
                        retryable=False,
                        error_type=self._preflight_error_type(agent, stream_request, skip_reason),
                    )
                )
                continue

            permission = self._provider_permission_decision(agent, stream_request)
            if permission is not None and not permission.allowed:
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason=permission.reason or "Permission required before using this provider.",
                        retryable=False,
                        error_type="permission_required" if permission.requires_approval else "permission_denied",
                        metadata={
                            "permission": permission.request.to_dict() if permission.request else None,
                            "trust_level": self.provider_permission_policy.trust_level(agent),
                        },
                    )
                )
                continue

            if not self._adapter_supports_native_streaming(agent):
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason="Provider adapter does not advertise native streaming support.",
                        retryable=False,
                        error_type="native_streaming_unavailable",
                    )
                )
                continue

            self._record_internal_event(
                PROVIDER_SELECTED,
                request_id=request_id,
                request=effective_request,
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
                routing_mode=decision.routing_mode,
                stream_mode="native",
                failover_count=len(failover),
                estimated_tokens=_context_usage(stream_request).get("estimated_input_tokens"),
            )
            return StreamingRoute(
                request_id=request_id,
                session_id=stream_request.session_id,
                agent=agent,
                public_model=_public_model_name(stream_request),
                decision=decision,
                failover=failover,
                request=stream_request,
                chunks=self._native_stream_chunks(
                    request_id=request_id,
                    request=stream_request,
                    agent=agent,
                    failover=failover,
                    decision=decision,
                ),
            )

        self._record_route_event(
            "stream_fallback_to_compatibility",
            request_id=request_id,
            request=effective_request,
            routing_decision=decision.to_dict(),
            failover=[event.to_dict() for event in failover],
        )
        return None

    def native_stream_for_agent(self, request: HubRequest, agent_name: str) -> StreamingRoute | None:
        """Create a native stream for an explicit agent, used for replay-safe recovery."""

        agent = self.config.agents.get(agent_name)
        if agent is None or not agent.enabled or not self._adapter_supports_native_streaming(agent):
            return None
        request_id = f"hub-{uuid.uuid4().hex}"
        decision = self.decide(request)
        stream_request = self._request_for_agent(
            request_id=request_id,
            request=request,
            agent=agent,
            decision=decision,
            stream=True,
        )
        skip_reason = self._preflight_skip_reason(agent, stream_request)
        if skip_reason:
            return None
        permission = self._provider_permission_decision(agent, stream_request)
        if permission is not None and not permission.allowed:
            return None
        return StreamingRoute(
            request_id=request_id,
            session_id=stream_request.session_id,
            agent=agent,
            public_model=_public_model_name(stream_request),
            decision=decision,
            failover=[],
            request=stream_request,
            chunks=self._native_stream_chunks(
                request_id=request_id,
                request=stream_request,
                agent=agent,
                failover=[],
                decision=decision,
            ),
        )

    def _adapter_supports_native_streaming(self, agent: AgentConfig) -> bool:
        if not agent.supports_streaming:
            return False
        try:
            adapter = self.provider_manager.create(agent)
        except ProviderError:
            return False
        supports = getattr(adapter, "supports_streaming", None)
        stream = getattr(adapter, "stream", None)
        try:
            return callable(stream) and callable(supports) and bool(supports())
        except Exception:
            return False

    def _native_stream_chunks(
        self,
        *,
        request_id: str,
        request: HubRequest,
        agent: AgentConfig,
        failover: list[FailoverEvent],
        decision: RoutingDecision,
    ) -> Any:
        started = time.perf_counter()
        last_chunk_at = started
        text_parts: list[str] = []
        usage_tokens = 0
        model = agent.model
        finish_reason: str | None = None
        first_token_latency_seconds = 0.0
        stream_request = request
        self._record_internal_event(
            STREAM_STARTED,
            request_id=request_id,
            request=stream_request,
            agent=agent.name,
            provider=agent.provider,
            model=agent.model,
            routing_mode=decision.routing_mode,
            stream_mode="native",
            estimated_tokens=_context_usage(stream_request).get("estimated_input_tokens"),
        )
        try:
            for chunk in self.provider_manager.stream(agent, stream_request):
                now = time.perf_counter()
                chunk = normalize_stream_chunk(chunk, default_model=agent.model)
                if chunk is None:
                    continue
                if chunk.text:
                    first_token_seconds = now - started
                    if not text_parts:
                        first_token_latency_seconds = first_token_seconds
                    gap_seconds = now - last_chunk_at
                    slow_first_token = _routing_float(
                        self.config,
                        "slow_first_token_timeout_seconds",
                        20.0,
                    )
                    stream_stall = _routing_float(
                        self.config,
                        "stream_stall_timeout_seconds",
                        30.0,
                    )
                    failover_on_slow_stream = _routing_bool(self.config, "failover_on_slow_stream", True)
                    if (
                        failover_on_slow_stream
                        and not text_parts
                        and slow_first_token > 0
                        and first_token_seconds > slow_first_token
                    ):
                        raise ProviderError(
                            (
                                "Provider time-to-first-token exceeded failover threshold: "
                                f"{first_token_seconds:.2f}s > {slow_first_token:.2f}s"
                            ),
                            retryable=True,
                            error_type="provider_overloaded",
                        )
                    if (
                        failover_on_slow_stream
                        and text_parts
                        and stream_stall > 0
                        and gap_seconds > stream_stall
                    ):
                        raise ProviderError(
                            (
                                "Provider stream stalled beyond failover threshold: "
                                f"{gap_seconds:.2f}s > {stream_stall:.2f}s"
                            ),
                            retryable=True,
                            error_type="provider_overloaded",
                        )
                if chunk.text:
                    text_parts.append(chunk.text)
                    usage_tokens += max(1, len(chunk.text) // 4)
                    elapsed = max(0.001, now - started)
                    minimum_tps = _routing_float(self.config, "min_tokens_per_second", 2.0)
                    if (
                        _routing_bool(self.config, "failover_on_slow_stream", True)
                        and minimum_tps > 0
                        and usage_tokens >= 4
                        and elapsed > 1.0
                        and (usage_tokens / elapsed) < minimum_tps
                    ):
                        raise ProviderError(
                            (
                                "Provider stream throughput fell below failover threshold: "
                                f"{usage_tokens / elapsed:.2f} tokens/s < {minimum_tps:.2f} tokens/s"
                            ),
                            retryable=True,
                            error_type="provider_overloaded",
                        )
                    last_chunk_at = now
                if chunk.model:
                    model = chunk.model
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                yield chunk
            latency = time.perf_counter() - started
            result = ProviderResult(
                text="".join(text_parts),
                model=model,
                raw={
                    "agent_hub_stream": {
                        "mode": "native",
                        "first_token_latency_seconds": round(first_token_latency_seconds, 4),
                    }
                },
                usage={"completion_tokens": usage_tokens, "output_tokens": usage_tokens},
                finish_reason=finish_reason or "stop",
            )
            self._record_success(
                agent,
                latency,
                result,
                stream_request,
                failover_attempts=len(failover),
                request_id=request_id,
                first_token_latency_seconds=float(
                    result.raw.get("agent_hub_stream", {}).get("first_token_latency_seconds") or 0.0
                )
                if isinstance(result.raw.get("agent_hub_stream"), dict)
                else None,
            )
            response = self._response_from_result(
                request_id=request_id,
                request=stream_request,
                agent=agent,
                result=result,
                failover=failover,
                decision=decision,
            )
            if stream_request.record_session:
                self.session_store.record_turn(stream_request, response)
            self._record_route_event(
                "native_stream_finished",
                request_id=request_id,
                request=stream_request,
                agent=agent.name,
                provider=agent.provider,
                model=model,
                latency_seconds=round(latency, 4),
                stream_mode="native",
                failover=[event.to_dict() for event in failover],
                routing_decision=decision.to_dict(),
            )
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
                request_id=request_id,
                request=stream_request,
                routing_mode=decision.routing_mode,
                failover_attempts=len(failover),
            )
            self._record_internal_event(
                STREAM_FAILED,
                request_id=request_id,
                request=stream_request,
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
                routing_mode=decision.routing_mode,
                stream_mode="native",
                error_type=exc.error_type,
                message=str(exc),
                retryable=exc.retryable,
            )
            self._record_route_event(
                "native_stream_failure",
                request_id=request_id,
                request=request,
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
                error_type=exc.error_type,
                message=str(exc),
            )
            raise
        except Exception as exc:
            self._record_failure(
                agent,
                error_type="native_stream_error",
                message=str(exc),
                request_id=request_id,
                request=stream_request,
                routing_mode=decision.routing_mode,
                failover_attempts=len(failover),
            )
            self._record_internal_event(
                STREAM_FAILED,
                request_id=request_id,
                request=stream_request,
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
                routing_mode=decision.routing_mode,
                stream_mode="native",
                error_type="native_stream_error",
                message=str(exc),
            )
            self._record_route_event(
                "native_stream_failure",
                request_id=request_id,
                request=request,
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
                error_type="native_stream_error",
                message=str(exc),
            )
            raise

    def _provider_permission_decision(self, agent: AgentConfig, request: HubRequest):
        return self.provider_permission_policy.check(agent, request)

    def _enterprise_permission_decision(
        self,
        permission_request: Any,
        request: HubRequest,
        approval_mode: str,
    ):
        return self.provider_permission_policy.check_enterprise(
            permission_request,
            request,
            approval_mode,
        )

    def _request_for_agent(
        self,
        *,
        request_id: str,
        request: HubRequest,
        agent: AgentConfig,
        decision: RoutingDecision,
        stream: bool = False,
    ) -> HubRequest:
        prepared, usage = self._apply_context_safety_cap(agent, request)
        metadata = dict(prepared.metadata)
        output_tokens = expected_output_tokens(prepared, agent)
        metadata["agent_hub_debug"] = provider_debug_context(
            enabled=getattr(self.config, "debug_raw_provider_responses", False),
            debug_dir=debug_dir_for_state(self.config.state_dir),
            request_id=request_id,
            provider=agent.provider,
            provider_name=agent.provider_type or agent.provider,
            model=agent.model,
            routing_mode=decision.routing_mode,
            estimated_input_tokens=int(usage["estimated_input_tokens"]),
            estimated_output_tokens=int(output_tokens),
            provider_limit=agent.context_window,
            stream_id=f"stream-{uuid.uuid4().hex}" if stream else None,
        )
        raw = dict(prepared.raw or {})
        hub = dict(raw.get("agent_hub") or {})
        hub["context_usage"] = usage
        hub.setdefault("auto_retry", _routing_bool(self.config, "auto_retry", True))
        hub.setdefault("auto_failover", _routing_bool(self.config, "auto_failover", True))
        raw["agent_hub"] = hub
        self._record_route_event(
            "context_token_estimate",
            request_id=request_id,
            request=prepared,
            agent=agent.name,
            provider=agent.provider,
            model=agent.model,
            **usage,
        )
        if usage.get("context_reduced"):
            self._record_internal_event(
                CONTEXT_TRUNCATED,
                request_id=request_id,
                request=prepared,
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
                routing_mode=decision.routing_mode,
                estimated_input_tokens=usage.get("estimated_input_tokens"),
                original_input_tokens=usage.get("original_input_tokens"),
                max_context_tokens=usage.get("max_context_tokens"),
                compression_ratio=usage.get("compression_ratio"),
                warnings=usage.get("warnings"),
            )
        return replace(prepared, metadata=metadata, raw=raw)

    def _chat_with_validation(
        self,
        *,
        request_id: str,
        agent: AgentConfig,
        request: HubRequest,
        decision: RoutingDecision,
    ) -> ProviderResult:
        del decision
        result = self.provider_manager.chat(agent, request)
        validation = validate_provider_result(result)
        if validation.valid:
            return result
        if not _routing_bool(self.config, "auto_retry", True):
            raise ProviderError(
                f"Provider returned invalid response: {validation.reason}",
                retryable=True,
                error_type="invalid_provider_response",
                metadata={"issues": validation.issues},
            )
        self._record_route_event(
            "provider_response_invalid",
            request_id=request_id,
            request=request,
            agent=agent.name,
            provider=agent.provider,
            model=agent.model,
            reason=validation.reason,
            issues=validation.issues,
            retrying=True,
        )
        result = self.provider_manager.chat(agent, request)
        validation = validate_provider_result(result)
        if validation.valid:
            self._record_route_event(
                "provider_response_retry_recovered",
                request_id=request_id,
                request=request,
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
            )
            return result
        raise ProviderError(
            f"Provider returned invalid response: {validation.reason}",
            retryable=True,
            error_type="invalid_provider_response",
            metadata={"issues": validation.issues},
        )

    def _continue_after_output_limit(
        self,
        *,
        request_id: str,
        agent: AgentConfig,
        request: HubRequest,
        decision: RoutingDecision,
        result: ProviderResult,
    ) -> tuple[ProviderResult | None, float]:
        continuation_request = _continuation_request(
            request,
            result.text,
            "same_provider_output_limit",
        )
        continuation_request = self._request_for_agent(
            request_id=request_id,
            request=continuation_request,
            agent=agent,
            decision=decision,
        )
        started = time.perf_counter()
        try:
            continuation = self._chat_with_validation(
                request_id=request_id,
                agent=agent,
                request=continuation_request,
                decision=decision,
            )
        except ProviderError as exc:
            latency = time.perf_counter() - started
            self._record_route_event(
                "output_continuation_failed",
                request_id=request_id,
                request=continuation_request,
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
                error_type=exc.error_type,
                message=str(exc),
            )
            return None, latency
        latency = time.perf_counter() - started
        self._record_route_event(
            "output_continuation_succeeded",
            request_id=request_id,
            request=continuation_request,
            agent=agent.name,
            provider=agent.provider,
            model=agent.model,
            continuation_finish_reason=continuation.finish_reason,
        )
        return (
            _merge_continuation_result(
                result.text,
                continuation,
                model=continuation.model or result.model,
                raw_reason="same_provider_output_limit",
            ),
            latency,
        )

    def _apply_context_safety_cap(
        self,
        agent: AgentConfig,
        request: HubRequest,
    ) -> tuple[HubRequest, dict[str, Any]]:
        original_messages = [dict(message) for message in request.messages]
        original_tokens = estimate_message_tokens(original_messages)
        cap = _context_cap(self.config, request, agent)
        output_tokens = expected_output_tokens(request, agent)
        provider_limit = agent.context_window
        effective_cap = cap
        if provider_limit is not None:
            effective_cap = min(effective_cap, max(1000, int(provider_limit) - int(output_tokens)))
        messages = original_messages
        warnings: list[str] = []
        if original_tokens > effective_cap:
            messages, warnings = _compress_messages_for_budget(messages, effective_cap)
            warnings.append("[Context reduced for provider compatibility]")
        optimizer = TokenOptimizer(
            cache=self.context_cache,
            summarization_enabled=getattr(self.config, "context_summarization_enabled", False),
        )
        optimized = optimizer.optimize(messages, max_context_tokens=effective_cap)
        messages = optimized.messages
        warnings.extend(optimized.warnings)
        final_tokens = optimized.final_tokens
        ratio = round(final_tokens / original_tokens, 4) if original_tokens else 1.0
        usage = {
            "estimated_input_tokens": final_tokens,
            "estimated_output_tokens": int(output_tokens),
            "provider_limit": provider_limit,
            "max_context_tokens": effective_cap,
            "original_input_tokens": original_tokens,
            "compression_ratio": ratio,
            "context_reduced": bool(warnings),
            "tokens_saved": optimized.tokens_saved,
            "context_cache_hit": optimized.cache_hit,
            "context_cache_enabled": self.context_cache.enabled,
            "summarization_hook_applied": optimized.summarized,
            "warnings": warnings,
        }
        if messages == request.messages:
            return request, usage
        return replace(request, messages=messages), usage

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

    def _prepare_request(self, request: HubRequest, *, include_tools: bool = True) -> HubRequest:
        if include_tools:
            request = self._with_builtin_tool_specs(request)
        prepared = self._with_repo_context(request)
        return prepared

    def _with_repo_context(self, request: HubRequest) -> HubRequest:
        if not getattr(self.config, "repo_context_enabled", True):
            return request
        if _agent_runner_managed_request(request):
            return request
        if _request_has_client_tool_specs(request):
            return request
        if not _repo_context_useful(request):
            return request
        if any(message.get("agent_hub_repo_context") for message in request.messages if isinstance(message, dict)):
            return request
        max_files = self.config.repo_context_max_files
        max_chars = self.config.repo_context_max_chars
        if _compatibility_reductions_enabled(self.config, request, "reduced_repo_context"):
            max_files = min(max_files, 3)
            max_chars = min(max_chars, 4_000)
        try:
            selection = repo_context_for_request(
                request,
                self.config.workspace_dir,
                max_files=max_files,
                max_chars=max_chars,
                ignore_patterns=self.config.repo_ignore_patterns,
            )
        except Exception:
            return request
        message = selection.to_message()
        if message is None:
            return request
        raw = dict(request.raw or {})
        hub = dict(raw.get("agent_hub") or {})
        hub["repo_context"] = selection.to_dict()
        raw["agent_hub"] = hub
        return replace(request, messages=[message, *request.messages], raw=raw)

    def _with_builtin_tool_specs(self, request: HubRequest) -> HubRequest:
        if not getattr(self.config, "tool_loop_enabled", True):
            return request
        if _request_is_cline(request) and not getattr(self.config, "tool_loop_enabled_for_cline", False):
            return request
        if _agent_runner_managed_request(request):
            return request
        if _request_has_client_tool_specs(request):
            return request
        if _request_option(request, "disable_builtin_tools", "disable_agent_hub_tools") is True:
            return request
        if not _repo_or_tool_task(request):
            return request
        if not self._has_tool_capable_candidate(request):
            return request
        raw = dict(request.raw or {})
        if isinstance(raw.get("agent_hub_tools"), list) and raw["agent_hub_tools"]:
            return request
        tool_specs = [tool.to_agent_hub_spec() for tool in self.tool_registry.list()]
        if _compatibility_reductions_enabled(self.config, request, "minimal_tool_schema"):
            tool_specs = [_minimal_tool_schema(spec) for spec in tool_specs]
        raw["agent_hub_tools"] = tool_specs
        hub = dict(raw.get("agent_hub") or {})
        hub["auto_execute_tools"] = True
        raw["agent_hub"] = hub
        return replace(request, raw=raw)

    def _has_tool_capable_candidate(self, request: HubRequest) -> bool:
        names: list[str] = []
        if request.preferred_agent:
            names.append(request.preferred_agent)
        names.extend(self._manual_model_or_provider_agent_names(request))
        names.extend(self._route_names(request))
        return any(
            _agent_supports_tools(agent)
            for name in names
            if (agent := self.config.agents.get(name)) is not None and agent.enabled
        )

    def _run_tool_loop(
        self,
        *,
        request_id: str,
        agent: AgentConfig,
        request: HubRequest,
        initial_result: ProviderResult,
    ) -> dict[str, Any]:
        return self.tool_loop_runner.run(
            request_id=request_id,
            agent=agent,
            request=request,
            initial_result=initial_result,
        ).to_router_dict()

    def _should_execute_tool_calls(self, request: HubRequest, calls: list[Any]) -> bool:
        return self.tool_loop_runner.should_execute_tool_calls(request, calls)

    def decide(self, request: HubRequest) -> RoutingDecision:
        """Choose a ranked fallback chain before execution."""

        mode = self._routing_mode(request)
        task_type = self._classify_task(request)
        agents = self._candidate_agent_pool(request, mode=mode)
        selected = agents[0] if agents else None
        candidate_scores = self._routing_candidate_scorecards(request, agents)
        reason = self._routing_decision_reason(
            mode=mode,
            task_type=task_type,
            selected=selected,
            request=request,
        )
        adaptive_reason = _adaptive_route_reason(candidate_scores)
        if adaptive_reason and mode != "manual":
            reason = f"{reason} {adaptive_reason}"
        return RoutingDecision(
            selected_agent=selected.name if selected else None,
            selected_provider=selected.provider if selected else "",
            selected_model=selected.model if selected else "",
            routing_mode=mode,
            task_type=task_type,
            reason=reason,
            fallback_chain=[agent.name for agent in agents],
            estimated_input_tokens=estimate_input_tokens(request),
            candidate_scores=candidate_scores,
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
        if task_type == "long_context":
            return "long_context"
        if task_type in {"coding", "debug", "review", "tool_use"}:
            return "coding"
        return DEFAULT_ROUTING_MODE

    def _classify_task(self, request: HubRequest) -> str:
        if _privacy_requested(request):
            return "local_private"
        if estimate_input_tokens(request) >= LONG_CONTEXT_TOKEN_THRESHOLD:
            return "long_context"
        text = _classification_text(request).lower()
        if _request_has_tools(request):
            return "tool_use"
        if _looks_like_debug_task(text):
            return "debug"
        if _looks_like_review_task(text):
            return "review"
        if _looks_like_research_task(text):
            return "research"
        if _looks_like_coding_task(text):
            return "coding"
        return "general"

    def _rank_agents_for_mode(
        self,
        agents: list[AgentConfig],
        request: HubRequest,
        mode: str,
    ) -> list[AgentConfig]:
        if mode == "manual":
            return agents
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

    def _routing_candidate_scorecards(
        self,
        request: HubRequest,
        agents: list[AgentConfig],
    ) -> list[dict[str, Any]]:
        task_type = self._classify_task(request)
        workflow_pattern = _request_workflow_pattern(request)
        workflow_role = _request_workflow_role(request)
        rows: list[dict[str, Any]] = []
        for rank, agent in enumerate(agents[:8], start=1):
            health = self._health.get(agent.name)
            if self.config.adaptive_learning_enabled and self.config.adaptive_routing_enabled:
                adaptive = self.adaptive_learning.routing_signal(
                    agent.name,
                    route=request.route or "",
                    task_type=task_type,
                    workflow_pattern=workflow_pattern,
                    workflow_role=workflow_role,
                )
            else:
                adaptive = {
                    "agent": agent.name,
                    "active": False,
                    "adaptive_bonus": 0.0,
                    "summary": "Adaptive routing is disabled by configuration.",
                }
            rows.append(
                {
                    "rank": rank,
                    "agent": agent.name,
                    "provider": agent.provider,
                    "provider_type": agent.provider_type or normalize_provider(agent.provider),
                    "model": agent.model,
                    "routing_score": round(self._routing_score(agent, request), 3),
                    "adaptive": adaptive,
                    "health": {
                        "success_count": health.success_count if health else 0,
                        "failure_count": health.failure_count if health else 0,
                        "reliability_score": round(health.reliability_score, 4) if health else 0.7,
                        "average_latency_ms": round(health.average_latency_ms, 2) if health else 0.0,
                        "degraded": health.is_degraded() if health else False,
                    },
                    "capabilities": {
                        "supports_tools": bool(agent.supports_tools or agent.supports_function_calling),
                        "supports_streaming": bool(agent.supports_streaming),
                        "context_window": agent.context_window,
                    },
                }
            )
        return rows

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
        tool_loop_metadata: ToolLoopMetadata | None = None,
    ) -> HubResponse:
        raw = result.raw
        if tool_loop_metadata is not None and (
            tool_loop_metadata.tool_calls or tool_loop_metadata.tool_results
        ):
            raw = merge_tool_loop_metadata(raw if isinstance(raw, dict) else {}, tool_loop_metadata)
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
            if tool_loop_metadata is not None:
                agent_metadata.update(tool_loop_metadata.to_dict())
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
            capabilities = agent_capabilities(agent) if agent else None
            cooldown_until = max(self._cooldowns.get(name, 0.0), health.cooldown_deadline())
            available = bool(agent.enabled) if agent else False
            if agent and self.config.free_only and not is_free_agent(agent):
                available = False
            if agent and _requires_missing_api_key(agent):
                available = False
            if agent and _is_echo_agent(agent) and not self.config.debug_echo_enabled:
                available = False
            score = calculate_provider_score(agent, health) if agent else None
            quota_state = _health_quota_state(health)
            quota_exhaustion_active = health.quota_exhausted and cooldown_until > now
            row: dict[str, Any] = {
                "agent": name,
                "name": name,
                "provider": agent.provider if agent else "",
                "provider_name": agent.provider if agent else "",
                "provider_type": (
                    agent.provider_type or normalize_provider(agent.provider)
                    if agent else ""
                ),
                "model": agent.model if agent else "",
                "available": available,
                "degraded": health.is_degraded(now),
                "streaming": capabilities.supports_streaming if capabilities else False,
                "supports_streaming": capabilities.supports_streaming if capabilities else False,
                "tool_support": capabilities.tool_capable if capabilities else False,
                "supports_tools": capabilities.tool_capable if capabilities else False,
                "function_support": capabilities.supports_function_calling if capabilities else False,
                "json_mode_support": capabilities.supports_json if capabilities else False,
                "supports_json": capabilities.supports_json if capabilities else False,
                "context_window": capabilities.context_window if capabilities else health.context_window,
                "max_output_tokens": (
                    capabilities.max_output_tokens
                    if capabilities and capabilities.max_output_tokens is not None
                    else health.max_output_tokens
                ),
                "quota_remaining": health.quota_remaining,
                "requests_remaining": health.requests_remaining,
                "tokens_remaining": health.tokens_remaining,
                "credits_remaining": health.credits_remaining,
                "remaining": _remaining_quota_value(health),
                "quota_state": quota_state,
                "quota_source": "provider" if quota_state != "unknown" else "unknown",
                "rate_limited": health.rate_limited,
                "rate_limit_state": "limited" if health.rate_limited else "ok",
                "quota_exhausted": quota_exhaustion_active,
                "quota_exhausted_state": "exhausted" if quota_exhaustion_active else "ok",
                "cooldown_until": cooldown_until,
                "unavailable_until": cooldown_until,
                "rate_limit_reset_at": health.rate_limit_reset_at,
                "latency_ms": round(health.average_latency_ms, 2),
                "average_latency_ms": round(health.average_latency_ms, 2),
                "average_latency_seconds": round(health.average_latency_seconds, 4),
                "average_tokens_per_second": round(health.average_tokens_per_second, 4),
                "streaming_tokens_per_second": round(health.streaming_tokens_per_second, 4),
                "reliability_score": round(health.reliability_score, 4),
                "score": round(score.total, 3) if score else 0.0,
                "score_components": score.to_dict() if score else {},
                "success_count": health.success_count,
                "failure_count": health.failure_count,
                "timeout_count": health.timeout_count,
                "tool_call_success_count": health.tool_call_success_count,
                "tool_call_failure_count": health.tool_call_failure_count,
                "success_rate": round(health.success_rate, 4),
                "last_success_at": health.last_success_at,
                "last_failure_at": health.last_failure_at,
                "last_error_time": health.last_failure_at,
                "last_checked_at": health.last_checked_at,
                "last_request_source": health.last_request_source,
                "last_route": health.last_route,
                "last_request_started_at": health.last_request_started_at,
                "last_first_token_latency_seconds": round(health.last_first_token_latency_seconds, 4),
                "last_total_latency_seconds": round(health.last_total_latency_seconds, 4),
                "last_input_tokens": health.last_input_tokens,
                "last_output_tokens": health.last_output_tokens,
                "last_tokens_per_second": round(health.last_tokens_per_second, 4),
                "last_finish_reason": health.last_finish_reason,
                "last_failover_attempts": health.last_failover_attempts,
                "last_context_compaction_usage": dict(health.last_context_compaction_usage),
                "stream_interruption_count": health.stream_interruption_count,
                "tokens_in": health.tokens_in,
                "tokens_out": health.tokens_out,
                "last_error_type": health.last_error_type,
                "last_error_message": health.last_error_message,
            }
            if cooldown_until > now:
                row["available"] = False
            if health.quota_remaining is not None and health.quota_remaining <= 0:
                row["available"] = False
            if health.quota_exhausted and cooldown_until > now:
                row["available"] = False
            if health.requests_remaining is not None and health.requests_remaining <= 0:
                row["available"] = False
            if health.tokens_remaining is not None and health.tokens_remaining <= 0:
                row["available"] = False
            row["health"] = health_state_label(row)
            if include_history:
                row["failover_events"] = list(health.failover_events)
            snapshot[name] = row
        return snapshot

    def provider_status(self) -> list[dict[str, Any]]:
        """Return health-centered provider rows for the /health endpoint."""

        return build_provider_status(
            self.config,
            self.health_snapshot(include_history=False),
        )

    def capability_graph(self) -> dict[str, Any]:
        """Expose provider/model capabilities for transparent routing decisions."""

        return build_capability_graph(
            self.config,
            self.health_snapshot(include_history=False),
        )

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
                    "remaining": _remaining_quota_value(health) if health else "unknown",
                    "quota_state": _health_quota_state(health) if health else "unknown",
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
        return self.preflight_policy.skip_reason(agent, request)

    def _preflight_error_type(
        self,
        agent: AgentConfig,
        request: HubRequest,
        reason: str,
    ) -> str | None:
        return self.preflight_policy.error_type(agent, request, reason)

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
        capabilities = agent_capabilities(agent)
        has_tools = _request_has_tools(request) if request is not None else False
        if normalize_provider(agent.provider) == "echo":
            score -= 5000.0
        if request is not None:
            text = request_text(request).lower()
            if has_tools and capabilities.tool_capable:
                score += 18
            if request.stream and capabilities.supports_streaming:
                score += 6
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
            if health.average_tokens_per_second:
                minimum_tps = _routing_float(self.config, "min_tokens_per_second", 2.0)
                if health.average_tokens_per_second < minimum_tps:
                    score -= min(10.0, (minimum_tps - health.average_tokens_per_second) * 2.0)
                else:
                    score += min(3.0, health.average_tokens_per_second / 25.0)
            if health.is_degraded():
                score -= 20.0
            if health.requests_remaining is not None and health.requests_remaining <= 1:
                score -= 25.0
            if (health.quota_exhausted and health.cooldown_deadline() > time.time()) or (
                health.quota_remaining is not None and health.quota_remaining <= 0
            ):
                score -= 100.0
            if request is not None:
                required_tokens = estimate_input_tokens(request) + expected_output_tokens(request, agent)
                if health.tokens_remaining is not None and health.tokens_remaining < required_tokens:
                    score -= 80.0
                elif health.tokens_remaining is not None and health.tokens_remaining < required_tokens * 2:
                    score -= 18.0
            if has_tools and health.tool_call_failure_count:
                score -= min(12.0, health.tool_call_failure_count * 2.0)
            if request is not None and request.stream and capabilities.supports_streaming and health.streaming_tokens_per_second:
                score += min(4.0, health.streaming_tokens_per_second / 25.0)
            if health.tokens_in > 0:
                token_efficiency = health.tokens_out / max(1, health.tokens_in)
                score += min(3.0, token_efficiency)
        else:
            score += 0.7 * 12
            if self.config.enable_load_balancing:
                score += 2.0
        if self._is_on_cooldown(agent.name):
            score -= 100.0
        if _routing_bool(self.config, "free_first", True) and not self.config.free_only and is_free_agent(agent):
            score += 4.0
        if _routing_bool(self.config, "prefer_available_quota", True) and health:
            if health.quota_remaining is not None and health.quota_remaining > 0:
                score += min(3.0, float(health.quota_remaining) / 1000.0)
            if health.requests_remaining is not None and health.requests_remaining > 1:
                score += min(2.0, float(health.requests_remaining) / 100.0)
        if not self.config.free_only and not is_free_agent(agent):
            score -= 2.5
        score += provider_cost_efficiency_score(agent)
        if request is not None:
            if self.config.adaptive_learning_enabled and self.config.adaptive_routing_enabled:
                score += self.adaptive_learning.routing_bonus(
                    agent.name,
                    route=request.route or "",
                    task_type=self._classify_task(request),
                    workflow_pattern=_request_workflow_pattern(request),
                    workflow_role=_request_workflow_role(request),
                )
        evaluation = self.provider_scores.get(agent.name) if isinstance(self.provider_scores, dict) else None
        if isinstance(evaluation, dict):
            try:
                score += float(evaluation.get("overall_score", 0.0)) * 8.0
            except (TypeError, ValueError):
                pass
        return score

    def _performance_failover_reason(
        self,
        *,
        agent: AgentConfig,
        request: HubRequest,
        result: ProviderResult,
        latency_seconds: float,
    ) -> str | None:
        if not _routing_bool(self.config, "auto_failover", True):
            return None
        slow_threshold = _routing_float(self.config, "slow_first_token_timeout_seconds", 20.0)
        if slow_threshold > 0 and latency_seconds > slow_threshold:
            return (
                "Provider response latency exceeded failover threshold: "
                f"{latency_seconds:.2f}s > {slow_threshold:.2f}s"
            )
        minimum_tps = _routing_float(self.config, "min_tokens_per_second", 2.0)
        output_tokens = _result_output_tokens(result)
        if minimum_tps > 0 and output_tokens >= 4 and latency_seconds > 1.0:
            tokens_per_second = output_tokens / latency_seconds
            if tokens_per_second < minimum_tps:
                return (
                    "Provider throughput fell below failover threshold: "
                    f"{tokens_per_second:.2f} tokens/s < {minimum_tps:.2f} tokens/s"
                )
        health = self._health.get(agent.name)
        if health and health.average_latency_seconds and health.success_count >= 2:
            if health.average_latency_seconds > max(slow_threshold, latency_seconds * 2):
                return (
                    "Provider average latency is degraded: "
                    f"{health.average_latency_seconds:.2f}s average"
                )
        return None

    def _record_route_event(self, event_type: str, *, request_id: str, request: HubRequest, **data: Any) -> None:
        self.event_recorder.route(event_type, request_id=request_id, request=request, **data)

    def _record_internal_event(
        self,
        name: str,
        *,
        request_id: str,
        request: HubRequest,
        **data: Any,
    ) -> None:
        self.event_recorder.internal(name, request_id=request_id, request=request, **data)

    def _record_success(
        self,
        agent: AgentConfig,
        latency_seconds: float,
        result: ProviderResult,
        request: HubRequest,
        *,
        failover_attempts: int = 0,
        request_id: str | None = None,
        first_token_latency_seconds: float | None = None,
    ) -> None:
        health = self._health.setdefault(agent.name, ProviderHealth())
        now = time.time()
        health.success_count += 1
        health.total_latency_seconds += max(0.0, latency_seconds)
        health.last_success_at = now
        health.last_checked_at = now
        health.last_request_source = request_source(request)
        health.last_route = request.route or ""
        health.last_request_started_at = max(0.0, now - max(0.0, latency_seconds))
        health.last_first_token_latency_seconds = max(
            0.0,
            float(first_token_latency_seconds)
            if first_token_latency_seconds is not None
            else float(_provider_stream_metadata(result.raw).get("first_token_latency_seconds") or 0.0),
        )
        health.last_total_latency_seconds = max(0.0, latency_seconds)
        health.last_finish_reason = str(result.finish_reason or "")
        health.last_failover_attempts = max(0, int(failover_attempts))
        health.rate_limited = False
        health.quota_exhausted = False
        tokens_in = _usage_int(result.usage, "prompt_tokens", "input_tokens")
        tokens_out = _usage_int(result.usage, "completion_tokens", "output_tokens")
        if tokens_out <= 0:
            tokens_out = _result_output_tokens(result)
        health.last_input_tokens = tokens_in
        health.last_output_tokens = tokens_out
        health.last_tokens_per_second = tokens_out / latency_seconds if latency_seconds > 0 and tokens_out > 0 else 0.0
        health.tokens_in += tokens_in
        health.tokens_out += tokens_out
        if latency_seconds > 0 and tokens_out > 0:
            health.total_tokens_per_second += tokens_out / latency_seconds
            health.tokens_per_second_sample_count += 1
        if request.stream and latency_seconds > 0 and tokens_out > 0:
            health.total_streaming_tokens_per_second += tokens_out / latency_seconds
            health.streaming_sample_count += 1
        _apply_agent_capabilities(health, agent)
        _apply_provider_metadata(
            health,
            _provider_metadata_from_raw(result.raw),
            agent=agent,
        )
        health.last_context_compaction_usage = _context_usage(request)
        health.quota_state = _health_quota_state(health)
        self._save_provider_health()
        self._record_adaptive_outcome(
            request_id=request_id,
            request=request,
            agent=agent,
            model=result.model or agent.model,
            success=True,
            latency_seconds=latency_seconds,
            failover_attempts=failover_attempts,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            estimated_cost_usd=estimate_known_cost_usd(
                agent,
                input_tokens=tokens_in,
                output_tokens=tokens_out,
            ),
            final=True,
        )

    def _record_failure(
        self,
        agent: AgentConfig,
        *,
        error_type: str = "",
        message: str = "",
        unavailable_until: float | None = None,
        status_code: int | None = None,
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
        request: HubRequest | None = None,
        routing_mode: str | None = None,
        failover_attempts: int = 0,
    ) -> None:
        health = self._health.setdefault(agent.name, ProviderHealth())
        now = time.time()
        health.failure_count += 1
        health.last_failure_at = now
        health.last_checked_at = now
        if request is not None:
            usage = _context_usage(request)
            health.last_request_source = request_source(request)
            health.last_route = request.route or ""
            health.last_request_started_at = now
            health.last_input_tokens = int(usage.get("estimated_input_tokens") or estimate_input_tokens(request))
            health.last_output_tokens = 0
            health.last_context_compaction_usage = usage
        health.last_total_latency_seconds = 0.0
        health.last_tokens_per_second = 0.0
        health.last_finish_reason = ""
        health.last_failover_attempts = max(0, int(failover_attempts))
        normalized_error_type = _canonical_error_type(error_type)
        if normalized_error_type == "provider_unavailable" and (
            "timed out" in message.lower() or "timeout" in message.lower()
        ):
            health.timeout_count += 1
        if unavailable_until is not None:
            health.unavailable_until = max(health.unavailable_until, unavailable_until)
            health.cooldown_until = max(health.cooldown_until, unavailable_until)
        if normalized_error_type:
            health.last_error_type = normalized_error_type
        if message:
            health.last_error_message = message[:500]
        if (request is not None and request.stream) or "stream" in normalized_error_type:
            health.stream_interruption_count += 1
        health.rate_limited = normalized_error_type == "temporary_rate_limit"
        if normalized_error_type == "quota_exhausted":
            health.quota_exhausted = True
        _apply_agent_capabilities(health, agent)
        _apply_provider_metadata(health, metadata or {}, agent=agent)
        health.quota_state = _health_quota_state(health)
        health.failover_events.append(
            {
                "time": now,
                "agent": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "reason": message[:500],
                "status_code": status_code,
                "error_type": normalized_error_type,
                "unavailable_until": unavailable_until,
            }
        )
        health.failover_events = health.failover_events[-MAX_FAILOVER_HISTORY:]
        self._save_provider_health()
        if request_id is not None and request is not None:
            self._record_internal_event(
                PROVIDER_FAILED,
                request_id=request_id,
                request=request,
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
                routing_mode=routing_mode,
                error_type=normalized_error_type,
                message=message,
                status_code=status_code,
                unavailable_until=unavailable_until,
                failure_count=health.failure_count,
                degraded=health.is_degraded(),
                retryable=unavailable_until is not None,
                metadata=metadata or {},
            )
        self._record_adaptive_outcome(
            request_id=request_id,
            request=request,
            agent=agent,
            model=agent.model,
            success=False,
            latency_seconds=None,
            failover_attempts=failover_attempts,
            input_tokens=health.last_input_tokens,
            output_tokens=0,
            estimated_cost_usd=estimate_known_cost_usd(
                agent,
                input_tokens=health.last_input_tokens,
                output_tokens=0,
            ),
            error_type=normalized_error_type,
            final=False,
        )

    def record_tool_result(self, agent_name: str, ok: bool) -> None:
        """Record whether an agent-produced tool call completed successfully."""

        health = self._health.setdefault(agent_name, ProviderHealth())
        if ok:
            health.tool_call_success_count += 1
        else:
            health.tool_call_failure_count += 1
        health.last_checked_at = time.time()
        self._save_provider_health()

    def _record_adaptive_outcome(
        self,
        *,
        request_id: str | None,
        request: HubRequest | None,
        agent: AgentConfig,
        model: str,
        success: bool,
        latency_seconds: float | None,
        failover_attempts: int,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_usd: float | None,
        error_type: str | None = None,
        final: bool = False,
    ) -> None:
        if request is None:
            return
        if not self.config.adaptive_learning_enabled:
            return
        try:
            self.adaptive_learning.record_outcome(
                request_id=request_id,
                route=request.route or "",
                task_type=self._classify_task(request),
                workflow_pattern=_request_workflow_pattern(request),
                workflow_role=_request_workflow_role(request),
                agent=agent,
                model=model,
                success=success,
                latency_seconds=latency_seconds,
                failover_attempts=failover_attempts,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=estimated_cost_usd,
                error_type=error_type,
                retry_count=failover_attempts,
                final=final,
            )
        except Exception:
            return

    def _load_provider_health(self) -> dict[str, ProviderHealth]:
        path = self._health_path
        if not path.exists():
            return {}
        now = time.time()
        health_by_agent: dict[str, ProviderHealth] = {}
        for name, health in self.health_tracker.load().items():
            if not isinstance(health.failover_events, list):
                health.failover_events = []
            last_seen = max(health.last_checked_at, health.last_success_at, health.last_failure_at)
            if last_seen and last_seen < now - HEALTH_STALE_SECONDS and health.cooldown_deadline() <= now:
                continue
            health_by_agent[name] = health
        return health_by_agent

    def _save_provider_health(self) -> None:
        try:
            self.health_tracker.save(self._health)
        except OSError:
            return

    def _cooldown_seconds(self, agent: AgentConfig, error: ProviderError) -> float:
        if error.cooldown_seconds is not None:
            return max(0.0, error.cooldown_seconds)
        error_type = _canonical_error_type(error.error_type)
        if error_type == "quota_exhausted":
            return max(agent.cooldown_seconds, _routing_float(self.config, "cooldown_quota_seconds", float(self.config.quota_cooldown_seconds)))
        if error_type == "temporary_rate_limit":
            return max(agent.cooldown_seconds, _routing_float(self.config, "cooldown_rate_limit_seconds", float(self.config.rate_limit_cooldown_seconds)))
        if error_type == "provider_overloaded":
            return max(agent.cooldown_seconds, _routing_float(self.config, "cooldown_overload_seconds", 60.0))
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


def _routing_value(config: HubConfig, key: str, default: Any) -> Any:
    routing = getattr(config, "routing", {}) or {}
    if isinstance(routing, dict) and routing.get(key) not in (None, ""):
        return routing[key]
    return default


def _routing_bool(config: HubConfig, key: str, default: bool) -> bool:
    value = _routing_value(config, key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _routing_int(config: HubConfig, key: str, default: int) -> int:
    try:
        return max(1, int(_routing_value(config, key, default)))
    except (TypeError, ValueError):
        return default


def _routing_float(config: HubConfig, key: str, default: float) -> float:
    try:
        return max(0.0, float(_routing_value(config, key, default)))
    except (TypeError, ValueError):
        return default


def _canonical_error_type(error_type: str | None) -> str:
    if not error_type:
        return ""
    return ERROR_TYPE_ALIASES.get(error_type, error_type)


def _request_is_cline(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    text = " ".join(
        str(value or "").lower()
        for value in (
            raw.get("source"),
            raw.get("client"),
            raw.get("client_name"),
            metadata.get("source"),
            metadata.get("client"),
            metadata.get("client_name"),
            metadata.get("user_agent"),
            metadata.get("client_user_agent"),
            metadata.get("cline_version"),
        )
    )
    return "cline" in text


def _compatibility_reductions_enabled(config: HubConfig, request: HubRequest, key: str) -> bool:
    mode = getattr(config, "compatibility_mode", {}) or {}
    if not isinstance(mode, dict) or not mode.get(key):
        return False
    if _request_is_cline(request):
        return True
    return bool(getattr(config, "force_compatibility_streaming", False))


def _context_cap(config: HubConfig, request: HubRequest, agent: AgentConfig) -> int:
    request_cap = _request_option(request, "max_context_tokens")
    if request_cap is not None:
        try:
            return max(1_000, int(request_cap))
        except (TypeError, ValueError):
            pass
    configured = getattr(config, "max_context_tokens", None)
    if configured:
        return max(1_000, int(configured))
    mode = getattr(config, "compatibility_mode", {}) or {}
    if isinstance(mode, dict) and (_request_is_cline(request) or getattr(config, "force_compatibility_streaming", False)):
        if mode.get("max_context_tokens") in (None, "", "auto"):
            return max(1_000, int(agent.context_window or config.agent_context_budget_tokens))
        try:
            return max(1_000, int(mode.get("max_context_tokens") or 12_000))
        except (TypeError, ValueError):
            return max(1_000, int(agent.context_window or config.agent_context_budget_tokens))
    return max(1_000, int(agent.context_window or config.agent_context_budget_tokens))


def _compress_messages_for_budget(
    messages: list[dict[str, Any]],
    budget: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    compacted = [_compact_repo_context_message(message) for message in messages]
    if estimate_message_tokens(compacted) <= budget:
        warnings.append("repo_context_compacted")
        return compacted, warnings

    protected: list[dict[str, Any]] = []
    tail: list[dict[str, Any]] = []
    for index, message in enumerate(compacted):
        if is_protected_context_message(message, recent=index >= max(0, len(compacted) - 8)):
            protected.append(message)
        elif index >= max(0, len(compacted) - 6):
            tail.append(message)
    reduced = _dedupe_messages([*protected, *tail])
    while len(reduced) > 1 and estimate_message_tokens(reduced) > budget:
        removed = False
        for index, message in enumerate(reduced):
            if not is_protected_context_message(message, recent=index >= max(0, len(reduced) - 8)):
                reduced.pop(index)
                removed = True
                break
        if not removed:
            break
    if estimate_message_tokens(reduced) > budget:
        reduced = [_truncate_message_content(message, 2_000) for message in reduced]
    reduced, summary_added = _with_compaction_summary(compacted, reduced, budget)
    if summary_added:
        warnings.append("internal_summary_note_added")
    warnings.append("messages_compacted")
    return reduced, warnings


def _compact_repo_context_message(message: dict[str, Any]) -> dict[str, Any]:
    if not message.get("agent_hub_repo_context"):
        return message
    copied = dict(message)
    text = content_to_text(copied.get("content"))
    if len(text) > 2_500:
        copied["content"] = text[:2_500].rstrip() + "\n[Context reduced for provider compatibility]"
    return copied


def _truncate_message_content(message: dict[str, Any], maximum: int) -> dict[str, Any]:
    copied = dict(message)
    text = content_to_text(copied.get("content"))
    if len(text) > maximum:
        copied["content"] = text[:maximum].rstrip() + "\n[Context reduced for provider compatibility]"
    return copied


def _with_compaction_summary(
    original: list[dict[str, Any]],
    reduced: list[dict[str, Any]],
    budget: int,
) -> tuple[list[dict[str, Any]], bool]:
    if len(reduced) >= len(original):
        return reduced, False
    kept_signatures = {
        json.dumps(message, sort_keys=True, ensure_ascii=False, default=str)
        for message in reduced
    }
    dropped = [
        message
        for message in original
        if json.dumps(message, sort_keys=True, ensure_ascii=False, default=str) not in kept_signatures
    ]
    if not dropped:
        return reduced, False
    dropped_tokens = estimate_message_tokens(dropped)
    note = {
        "role": "system",
        "content": (
            "Agent Hub context compaction note: older low-signal messages were compressed "
            f"to fit the selected provider. Dropped approximately {dropped_tokens} tokens. "
            "Preserved system/developer instructions, latest user request, protected tool state, "
            "task progress, TODOs, active files, and recent code context when present."
        ),
        "agent_hub_context_summary": True,
    }
    insert_at = 0
    while insert_at < len(reduced) and str(reduced[insert_at].get("role") or "").lower() in {"system", "developer"}:
        insert_at += 1
    with_note = [*reduced[:insert_at], note, *reduced[insert_at:]]
    while len(with_note) > 1 and estimate_message_tokens(with_note) > budget:
        removed = False
        for index, message in enumerate(with_note):
            if message is note:
                continue
            if not is_protected_context_message(message, recent=index >= max(0, len(with_note) - 8)):
                with_note.pop(index)
                removed = True
                break
        if not removed:
            break
    if estimate_message_tokens(with_note) <= budget:
        return with_note, True
    return reduced, False


def _dedupe_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for message in messages:
        signature = json.dumps(message, sort_keys=True, ensure_ascii=False, default=str)
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(message)
    return deduped


def _minimal_tool_schema(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name") or "")
    parameters = spec.get("parameters") if isinstance(spec.get("parameters"), dict) else {}
    properties = parameters.get("properties") if isinstance(parameters.get("properties"), dict) else {}
    minimal_properties = {
        key: {"type": value.get("type", "string")} if isinstance(value, dict) else {"type": "string"}
        for key, value in properties.items()
    }
    return {
        "name": name,
        "description": str(spec.get("description") or "")[:160],
        "parameters": {
            "type": parameters.get("type", "object"),
            "properties": minimal_properties,
            **({"required": parameters["required"]} if isinstance(parameters.get("required"), list) else {}),
        },
    }


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
        "context_window": agent.context_window,
        "max_output_tokens": agent.max_tokens or health.get("max_output_tokens"),
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
    metadata: dict[str, Any] = {}
    quota = provider_metadata.get("quota")
    if isinstance(quota, dict):
        metadata.update(quota)
    limits = provider_metadata.get("limits")
    if isinstance(limits, dict):
        metadata.update(
            {
                key: limits[key]
                for key in ("context_window", "max_output_tokens")
                if key in limits
            }
        )
    return metadata


def _provider_stream_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    metadata = raw.get("agent_hub_stream")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _apply_agent_capabilities(health: ProviderHealth, agent: AgentConfig) -> None:
    for name, value in agent_capabilities(agent).to_health_fields().items():
        setattr(health, name, value)


def _apply_provider_metadata(
    health: ProviderHealth,
    metadata: dict[str, Any],
    *,
    agent: AgentConfig,
) -> None:
    _apply_agent_capabilities(health, agent)
    if not metadata:
        return
    _assign_float(health, "quota_remaining", metadata.get("quota_remaining"))
    _assign_int(health, "requests_remaining", metadata.get("requests_remaining"))
    _assign_int(health, "tokens_remaining", metadata.get("tokens_remaining"))
    _assign_float(health, "credits_remaining", metadata.get("credits_remaining"))
    _assign_float(health, "rate_limit_reset_at", metadata.get("rate_limit_reset_at"))
    _assign_int(health, "context_window", metadata.get("context_window"))
    _assign_int(health, "max_output_tokens", metadata.get("max_output_tokens"))
    if health.quota_remaining is not None:
        health.quota_exhausted = health.quota_remaining <= 0
    if health.credits_remaining is not None and health.credits_remaining > 0:
        health.quota_exhausted = False
    if health.credits_remaining is not None and health.credits_remaining <= 0:
        health.quota_exhausted = True
    if health.requests_remaining is not None and health.requests_remaining <= 0:
        health.rate_limited = True
    elif health.requests_remaining is not None and health.requests_remaining > 0:
        health.rate_limited = False
    if health.rate_limit_reset_at is not None and health.rate_limit_reset_at <= time.time():
        health.rate_limited = False
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
    health.quota_state = _health_quota_state(health)


def _health_quota_state(health: ProviderHealth) -> str:
    now = time.time()
    if health.quota_exhausted and health.cooldown_deadline() > now:
        return "exhausted"
    if health.rate_limited and (health.cooldown_deadline() > now or health.rate_limit_reset_at):
        return "rate_limited"
    if health.requests_remaining is not None and health.requests_remaining <= 0:
        return "rate_limited"
    if health.quota_remaining is not None and health.quota_remaining <= 0:
        return "exhausted"
    if health.credits_remaining is not None and health.credits_remaining <= 0:
        return "exhausted"
    if any(
        value is not None
        for value in (
            health.quota_remaining,
            health.requests_remaining,
            health.tokens_remaining,
            health.credits_remaining,
        )
    ):
        return "available"
    return "unknown"


def _remaining_quota_value(health: ProviderHealth) -> int | float | str:
    values = [
        value
        for value in (
            health.quota_remaining,
            health.requests_remaining,
            health.tokens_remaining,
            health.credits_remaining,
        )
        if value is not None
    ]
    if not values:
        return "unknown"
    return min(values)


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


def _context_usage(request: HubRequest) -> dict[str, Any]:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw, dict) else None
    usage = hub.get("context_usage") if isinstance(hub, dict) else None
    return dict(usage) if isinstance(usage, dict) else {}


def _request_workflow_pattern(request: HubRequest) -> str:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    for value in (
        hub.get("workflow_pattern"),
        raw.get("workflow_pattern"),
        raw.get("workflow_selection"),
        raw.get("mode") if raw.get("mode") == "group-agent" else None,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _request_workflow_role(request: HubRequest) -> str:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    for value in (
        hub.get("workflow_role"),
        hub.get("role"),
        raw.get("workflow_role"),
        raw.get("team_agent_role"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _continuation_request(request: HubRequest, partial_text: str, reason: str) -> HubRequest:
    partial = str(partial_text or "").strip()
    if not partial:
        return request
    raw = dict(request.raw or {})
    hub = dict(raw.get("agent_hub") or {})
    hub["continuation_after_output_limit"] = True
    hub["continuation_reason"] = reason
    raw["agent_hub"] = hub
    messages = [
        *[dict(message) for message in request.messages],
        {
            "role": "assistant",
            "content": partial,
            "agent_hub_partial_response": True,
        },
        {
            "role": "user",
            "content": (
                "Continue from the exact point where the previous response stopped. "
                "Do not repeat completed text. Preserve the requested format, JSON/schema "
                "constraints, tool-call state, and task context."
            ),
            "agent_hub_continuation_instruction": True,
        },
    ]
    return replace(request, messages=messages, raw=raw, record_session=False)


def _merge_continuation_result(
    prefix: str,
    result: ProviderResult,
    *,
    model: str,
    raw_reason: str,
) -> ProviderResult:
    suffix = _trim_text_overlap(str(prefix or ""), result.text or "")
    raw = dict(result.raw or {})
    metadata = dict(raw.get("agent_hub") or {})
    metadata["continued_from_partial"] = True
    metadata["continuation_reason"] = raw_reason
    metadata["deduplicated_prefix_chars"] = max(0, len(result.text or "") - len(suffix))
    raw["agent_hub"] = metadata
    usage = dict(result.usage or {})
    usage.setdefault("continuation_output_tokens", max(1, len(suffix) // 4) if suffix else 0)
    return ProviderResult(
        text=f"{prefix}{suffix}",
        model=model,
        raw=raw,
        usage=usage,
        finish_reason=result.finish_reason,
        citations=result.citations,
        search_results=result.search_results,
        images=result.images,
        related_questions=result.related_questions,
    )


def _trim_text_overlap(prefix: str, suffix: str) -> str:
    if not prefix or not suffix:
        return suffix
    max_overlap = min(len(prefix), len(suffix), 4000)
    for size in range(max_overlap, 0, -1):
        if prefix[-size:] == suffix[:size]:
            return suffix[size:]
    stripped_prefix = prefix.rstrip()
    stripped_suffix = suffix.lstrip()
    if stripped_prefix and stripped_suffix and stripped_suffix.startswith(stripped_prefix[-min(len(stripped_prefix), 400):]):
        marker = stripped_prefix[-min(len(stripped_prefix), 400):]
        return stripped_suffix[len(marker):]
    return suffix


def _next_candidate_name(candidates: list[AgentConfig], current: AgentConfig) -> str | None:
    try:
        index = next(
            position for position, agent in enumerate(candidates) if agent.name == current.name
        )
    except StopIteration:
        return None
    for agent in candidates[index + 1 :]:
        if agent.enabled:
            return agent.name
    return None


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


def _result_output_tokens(result: ProviderResult) -> int:
    tokens = _usage_int(result.usage, "completion_tokens", "output_tokens")
    if tokens > 0:
        return tokens
    return max(0, len(result.text or "") // 4)


def _adaptive_route_reason(candidate_scores: list[dict[str, Any]]) -> str:
    if not candidate_scores:
        return ""
    selected = candidate_scores[0]
    adaptive = selected.get("adaptive")
    if not isinstance(adaptive, dict) or not adaptive.get("active"):
        return ""
    bonus = _optional_float(adaptive.get("adaptive_bonus")) or 0.0
    if abs(bonus) < 0.05:
        return ""
    scorecard = adaptive.get("scorecard") if isinstance(adaptive.get("scorecard"), dict) else {}
    success_rate = _optional_float(scorecard.get("success_rate")) or 0.0
    attempts = int(adaptive.get("attempts", 0) or 0)
    scope = str(adaptive.get("scope") or "adaptive")
    direction = "boosted" if bonus > 0 else "penalized"
    return (
        f"Adaptive history {direction} {selected.get('agent')} by {bonus:+.2f} "
        f"from {scope} data ({attempts} sample(s), {success_rate * 100:.0f}% success)."
    )


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
            "Provider requires approval. Set approval_mode=auto or enable "
            f"cline_compatibility_mode for trusted providers. Provider: {latest.agent}. {latest.reason}"
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
        if _canonical_error_type(event.error_type) in {"quota_exhausted", "temporary_rate_limit"}
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
    invalid_events = [event for event in failover if event.error_type == "invalid_provider_response"]
    if invalid_events and len(invalid_events) == len(failover):
        return "invalid_provider_response"
    retryable_events = [event for event in failover if event.retryable and event.error_type]
    if retryable_events and len(retryable_events) == len(failover):
        return _canonical_error_type(retryable_events[-1].error_type)
    return None


def _router_error_category(error_type: str | None) -> str:
    error_type = _canonical_error_type(error_type)
    if error_type in {CONFIGURATION_ERROR, ECHO_DISABLED, NO_TOOL_CAPABLE_MODEL}:
        return ErrorCategory.CONFIGURATION
    if error_type in {"permission_required", "permission_denied"}:
        return ErrorCategory.PERMISSION
    if error_type == "invalid_provider_response":
        return ErrorCategory.VALIDATION
    if error_type == "context_too_large":
        return ErrorCategory.CONTEXT_LIMIT
    if error_type == "output_too_large":
        return ErrorCategory.CONTEXT_LIMIT
    if error_type in {"temporary_rate_limit", "quota_exhausted"}:
        return ErrorCategory.RATE_LIMIT if error_type == "temporary_rate_limit" else ErrorCategory.QUOTA
    if error_type in {"provider_unavailable", "provider_overloaded"}:
        return ErrorCategory.NETWORK
    if error_type == "authentication_error":
        return ErrorCategory.CONFIGURATION
    return ErrorCategory.PROVIDER if error_type else ErrorCategory.UNKNOWN


def _router_user_message(message: str, suggested_fix: str | None) -> str:
    if suggested_fix:
        return f"{message} Suggested fix: {suggested_fix}"
    return message


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


def _classification_text(request: HubRequest) -> str:
    parts = [request.task or "", request.context or ""]
    for message in request.messages:
        if message.get("agent_hub_repo_context"):
            continue
        parts.append(content_to_text(message.get("content")))
    return "\n".join(part for part in parts if part)


def _looks_like_debug_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "debug",
            "failing",
            "failure",
            "traceback",
            "exception",
            "regression",
            "not working",
        )
    )


def _looks_like_review_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "review",
            "audit",
            "check my",
            "critique",
            "risk",
            "security",
            "correctness",
        )
    )


def _looks_like_research_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "research",
            "investigate",
            "find out",
            "compare",
            "summarize",
            "search",
            "evaluate",
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


def _repo_or_tool_task(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub_options = raw.get("agent_hub")
    if isinstance(hub_options, dict) and hub_options.get("enable_builtin_tools") is False:
        return False
    if isinstance(hub_options, dict) and hub_options.get("enable_builtin_tools") is True:
        return True
    return _tool_task_requested(request)


def _tool_task_requested(request: HubRequest) -> bool:
    text = request_text(request).lower()
    return any(
        marker in text
        for marker in (
            "read ",
            "search",
            "file",
            "repo",
            "workspace",
            "run ",
            "command",
            "test",
            "edit",
            "write",
            "debug",
            "refactor",
        )
    )


def _repo_context_useful(request: HubRequest) -> bool:
    if _agent_runner_managed_request(request):
        return False
    route = str(request.route or "").lower()
    if route in {"coding", "local-agent", "agent-hub-coding", "debug", "review", "refactor"}:
        return True
    raw = request.raw if isinstance(request.raw, dict) else {}
    workflow = str(raw.get("workflow") or raw.get("workflow_stage") or "").lower()
    if workflow in {"code", "debug", "review", "refactor"}:
        return True
    return _looks_like_coding_task(request_text(request).lower())


def _agent_runner_managed_request(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    return isinstance(raw.get("agent_hub_runtime"), dict)


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
