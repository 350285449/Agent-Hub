from __future__ import annotations

import json
import random
import time
import uuid
from dataclasses import dataclass, field, fields, replace
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any

from ...adaptive import AdaptiveLearningStore, estimate_known_cost_usd
from ...capabilities import agent_capabilities
from ...config import AgentConfig, HubConfig, agent_allowed_by_cost_policy, is_free_agent, normalize_provider
from ...context import estimate_message_tokens, is_protected_context_message
from ...debug import debug_dir_for_state, provider_debug_context
from ...events import (
    CONTEXT_TRUNCATED,
    PROVIDER_FAILED,
    PROVIDER_SELECTED,
    RouterEventRecorder,
    STREAM_FAILED,
    STREAM_STARTED,
    request_source,
)
from ...evaluation import ProviderScoreStore
from ...mcp import MCPServerRegistry
from ...models import FailoverEvent, HubRequest, HubResponse, ProviderResult, StructuredError
from ...measurement import record_completed_request
from ...payloads import content_to_text, request_text
from ...providers import Provider, ProviderError, create_provider
from ...response_normalization import validate_provider_result
from ...repository import repo_context_for_request
from ...repository_intelligence import (
    RepositoryDNA,
    RepositoryIntelligenceStore,
    build_failure_prediction,
    repository_routing_signal,
)
from ...routing_memory import RoutingMemoryStore, outcome_score
from ...security.provider_permissions import ProviderPermissionPolicy
from ...session_store import SessionStore
from ...streaming import normalize_stream_chunk
from ...token_optimizer import ContextCache, TokenOptimizer
from ...tools import ToolExecutionPipeline, ToolLoopRunner, create_builtin_registry
from ...tool_compatibility import (
    agent_can_emulate_tools,
    normalize_emulated_tool_result,
    prepare_tool_compatibility_request,
    tool_compatibility_mode,
    tool_emulation_can_handle,
)
from ...tools.loop import (
    ToolLoopMetadata,
    merge_tool_loop_metadata,
)
from ..health import (
    ProviderHealth,
    ProviderHealthTracker,
    calculate_provider_score,
    health_state_label,
    provider_cost_efficiency_score,
)
from ..context_preparation import ContextPreparationService
from ..provider_manager import ProviderManager
from ..provider_attempts import ProviderAttemptExecutor, ProviderAttemptHelpers
from ..router_diagnostics import build_capability_graph, build_provider_status
from ..task_classifier import TaskClassifier
from ..routing_policy import (
    CONFIGURATION_ERROR,
    ECHO_DISABLED,
    NO_TOOL_CAPABLE_MODEL,
    RouterPreflightPolicy,
    estimate_input_tokens,
    expected_output_tokens,
    output_token_budget,
    _agent_supports_tools,
    _is_echo_agent,
    _is_local_or_private_agent,
    _request_has_client_tool_specs,
    _request_has_tools,
    _requires_missing_api_key,
    _requires_tool_capable_model,
)
from .fallback_reasons import (
    ERROR_TYPE_ALIASES,
    _canonical_error_type,
    _checked_model_summary,
    _missing_key_names,
    _no_fallback_reason,
    _no_model_available_fix,
    _no_model_available_message,
    _no_tool_capable_fix,
    _no_tool_capable_message,
    _route_error_type,
    _route_status_code,
    _router_error_category,
    _router_user_message,
    _suggested_fix,
)
from .task_signals import (
    _agent_runner_managed_request,
    _classification_text,
    _looks_like_coding_task,
    _looks_like_debug_task,
    _looks_like_reasoning_task,
    _looks_like_research_task,
    _looks_like_review_task,
    _recommendation_reason,
    _repo_context_useful,
    _repo_or_tool_task,
    _tool_task_requested,
)


ProviderFactory = Callable[[AgentConfig], Provider]
HEALTH_STATE_VERSION = 1
HEALTH_STATE_FILE = "provider_health.json"
HEALTH_STALE_SECONDS = 7 * 24 * 60 * 60
MAX_FAILOVER_HISTORY = 50
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
    task_category: str | None = None
    language: str = "unknown"
    framework: str = "unknown"
    complexity: str = "low"
    risk: str = "low"
    context_estimate: str = "small"
    selected_workflow: str = ""
    permission_requirements: list[str] = field(default_factory=list)
    routing_reasons: list[str] = field(default_factory=list)
    memory_adjustments: list[dict[str, Any]] = field(default_factory=list)
    estimated_input_tokens: int = 0
    candidate_scores: list[dict[str, Any]] = field(default_factory=list)
    task_classification: dict[str, Any] = field(default_factory=dict)
    repository_dna: dict[str, Any] = field(default_factory=dict)
    workspace_memory: dict[str, Any] = field(default_factory=dict)
    failure_prediction: dict[str, Any] = field(default_factory=dict)
    tournament_plan: dict[str, Any] = field(default_factory=dict)
    escalation_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "selected_agent": self.selected_agent,
            "selected_provider": self.selected_provider,
            "selected_model": self.selected_model,
            "routing_mode": self.routing_mode,
            "task_type": self.task_type,
            "task_category": self.task_category,
            "language": self.language,
            "framework": self.framework,
            "complexity": self.complexity,
            "risk": self.risk,
            "context_estimate": self.context_estimate,
            "selected_workflow": self.selected_workflow,
            "reason": self.reason,
            "routing_reasons": list(self.routing_reasons),
            "fallback_chain": list(self.fallback_chain),
            "fallback_candidates": list(self.fallback_chain[1:]),
            "fallback_rejections": _fallback_rejections(self.candidate_scores),
            "memory_adjustments": list(self.memory_adjustments),
            "permission_requirements": list(self.permission_requirements),
            "estimated_input_tokens": self.estimated_input_tokens,
        }
        if self.task_classification:
            data["task_classification"] = dict(self.task_classification)
        if self.repository_dna:
            data["repository_dna"] = dict(self.repository_dna)
        if self.workspace_memory:
            data["workspace_memory"] = dict(self.workspace_memory)
        if self.failure_prediction:
            data["failure_prediction"] = dict(self.failure_prediction)
        if self.tournament_plan:
            data["tournament_plan"] = dict(self.tournament_plan)
        if self.escalation_plan:
            data["escalation_plan"] = dict(self.escalation_plan)
        if self.candidate_scores:
            data["candidate_scores"] = list(self.candidate_scores)
        data["explanation"] = _routing_decision_explanation(self).to_dict()
        return data


@dataclass(slots=True)
class RoutingDecisionExplanation:
    """Product-facing explanation derived from the existing routing scorecards."""

    summary: str
    selected: dict[str, Any]
    reasons: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    provider_rankings: list[dict[str, Any]] = field(default_factory=list)
    model_rankings: list[dict[str, Any]] = field(default_factory=list)
    adaptive_learning: dict[str, Any] = field(default_factory=dict)
    routing_memory: dict[str, Any] = field(default_factory=dict)
    repository_dna: dict[str, Any] = field(default_factory=dict)
    cost_savings: dict[str, Any] = field(default_factory=dict)
    context_optimization: dict[str, Any] = field(default_factory=dict)
    lifecycle: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.routing_decision_explanation",
            "summary": self.summary,
            "selected": dict(self.selected),
            "reasons": list(self.reasons),
            "rejected": list(self.rejected),
            "provider_rankings": list(self.provider_rankings),
            "model_rankings": list(self.model_rankings),
            "adaptive_learning": dict(self.adaptive_learning),
            "routing_memory": dict(self.routing_memory),
            "repository_dna": dict(self.repository_dna),
            "cost_savings": dict(self.cost_savings),
            "context_optimization": dict(self.context_optimization),
            "lifecycle": list(self.lifecycle),
        }


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
        self._state_lock = RLock()
        self.task_classifier = TaskClassifier(config.workspace_dir)
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
        self.context_preparation = ContextPreparationService(
            config,
            tool_registry=self.tool_registry,
            has_tool_capable_candidate=self._has_tool_capable_candidate,
            repo_context_provider=repo_context_for_request,
        )
        self.tool_pipeline = ToolExecutionPipeline(self.tool_registry)
        self.tool_loop_runner = ToolLoopRunner(
            config=config,
            registry=self.tool_registry,
            pipeline=self.tool_pipeline,
            chat_provider=self._tool_loop_chat,
            record_tool_result=self.record_tool_result,
            record_event=self._record_route_event,
        )
        self.provider_score_store = ProviderScoreStore(config.state_dir)
        self.provider_scores = self.provider_score_store.load()
        self.adaptive_learning = AdaptiveLearningStore(config.state_dir)
        self.routing_memory = RoutingMemoryStore.from_config(config)
        self.repository_intelligence = RepositoryIntelligenceStore.from_config(config)
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

        for index, agent in enumerate(candidates):
            if self._should_skip_cooldown_candidate(candidates, index, effective_request):
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
            if tool_emulation_can_handle(self.config, effective_request) and not _agent_supports_tools(agent):
                failover.append(
                    FailoverEvent(
                        agent=agent.name,
                        provider=agent.provider,
                        model=agent.model,
                        reason="Tool compatibility emulation requires buffered compatibility streaming.",
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
        if tool_emulation_can_handle(self.config, request) and not _agent_supports_tools(agent):
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
                routing_mode=decision.routing_mode,
                decision=decision,
                failover=failover,
            )
            response = self._response_from_result(
                request_id=request_id,
                request=stream_request,
                agent=agent,
                result=result,
                failover=failover,
                decision=decision,
                latency_seconds=latency,
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
        request = prepare_tool_compatibility_request(self.config, agent, request)
        prepared, usage = self._apply_context_safety_cap(agent, request)
        prepared, limit_usage = self._apply_model_output_limit(agent, prepared, usage)
        if limit_usage.get("output_tokens_adjusted"):
            adjusted_source = replace(
                request,
                max_tokens=prepared.max_tokens,
                raw=prepared.raw,
                metadata=prepared.metadata,
            )
            prepared, usage = self._apply_context_safety_cap(agent, adjusted_source)
        usage.update(limit_usage)
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
        hub = dict(raw.get("agent_hub")) if isinstance(raw.get("agent_hub"), dict) else {}
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

    def _apply_model_output_limit(
        self,
        agent: AgentConfig,
        request: HubRequest,
        usage: dict[str, Any],
    ) -> tuple[HubRequest, dict[str, Any]]:
        estimated_input = int(usage.get("estimated_input_tokens") or estimate_input_tokens(request))
        budget = output_token_budget(
            self.config,
            request,
            agent,
            input_tokens=estimated_input,
            health=self._health.get(agent.name),
        )
        limit_usage = {
            "requested_output_tokens": int(budget.requested),
            "estimated_output_tokens": int(budget.effective),
            "model_output_token_limit": budget.limit,
            "max_tokens_mode": budget.mode,
            "output_tokens_adjusted": bool(budget.adjusted),
        }
        if not budget.adjusted:
            return request, limit_usage

        raw = dict(request.raw) if isinstance(request.raw, dict) else {}
        for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
            if key in raw:
                raw[key] = int(budget.effective)
        hub = dict(raw.get("agent_hub")) if isinstance(raw.get("agent_hub"), dict) else {}
        hub["max_tokens_adjusted"] = {
            "requested": int(budget.requested),
            "effective": int(budget.effective),
            "limit": budget.limit,
            "mode": budget.mode,
            "provider": agent.provider,
            "model": agent.model,
            "context_window": agent.context_window,
        }
        raw["agent_hub"] = hub
        metadata = dict(request.metadata)
        metadata["max_tokens_adjusted"] = hub["max_tokens_adjusted"]
        return replace(
            request,
            max_tokens=int(budget.effective),
            raw=raw,
            metadata=metadata,
        ), limit_usage

    def _chat_with_validation(
        self,
        *,
        request_id: str,
        agent: AgentConfig,
        request: HubRequest,
        decision: RoutingDecision,
    ) -> ProviderResult:
        del decision
        result = normalize_emulated_tool_result(
            request,
            self.provider_manager.chat(agent, request),
        )
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
        result = normalize_emulated_tool_result(
            request,
            self.provider_manager.chat(agent, request),
        )
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
        return self.context_preparation.prepare(request, include_tools=include_tools)

    def _with_repo_context(self, request: HubRequest) -> HubRequest:
        return self.context_preparation.with_repo_context(request)

    def _with_builtin_tool_specs(self, request: HubRequest) -> HubRequest:
        return self.context_preparation.with_builtin_tool_specs(request)

    def _has_tool_capable_candidate(self, request: HubRequest) -> bool:
        names: list[str] = []
        if request.preferred_agent:
            names.append(request.preferred_agent)
        names.extend(self._manual_model_or_provider_agent_names(request))
        names.extend(self._route_names(request))
        return any(
            agent_can_emulate_tools(self.config, agent) or _agent_supports_tools(agent)
            for name in names
            if (agent := self.config.agents.get(name)) is not None
            and agent.enabled
            and (not _strict_free_policy_enabled(self.config) or agent_allowed_by_cost_policy(self.config, agent))
        )

    def _tool_loop_chat(self, agent: AgentConfig, request: HubRequest) -> ProviderResult:
        compatible_request = prepare_tool_compatibility_request(self.config, agent, request)
        return normalize_emulated_tool_result(
            compatible_request,
            self.provider_manager.chat(agent, compatible_request),
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

        classification = self._classify_request(request)
        mode = self._routing_mode(request)
        task_type = classification.task_type
        agents = self._candidate_agent_pool(request, mode=mode)
        selected = agents[0] if agents else None
        candidate_scores = self._routing_candidate_scorecards(request, agents)
        reviewer_signal = self.routing_memory.reviewer_signal(classification)
        selected_workflow = classification.workflow_hint
        if reviewer_signal.get("required") and not selected_workflow:
            selected_workflow = "reviewer_memory_gate"
        reason = self._routing_decision_reason(
            mode=mode,
            task_type=task_type,
            selected=selected,
            request=request,
        )
        adaptive_reason = _adaptive_route_reason(candidate_scores)
        if adaptive_reason and mode != "manual":
            reason = f"{reason} {adaptive_reason}"
        memory_reason = _routing_memory_route_reason(candidate_scores)
        if memory_reason and mode != "manual":
            reason = f"{reason} {memory_reason}"
        token_saver_reason = _token_saver_route_reason(candidate_scores)
        if token_saver_reason and mode != "manual":
            reason = f"{reason} {token_saver_reason}"
        if reviewer_signal.get("reason"):
            reason = f"{reason} {reviewer_signal['reason']}"
        routing_reasons = [reason, *classification.reasons[:8]]
        if memory_reason:
            routing_reasons.append(memory_reason)
        if token_saver_reason:
            routing_reasons.append(token_saver_reason)
        if reviewer_signal.get("reason"):
            routing_reasons.append(str(reviewer_signal["reason"]))
        dna = self._repository_dna()
        workspace_memory = self._workspace_memory()
        if dna is not None:
            routing_reasons.append(f"Repository DNA: {dna.summary}")
        memory_adjustments = [
            {
                "agent": row.get("agent"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "original_routing_score": row.get("original_routing_score"),
                "memory_adjustment": row.get("memory_adjustment"),
                "final_routing_score": row.get("final_routing_score"),
                "summary": (row.get("routing_memory") or {}).get("summary")
                if isinstance(row.get("routing_memory"), dict)
                else "",
            }
            for row in candidate_scores
            if abs(float(row.get("memory_adjustment") or 0.0)) > 0.0001
        ]
        decision = RoutingDecision(
            selected_agent=selected.name if selected else None,
            selected_provider=selected.provider if selected else "",
            selected_model=selected.model if selected else "",
            routing_mode=mode,
            task_type=task_type,
            task_category=classification.task_category,
            language=classification.language,
            framework=classification.framework,
            complexity=classification.complexity,
            risk=classification.risk_level,
            context_estimate=classification.context_estimate,
            selected_workflow=selected_workflow,
            reason=reason,
            routing_reasons=routing_reasons,
            fallback_chain=[agent.name for agent in agents],
            permission_requirements=list(classification.permission_requirements),
            memory_adjustments=memory_adjustments,
            estimated_input_tokens=classification.estimated_input_tokens,
            candidate_scores=candidate_scores,
            task_classification=classification.to_dict(),
            repository_dna=dna.to_dict() if dna is not None else {},
            workspace_memory=workspace_memory,
            tournament_plan=self._tournament_plan(agents, candidate_scores, classification),
            escalation_plan=self._escalation_plan(agents, candidate_scores, classification),
        )
        if getattr(self.config, "failure_prediction_enabled", True):
            decision.failure_prediction = build_failure_prediction(decision=decision, config=self.config)
        return decision

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
        if _strict_free_policy_enabled(self.config):
            agents = [agent for agent in agents if agent_allowed_by_cost_policy(self.config, agent)]
        if request.preferred_agent and agents and agents[0].name == request.preferred_agent:
            return [agents[0], *self._rank_agents_for_mode(agents[1:], request, mode)]
        ranked = self._rank_agents_for_mode(agents, request, mode)
        return self._apply_token_saver_ranking(ranked, request, mode)

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
        return self._classify_request(request).routing_mode

    def _classify_task(self, request: HubRequest) -> str:
        return self._classify_request(request).task_type

    def _classify_request(self, request: HubRequest) -> Any:
        classification = self.task_classifier.classify(request)
        dna = self._repository_dna()
        if dna is None:
            return classification
        reasons = list(classification.reasons)
        reasons.append(f"Repository DNA: {dna.summary}")
        language = classification.language if classification.language != "unknown" else dna.language
        framework = classification.framework
        if (
            framework == "unknown"
            and dna.frameworks
            and classification.language in {"unknown", dna.language}
        ):
            framework = dna.frameworks[0]
        complexity = classification.complexity
        if (
            complexity == "low"
            and dna.testing.lower() == "weak"
            and classification.task_type in {"coding", "debug", "tool_use", "test_generation"}
        ):
            complexity = "medium"
        return replace(
            classification,
            language=language,
            framework=framework,
            complexity=complexity,
            repository_profile_id=dna.profile_id,
            repository_project=dna.project,
            repository_architecture=dna.architecture,
            repository_code_style=dna.code_style,
            repository_testing=dna.testing,
            repository_risk_areas=list(dna.risk_areas),
            reasons=reasons[:12],
        )

    def _repository_dna(self) -> RepositoryDNA | None:
        if not getattr(self.config, "repository_dna_enabled", True):
            return None
        try:
            return self.repository_intelligence.repository_dna()
        except Exception:
            return None

    def _workspace_memory(self) -> dict[str, Any]:
        if not getattr(self.config, "workspace_memory_enabled", True):
            return {}
        try:
            return self.repository_intelligence.workspace_memory()
        except Exception:
            return {}

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
            exploration_order = self._simple_cloud_exploration_order(agents, request)
            if exploration_order is not None:
                return exploration_order
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

    def _simple_cloud_exploration_order(
        self,
        agents: list[AgentConfig],
        request: HubRequest,
    ) -> list[AgentConfig] | None:
        if not agents or not self.config.enable_load_balancing:
            return None
        if not _routing_bool(self.config, "simple_cloud_exploration_enabled", True):
            return None
        if not _request_bool_option(
            request,
            "allow_cloud_exploration",
            "simple_cloud_exploration",
            "free_cloud_offload",
            default=False,
        ):
            return None
        classification = self._classify_request(request)
        if classification.task_type != "simple_explanation" or classification.risk_level != "low":
            return None
        if _request_has_tools(request) or _requires_tool_capable_model(request):
            return None

        codex = _codex_efficiency_reference_agent(agents)
        cloud_candidates = [agent for agent in agents if _free_remote_cloud_agent(agent)]
        if codex is None or not cloud_candidates:
            return None

        codex_score, _codex_samples = self._model_efficiency_score(codex, request, classification)
        if codex_score is None:
            codex_score = _routing_float(self.config, "simple_cloud_codex_baseline_score", 0.82)
        min_relative = _bounded_float(
            _routing_float(self.config, "simple_cloud_min_relative_score", 0.82),
            0.1,
            1.5,
        )
        min_samples = _routing_int(self.config, "simple_cloud_min_samples", 3)
        explore_rate = _bounded_float(
            _routing_float(self.config, "simple_cloud_exploration_rate", 0.35),
            0.0,
            1.0,
        )

        close: list[tuple[AgentConfig, float]] = []
        unknown: list[AgentConfig] = []
        below: list[tuple[AgentConfig, float]] = []
        threshold = codex_score * min_relative
        for agent in cloud_candidates:
            score, samples = self._model_efficiency_score(agent, request, classification)
            if score is None or samples < min_samples:
                unknown.append(agent)
            elif score >= threshold:
                close.append((agent, score))
            else:
                below.append((agent, score))

        selected: AgentConfig | None = None
        if close:
            selected = random.choice([agent for agent, _score in close])
        elif unknown and random.random() < explore_rate:
            selected = random.choice(unknown)

        if selected is None:
            ordered = [
                codex,
                *[agent for agent, _score in sorted(close, key=lambda item: item[1], reverse=True)],
                *unknown,
                *[agent for agent, _score in sorted(below, key=lambda item: item[1], reverse=True)],
            ]
        else:
            ordered = [
                selected,
                *[agent for agent, _score in sorted(close, key=lambda item: item[1], reverse=True) if agent.name != selected.name],
                codex,
                *[agent for agent in unknown if agent.name != selected.name],
                *[agent for agent, _score in sorted(below, key=lambda item: item[1], reverse=True)],
            ]

        return _dedupe_agents([*ordered, *agents])

    def _apply_token_saver_ranking(
        self,
        agents: list[AgentConfig],
        request: HubRequest,
        mode: str,
    ) -> list[AgentConfig]:
        if not agents or not self._token_saver_enabled(request, mode):
            return agents
        classification = self._classify_request(request)
        codex_reference = _codex_efficiency_reference_agent(agents)
        eligible: list[tuple[AgentConfig, dict[str, Any], float]] = []
        for agent in agents:
            if not _token_saver_offload_candidate(agent):
                continue
            signal = self._token_saver_signal(
                agent,
                request,
                classification=classification,
                codex_reference=codex_reference,
            )
            if not signal.get("active"):
                continue
            eligible.append(
                (
                    agent,
                    signal,
                    self._routing_score(
                        agent,
                        request,
                        include_routing_memory=False,
                        include_token_saver=False,
                    ),
                )
            )
        if not eligible:
            return agents
        eligible.sort(
            key=lambda item: (
                -float(item[1].get("confidence", 0.0) or 0.0),
                -float(item[1].get("adjustment", 0.0) or 0.0),
                -float(item[2]),
            )
        )
        return _dedupe_agents([*[agent for agent, _signal, _score in eligible], *agents])

    def _token_saver_enabled(self, request: HubRequest | None, mode: str | None = None) -> bool:
        if not getattr(self.config, "cost_optimizer_enabled", True):
            return False
        if _strict_free_policy_enabled(self.config):
            return False
        if not _routing_bool(self.config, "token_saver_enabled", True):
            return False
        if request is None:
            return False
        if mode == "manual" or request.preferred_agent or self._manual_model_or_provider_agent_names(request):
            return False
        if _privacy_requested(request):
            return False
        return True

    def _token_saver_signal(
        self,
        agent: AgentConfig,
        request: HubRequest,
        *,
        classification: Any | None = None,
        codex_reference: AgentConfig | None = None,
    ) -> dict[str, Any]:
        classification = classification or self._classify_request(request)
        threshold = _bounded_float(
            _routing_float(
                self.config,
                "token_saver_confidence_threshold",
                float(getattr(self.config, "confidence_threshold", 0.72) or 0.72),
            ),
            0.0,
            1.0,
        )
        max_loss = _bounded_float(
            _routing_float(self.config, "token_saver_max_productivity_loss", 0.08),
            0.0,
            1.0,
        )
        enabled = self._token_saver_enabled(request, self._routing_mode(request))
        offload_candidate = _token_saver_offload_candidate(agent)
        confidence, confidence_reasons = self._token_saver_confidence(agent, request, classification)
        reference_confidence = None
        productivity_loss = 0.0
        if codex_reference is not None:
            reference_confidence = self._token_saver_confidence(
                codex_reference,
                request,
                classification,
            )[0]
            productivity_loss = max(0.0, float(reference_confidence) - float(confidence))
        protection_reasons = self._token_saver_protection_reasons(agent, request, classification)
        has_reference = codex_reference is not None
        active = bool(
            enabled
            and has_reference
            and offload_candidate
            and not protection_reasons
            and confidence >= threshold
            and productivity_loss <= max_loss
        )
        if active:
            adjustment = _routing_float(self.config, "token_saver_free_candidate_bonus", 22.0) * confidence
            summary = (
                "Token saver active: free candidate is confident enough and within "
                f"{max_loss:.0%} productivity-loss tolerance."
            )
        elif not enabled:
            adjustment = 0.0
            summary = "Token saver is disabled for this request or routing mode."
        elif not offload_candidate:
            adjustment = 0.0
            summary = "Not a token-saver offload candidate."
        elif not has_reference:
            adjustment = 0.0
            summary = "Token saver inactive: no Codex fallback reference is in this route."
        elif protection_reasons:
            adjustment = 0.0
            summary = "Codex fallback protected: " + "; ".join(protection_reasons[:3]) + "."
        elif confidence < threshold:
            adjustment = 0.0
            summary = f"Confidence {confidence:.2f} is below token-saver threshold {threshold:.2f}."
        else:
            adjustment = 0.0
            summary = (
                f"Estimated productivity loss {productivity_loss:.2f} exceeds "
                f"token-saver tolerance {max_loss:.2f}."
            )
        return {
            "enabled": enabled,
            "active": active,
            "agent": agent.name,
            "provider": agent.provider,
            "model": agent.model,
            "free_candidate": offload_candidate,
            "codex_reference": codex_reference.name if codex_reference is not None else None,
            "confidence": round(confidence, 4),
            "confidence_threshold": round(threshold, 4),
            "reference_confidence": round(reference_confidence, 4) if reference_confidence is not None else None,
            "max_productivity_loss": round(max_loss, 4),
            "estimated_productivity_loss": round(productivity_loss, 4),
            "adjustment": round(adjustment, 3),
            "protection_reasons": protection_reasons,
            "confidence_reasons": confidence_reasons,
            "summary": summary,
        }

    def _token_saver_confidence(
        self,
        agent: AgentConfig,
        request: HubRequest,
        classification: Any,
    ) -> tuple[float, list[str]]:
        capability = _token_saver_task_capability(agent, classification)
        health = self._health.get(agent.name)
        reliability = _bounded_float(health.reliability_score if health else 0.7, 0.0, 1.0)
        outcome_score, outcome_samples = self._model_efficiency_score(agent, request, classification)
        evidence = capability if outcome_score is None else outcome_score
        context_fit = self._token_saver_context_fit(agent, request, classification, health)
        speed = _bounded_float(float(agent.speed_score or 0.5), 0.0, 1.0)
        penalty = _token_saver_task_penalty(classification)
        if health is not None:
            if health.is_degraded():
                penalty += 0.18
            attempts = health.success_count + health.failure_count
            if attempts >= 3 and health.failure_count:
                penalty += min(0.12, health.failure_count / max(1, attempts) * 0.2)
            if health.timeout_count:
                penalty += min(0.10, health.timeout_count * 0.03)
        if _request_has_tools(request) and tool_compatibility_mode(self.config, agent) == "unavailable":
            penalty += 0.22
        confidence = (
            capability * 0.42
            + reliability * 0.24
            + context_fit * 0.14
            + evidence * 0.16
            + speed * 0.04
            - penalty
        )
        reasons = [
            f"capability={capability:.2f}",
            f"reliability={reliability:.2f}",
            f"context_fit={context_fit:.2f}",
        ]
        if outcome_score is not None:
            reasons.append(f"outcomes={outcome_score:.2f}/{outcome_samples} samples")
        if penalty:
            reasons.append(f"risk_penalty={penalty:.2f}")
        return round(_bounded_float(confidence, 0.0, 1.0), 4), reasons

    def _token_saver_context_fit(
        self,
        agent: AgentConfig,
        request: HubRequest,
        classification: Any,
        health: ProviderHealth | None,
    ) -> float:
        output_budget = output_token_budget(
            self.config,
            request,
            agent,
            input_tokens=max(1, int(getattr(classification, "estimated_input_tokens", 0) or 0)),
            health=health,
        )
        required = max(1, int(getattr(classification, "estimated_input_tokens", 0) or 0)) + int(output_budget.effective)
        window = int(agent.context_window or getattr(health, "context_window", 0) or 0)
        if window <= 0:
            return 0.72
        if window >= required * 2:
            return 1.0
        if window >= required:
            return 0.86
        if window >= max(1, required // 2):
            return 0.42
        return 0.15

    def _token_saver_protection_reasons(
        self,
        agent: AgentConfig,
        request: HubRequest,
        classification: Any,
    ) -> list[str]:
        reasons: list[str] = []
        risk = str(getattr(classification, "risk_level", "low") or "low")
        task_type = str(getattr(classification, "task_type", "") or "")
        complexity = str(getattr(classification, "complexity", "low") or "low")
        context_estimate = str(getattr(classification, "context_estimate", "small") or "small")
        if risk in {"high", "critical"} or task_type == "security_sensitive_change":
            reasons.append(f"{risk} risk task")
        if bool(getattr(classification, "reviewer_required", False)):
            reasons.append("reviewer workflow recommended")
        if task_type == "long_context" or context_estimate == "large":
            reasons.append("large-context task")
        if complexity == "high" and task_type not in {"simple_explanation", "documentation"}:
            reasons.append("high-complexity task")
        if _request_has_tools(request) and tool_compatibility_mode(self.config, agent) == "unavailable":
            reasons.append("required tools unavailable")
        health = self._health.get(agent.name)
        if health is not None and health.is_degraded():
            reasons.append("provider health is degraded")
        return reasons

    def _model_efficiency_score(
        self,
        agent: AgentConfig,
        request: HubRequest,
        classification: Any,
    ) -> tuple[float | None, int]:
        scores: list[tuple[float, int]] = []
        row = self.provider_scores.get(agent.name) if isinstance(self.provider_scores, dict) else None
        if isinstance(row, dict):
            task_scores = row.get("task_scores") if isinstance(row.get("task_scores"), dict) else {}
            task_counts = row.get("task_sample_counts") if isinstance(row.get("task_sample_counts"), dict) else {}
            for key in _score_task_aliases(classification):
                if key in task_scores:
                    count = max(1, int(task_counts.get(key, 1) or 1))
                    scores.append((_bounded_float(_optional_float(task_scores.get(key)) or 0.0, 0.0, 1.0), count))
                    break
            else:
                if row.get("overall_score") is not None:
                    scores.append(
                        (
                            _bounded_float(_optional_float(row.get("overall_score")) or 0.0, 0.0, 1.0),
                            max(1, int(row.get("sample_count", 1) or 1)),
                        )
                    )
            if not scores and row.get("overall_score") is not None:
                scores.append(
                    (
                        _bounded_float(_optional_float(row.get("overall_score")) or 0.0, 0.0, 1.0),
                        max(1, int(row.get("sample_count", 1) or 1)),
                    )
                )
        try:
            signal = self.routing_memory.routing_signal(agent, classification)
            attempts = int(signal.get("attempts", 0) or 0)
            memory_score = _optional_float(signal.get("average_outcome_score"))
            if attempts > 0 and memory_score is not None:
                scores.append((_bounded_float(memory_score, 0.0, 1.0), attempts))
        except Exception:
            pass
        health = self._health.get(agent.name)
        if health is not None:
            attempts = int(health.success_count + health.failure_count)
            if attempts > 0:
                scores.append((_bounded_float(health.reliability_score, 0.0, 1.0), attempts))
        if not scores:
            return None, 0
        total_weight = sum(min(12, max(1, samples)) for _score, samples in scores)
        weighted = sum(score * min(12, max(1, samples)) for score, samples in scores) / max(1, total_weight)
        return round(_bounded_float(weighted, 0.0, 1.0), 4), sum(max(0, samples) for _score, samples in scores)

    def _outcome_based_routing_signal(
        self,
        agent: AgentConfig,
        request: HubRequest,
        classification: Any,
    ) -> dict[str, Any]:
        score, samples = self._model_efficiency_score(agent, request, classification)
        health = self._health.get(agent.name)
        average_latency_ms = round(health.average_latency_ms, 2) if health else 0.0
        failure_count = health.failure_count if health else 0
        success_count = health.success_count if health else 0
        return {
            "enabled": bool(
                self.config.adaptive_learning_enabled
                or getattr(self.config, "routing_memory_enabled", True)
            ),
            "score": score,
            "samples": samples,
            "success_count": success_count,
            "failure_count": failure_count,
            "average_latency_ms": average_latency_ms,
            "cost_efficiency_score": round(provider_cost_efficiency_score(agent), 4),
            "summary": (
                f"{agent.name} has {samples} outcome sample(s) for similar "
                f"{classification.task_type} work."
                if samples
                else f"No historical outcome samples for {agent.name} on this task shape yet."
            ),
        }

    def _tournament_plan(
        self,
        agents: list[AgentConfig],
        candidate_scores: list[dict[str, Any]],
        classification: Any,
    ) -> dict[str, Any]:
        enabled = bool(getattr(self.config, "model_tournament_enabled", True))
        max_candidates = max(2, min(4, int(getattr(self.config, "model_tournament_max_candidates", 4) or 4)))
        cheap = [
            row
            for row in candidate_scores
            if row.get("agent")
            and (
                row.get("estimated_cost_usd") in (None, 0)
                or any(agent.name == row.get("agent") and is_free_agent(agent) for agent in agents)
            )
        ][:max_candidates]
        judge = next(
            (
                row
                for row in candidate_scores
                if row.get("agent") not in {item.get("agent") for item in cheap}
            ),
            candidate_scores[0] if candidate_scores else {},
        )
        return {
            "enabled": enabled,
            "task_type": getattr(classification, "task_type", ""),
            "candidate_count": len(cheap),
            "candidates": [
                {
                    "agent": row.get("agent"),
                    "provider": row.get("provider"),
                    "model": row.get("model"),
                    "estimated_cost_usd": row.get("estimated_cost_usd"),
                    "outcome_score": (row.get("outcome_based_routing") or {}).get("score")
                    if isinstance(row.get("outcome_based_routing"), dict)
                    else None,
                }
                for row in cheap
            ],
            "judge": {
                "agent": judge.get("agent"),
                "provider": judge.get("provider"),
                "model": judge.get("model"),
                "mode": "judge-model" if judge else "rule-based",
            },
            "selection_policy": "Judge answers by correctness, file grounding, syntax, testability, cost, and latency.",
        }

    def _escalation_plan(
        self,
        agents: list[AgentConfig],
        candidate_scores: list[dict[str, Any]],
        classification: Any,
    ) -> dict[str, Any]:
        threshold = max(0.0, min(1.0, float(getattr(self.config, "confidence_threshold", 0.72) or 0.72)))
        cheap_first = [
            row.get("agent")
            for row in candidate_scores
            if row.get("agent") and (row.get("estimated_cost_usd") in (None, 0))
        ]
        stronger = [
            row.get("agent")
            for row in candidate_scores
            if row.get("agent") and row.get("agent") not in cheap_first
        ]
        return {
            "enabled": bool(getattr(self.config, "automatic_escalation_enabled", True)),
            "confidence_threshold": threshold,
            "task_type": getattr(classification, "task_type", ""),
            "start": cheap_first[0] if cheap_first else (candidate_scores[0].get("agent") if candidate_scores else None),
            "escalate_to": [name for name in stronger[:3] if name],
            "triggers": [
                "low_confidence_response",
                "empty_or_truncated_output",
                "tests_or_validation_failed",
                "tool_or_syntax_failure",
            ],
        }

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
        classification = self._classify_request(request)
        task_type = classification.task_type
        workflow_pattern = _request_workflow_pattern(request)
        workflow_role = _request_workflow_role(request)
        estimated_input = classification.estimated_input_tokens
        rows: list[dict[str, Any]] = []
        repository_dna = self._repository_dna()
        codex_reference = _codex_efficiency_reference_agent(agents)
        for rank, agent in enumerate(agents[:8], start=1):
            health = self._health.get(agent.name)
            output_budget = output_token_budget(
                self.config,
                request,
                agent,
                input_tokens=estimated_input,
                health=health,
            )
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
            original_routing_score = self._routing_score(
                agent,
                request,
                include_routing_memory=False,
                include_token_saver=False,
            )
            token_saver = self._token_saver_signal(
                agent,
                request,
                classification=classification,
                codex_reference=codex_reference,
            )
            routing_memory = self._routing_memory_signal(
                agent,
                request,
                classification=classification,
            )
            repository_signal = self._repository_routing_signal(
                agent,
                classification,
                repository_dna,
            )
            outcome_signal = self._outcome_based_routing_signal(agent, request, classification)
            memory_adjustment = float(routing_memory.get("adjustment", 0.0) or 0.0)
            token_saver_adjustment = float(token_saver.get("adjustment", 0.0) or 0.0)
            final_routing_score = original_routing_score + memory_adjustment + token_saver_adjustment
            rows.append(
                {
                    "rank": rank,
                    "agent": agent.name,
                    "provider": agent.provider,
                    "provider_type": agent.provider_type or normalize_provider(agent.provider),
                    "model": agent.model,
                    "original_routing_score": round(original_routing_score, 3),
                    "memory_adjustment": round(memory_adjustment, 3),
                    "token_saver_adjustment": round(token_saver_adjustment, 3),
                    "repository_dna_adjustment": round(
                        float(repository_signal.get("adjustment", 0.0) or 0.0),
                        3,
                    ),
                    "final_routing_score": round(final_routing_score, 3),
                    "routing_score": round(final_routing_score, 3),
                    "why": _recommendation_reason(agent, text=request_text(request), prefer=None, index=rank - 1),
                    "task_classification": classification.to_dict(),
                    "estimated_input_tokens": estimated_input,
                    "estimated_output_tokens": int(output_budget.effective),
                    "estimated_cost_usd": estimate_known_cost_usd(
                        agent,
                        input_tokens=estimated_input,
                        output_tokens=int(output_budget.effective),
                    ),
                    "adaptive": adaptive,
                    "token_saver": token_saver,
                    "routing_memory": routing_memory,
                    "repository_dna": repository_signal,
                    "outcome_based_routing": outcome_signal,
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
            if _strict_free_policy_enabled(self.config):
                manual_names = [
                    *([request.preferred_agent] if request.preferred_agent else []),
                    *self._manual_model_or_provider_agent_names(request),
                ]
                blocked = [
                    name
                    for name in manual_names
                    if (agent := self.config.agents.get(name)) is not None
                    and not agent_allowed_by_cost_policy(self.config, agent)
                ]
                if blocked and selected.name not in blocked:
                    return (
                        "Strict free-model policy blocked the manual non-free preference "
                        "and selected the next eligible fallback candidate."
                    )
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
        classification = self._classify_request(request)
        if classification.task_type == "security_sensitive_change":
            return (
                "Security-sensitive workspace change detected; selected a coding/review-capable "
                "candidate with permission gates active."
            )
        if classification.task_type == "simple_explanation":
            return "Simple explanation request; selected a cheaper fast candidate when available."
        if classification.repository_context_needed:
            return (
                f"{classification.reason_sentence()} Selected {selected.name} because its "
                "capabilities best match the workspace-aware task."
            )
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
        latency_seconds: float | None = None,
    ) -> HubResponse:
        raw = result.raw
        if tool_loop_metadata is not None and (
            tool_loop_metadata.tool_calls or tool_loop_metadata.tool_results
        ):
            raw = merge_tool_loop_metadata(raw if isinstance(raw, dict) else {}, tool_loop_metadata)
        if self.config.expose_routing_details and isinstance(raw, dict):
            raw = dict(raw)
            agent_metadata = dict(raw.get("agent_hub")) if isinstance(raw.get("agent_hub"), dict) else {}
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
            agent_metadata["routing_summary"] = _routing_transparency_metadata(
                agent=agent,
                result=result,
                failover=failover,
                decision=decision,
                latency_seconds=latency_seconds,
            )
            agent_metadata["confidence"] = self._confidence_score(
                request=request,
                agent=agent,
                result=result,
                failover=failover,
                latency_seconds=latency_seconds,
            )
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
            related_questions=result.related_questions,
        )

    def _confidence_score(
        self,
        *,
        request: HubRequest,
        agent: AgentConfig,
        result: ProviderResult,
        failover: list[FailoverEvent],
        latency_seconds: float | None = None,
    ) -> dict[str, Any]:
        score = 0.86
        reasons: list[str] = []
        text = str(result.text or "").strip()
        if not text:
            score -= 0.72
            reasons.append("empty_response")
        if _token_limit_finish_reason(result.finish_reason):
            score -= 0.32
            reasons.append("output_limit_finish")
        lowered = text.lower()
        if any(marker in lowered for marker in ("i cannot access", "i can't access", "as an ai language model")):
            score -= 0.18
            reasons.append("capability_disclaimer")
        if len(text) < 40 and self._classify_task(request) in {"coding", "debug", "test_generation"}:
            score -= 0.25
            reasons.append("too_short_for_coding_task")
        if "```" in text and text.count("```") % 2:
            score -= 0.12
            reasons.append("unclosed_code_block")
        if failover:
            score -= min(0.16, len(failover) * 0.04)
            reasons.append("fallbacks_used")
        if latency_seconds is not None and latency_seconds > 45:
            score -= 0.08
            reasons.append("slow_response")
        if result.finish_reason in {"error", "failed"}:
            score -= 0.5
            reasons.append("error_finish_reason")
        confidence = round(_bounded_float(score, 0.0, 1.0), 4)
        threshold = _bounded_float(float(getattr(self.config, "confidence_threshold", 0.72) or 0.72), 0.0, 1.0)
        return {
            "score": confidence,
            "threshold": threshold,
            "level": "high" if confidence >= 0.82 else "medium" if confidence >= threshold else "low",
            "should_escalate": bool(
                getattr(self.config, "automatic_escalation_enabled", True)
                and confidence < threshold
                and any(
                    reason in reasons
                    for reason in (
                        "empty_response",
                        "output_limit_finish",
                        "error_finish_reason",
                        "too_short_for_coding_task",
                    )
                )
            ),
            "reasons": reasons,
            "agent": agent.name,
            "model": result.model or agent.model,
        }

    def _is_on_cooldown(self, agent_name: str) -> bool:
        return self._cooldown_until(agent_name) > time.time()

    def _cooldown_until(self, agent_name: str) -> float:
        with self._state_lock:
            health = self._health.get(agent_name)
            return max(
                self._cooldowns.get(agent_name, 0.0),
                health.cooldown_deadline() if health else 0.0,
            )

    def _should_skip_cooldown_candidate(
        self,
        candidates: list[AgentConfig],
        index: int,
        request: HubRequest | None = None,
    ) -> bool:
        agent = candidates[index]
        if not self._is_on_cooldown(agent.name):
            return False
        for candidate in candidates[index + 1 :]:
            if self._is_on_cooldown(candidate.name):
                continue
            if request is not None:
                if self._preflight_skip_reason(candidate, request):
                    continue
                permission = self._provider_permission_decision(candidate, request)
                if permission is not None and not permission.allowed:
                    continue
            return True
        return False

    def cooldown_agent(self, agent_name: str, seconds: float | None = None) -> None:
        agent = self.config.agents.get(agent_name)
        duration = seconds if seconds is not None else (agent.cooldown_seconds if agent else 0)
        if duration <= 0:
            return
        with self._state_lock:
            cooldown_until = time.time() + duration
            self._cooldowns[agent_name] = cooldown_until
            health = self._health.setdefault(agent_name, ProviderHealth())
            health.cooldown_until = max(health.cooldown_until, cooldown_until)
            health.unavailable_until = max(health.unavailable_until, cooldown_until)
            health.last_checked_at = time.time()
            self._save_provider_health()

    def health_snapshot(self, *, include_history: bool = False) -> dict[str, dict[str, Any]]:
        """Return normalized provider health for diagnostics and tests."""

        with self._state_lock:
            now = time.time()
            names = sorted(set(self.config.agents) | set(self._health))
            health_rows = {name: self._health.get(name, ProviderHealth()) for name in names}
            cooldown_rows = {name: self._cooldowns.get(name, 0.0) for name in names}
        snapshot: dict[str, dict[str, Any]] = {}
        for name in names:
            health = health_rows[name]
            agent = self.config.agents.get(name)
            capabilities = agent_capabilities(agent) if agent else None
            cooldown_until = max(cooldown_rows.get(name, 0.0), health.cooldown_deadline())
            available = bool(agent.enabled) if agent else False
            if agent and not agent_allowed_by_cost_policy(self.config, agent):
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
            tool_mode = tool_compatibility_mode(self.config, agent)
            unavailable_reason = ""
            if not agent.enabled:
                unavailable_reason = "disabled"
            elif require_free is True and not free:
                unavailable_reason = "not free"
            elif not agent_allowed_by_cost_policy(self.config, agent):
                unavailable_reason = "skipped by free_only"
            elif (
                needs_tools is True
                and not _agent_supports_tools(agent)
                and tool_mode == "unavailable"
            ):
                unavailable_reason = "tool support required"
            elif self._is_on_cooldown(agent.name):
                unavailable_reason = "temporarily unavailable"
            else:
                unavailable_reason = self._preflight_skip_reason(agent, request) or ""
                if not unavailable_reason:
                    unavailable_reason = _local_probe_readiness_reason(self.config, agent) or ""

            available = not unavailable_reason
            if unavailable_reason and not include_unavailable:
                continue
            token_saver = self._token_saver_signal(agent, request, classification=self._classify_request(request))
            score = self._recommendation_score(
                agent,
                request=request,
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
                    "effective_supports_tools": (
                        tool_mode in {"native", "emulated"}
                    ),
                    "tool_compatibility": tool_mode,
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
                    "token_saver": token_saver,
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

    def _routing_score(
        self,
        agent: AgentConfig,
        request: HubRequest | None = None,
        *,
        include_routing_memory: bool = True,
        include_token_saver: bool = True,
    ) -> float:
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
                input_tokens = estimate_input_tokens(request)
                required_tokens = input_tokens + output_token_budget(
                    self.config,
                    request,
                    agent,
                    input_tokens=input_tokens,
                    health=health,
                ).effective
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
            repository_signal = self._repository_routing_signal(
                agent,
                self._classify_request(request),
                self._repository_dna(),
            )
            score += float(repository_signal.get("adjustment", 0.0) or 0.0)
            if include_routing_memory:
                signal = self._routing_memory_signal(agent, request)
                score += float(signal.get("adjustment", 0.0) or 0.0)
            if include_token_saver:
                token_saver = self._token_saver_signal(
                    agent,
                    request,
                    classification=self._classify_request(request),
                )
                score += float(token_saver.get("adjustment", 0.0) or 0.0)
        evaluation = self.provider_scores.get(agent.name) if isinstance(self.provider_scores, dict) else None
        if isinstance(evaluation, dict):
            try:
                score += float(evaluation.get("overall_score", 0.0)) * 8.0
            except (TypeError, ValueError):
                pass
        return score

    def _routing_memory_signal(
        self,
        agent: AgentConfig,
        request: HubRequest,
        *,
        classification: Any | None = None,
    ) -> dict[str, Any]:
        if not getattr(self.config, "routing_memory_enabled", True):
            return {
                "active": False,
                "agent": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "adjustment": 0.0,
                "summary": "Routing memory is disabled by configuration.",
                "similar_outcomes": [],
            }
        try:
            classification = classification or self._classify_request(request)
            return self.routing_memory.routing_signal(agent, classification)
        except Exception:
            return {
                "active": False,
                "agent": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "adjustment": 0.0,
                "summary": "Routing memory was unavailable.",
                "similar_outcomes": [],
            }

    def _repository_routing_signal(
        self,
        agent: AgentConfig,
        classification: Any,
        dna: RepositoryDNA | None = None,
    ) -> dict[str, Any]:
        if not getattr(self.config, "repository_dna_enabled", True):
            return {
                "active": False,
                "agent": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "adjustment": 0.0,
                "summary": "Repository DNA routing is disabled by configuration.",
            }
        try:
            return repository_routing_signal(
                agent,
                classification,
                dna if dna is not None else self._repository_dna(),
            )
        except Exception:
            return {
                "active": False,
                "agent": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "adjustment": 0.0,
                "summary": "Repository DNA could not be applied.",
            }

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
        if (agent.provider_type or agent.provider).lower() == "codex-cli":
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
        routing_mode: str | None = None,
        decision: RoutingDecision | None = None,
        failover: list[FailoverEvent] | None = None,
    ) -> None:
        with self._state_lock:
            health = self._health.setdefault(agent.name, ProviderHealth())
            now = time.time()
            request_started_at = max(0.0, now - max(0.0, latency_seconds))
            success_started_before_latest_failure = bool(
                health.last_failure_at
                and request_started_at <= health.last_failure_at
                and health.cooldown_deadline() > now
            )
            previous_rate_limited = health.rate_limited
            previous_quota_exhausted = health.quota_exhausted
            health.success_count += 1
            health.total_latency_seconds += max(0.0, latency_seconds)
            health.last_success_at = now
            health.last_checked_at = now
            health.last_request_source = request_source(request)
            health.last_route = request.route or ""
            health.last_request_started_at = request_started_at
            health.last_first_token_latency_seconds = max(
                0.0,
                float(first_token_latency_seconds)
                if first_token_latency_seconds is not None
                else float(_provider_stream_metadata(result.raw).get("first_token_latency_seconds") or 0.0),
            )
            health.last_total_latency_seconds = max(0.0, latency_seconds)
            health.last_finish_reason = str(result.finish_reason or "")
            health.last_failover_attempts = max(0, int(failover_attempts))
            if not success_started_before_latest_failure:
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
            if success_started_before_latest_failure:
                health.rate_limited = health.rate_limited or previous_rate_limited
                health.quota_exhausted = health.quota_exhausted or previous_quota_exhausted
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
            routing_mode=routing_mode or "",
            final=True,
        )
        if request_id is not None:
            self._record_usage_ledger_outcome(
                request_id=request_id,
                request=request,
                agent=agent,
                model=result.model or agent.model,
                result=result,
                success=True,
                latency_seconds=latency_seconds,
                failover=failover or [],
                decision=decision,
                task_type=(
                    decision.task_type
                    if decision is not None and decision.task_type
                    else self._classify_task(request)
                ),
            )

    def _record_usage_ledger_outcome(
        self,
        *,
        request_id: str,
        request: HubRequest,
        agent: AgentConfig,
        model: str,
        result: ProviderResult,
        success: bool,
        latency_seconds: float | None,
        failover: list[FailoverEvent],
        decision: RoutingDecision | None,
        task_type: str,
    ) -> None:
        try:
            context = _context_usage(request)
            estimated_input = int(
                context.get("estimated_input_tokens")
                or context.get("input_tokens")
                or estimate_input_tokens(request)
            )
            estimated_output = expected_output_tokens(request, agent)
            if estimated_output <= 0:
                estimated_output = _result_output_tokens(result)
            record_completed_request(
                config=self.config,
                request_id=request_id,
                request=request,
                agent=agent,
                model=model,
                usage=result.usage,
                output_text=result.text,
                latency_seconds=latency_seconds,
                success=success,
                failover=failover,
                candidate_scores=decision.candidate_scores if decision is not None else [],
                task_type=task_type,
                input_tokens_estimated=estimated_input,
                output_tokens_estimated=estimated_output,
            )
        except Exception:
            return

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
        normalized_error_type = _canonical_error_type(error_type)
        with self._state_lock:
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
            failure_count = health.failure_count
            degraded = health.is_degraded()
            last_input_tokens = health.last_input_tokens
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
                failure_count=failure_count,
                degraded=degraded,
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
            input_tokens=last_input_tokens,
            output_tokens=0,
            estimated_cost_usd=estimate_known_cost_usd(
                agent,
                input_tokens=last_input_tokens,
                output_tokens=0,
            ),
            error_type=normalized_error_type,
            routing_mode=routing_mode or "",
            final=False,
        )

    def record_tool_result(self, agent_name: str, ok: bool) -> None:
        """Record whether an agent-produced tool call completed successfully."""

        with self._state_lock:
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
        routing_mode: str = "",
        final: bool = False,
    ) -> None:
        if request is None:
            return
        classification = None
        if self.config.adaptive_learning_enabled:
            try:
                classification = self._classify_request(request)
                self.adaptive_learning.record_outcome(
                    request_id=request_id,
                    route=request.route or "",
                    task_type=classification.task_type,
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
                pass
        try:
            if classification is None:
                classification = self._classify_request(request)
            timeout = str(error_type or "").lower() in {"timeout", "provider_timeout", "timed_out"}
            tool_failure = "tool" in str(error_type or "").lower()
            score = outcome_score(
                success=success,
                latency_seconds=latency_seconds,
                fallback_count=failover_attempts,
                timeout=timeout,
                tool_failure=tool_failure,
                reviewer_pass=True,
                user_cancellation="cancel" in str(error_type or "").lower(),
                token_efficiency=_token_efficiency_for_score(input_tokens, output_tokens),
            )
            self.provider_scores = self.provider_score_store.record_outcome(
                agent=agent.name,
                provider=agent.provider,
                model=model or agent.model,
                task_type=classification.task_type,
                score=score,
                latency_ms=max(0.0, float(latency_seconds or 0.0)) * 1000,
                ok=success,
            )
        except Exception:
            pass
        self._record_routing_memory_outcome(
            request_id=request_id,
            request=request,
            agent=agent,
            model=model,
            success=success,
            latency_seconds=latency_seconds,
            failover_attempts=failover_attempts,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
            error_type=error_type,
            routing_mode=routing_mode,
            final=final,
        )

    def _record_routing_memory_outcome(
        self,
        *,
        request_id: str | None,
        request: HubRequest,
        agent: AgentConfig,
        model: str,
        success: bool,
        latency_seconds: float | None,
        failover_attempts: int,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_usd: float | None,
        error_type: str | None = None,
        routing_mode: str = "",
        final: bool = False,
    ) -> None:
        if not getattr(self.config, "routing_memory_enabled", True):
            return
        try:
            classification = self._classify_request(request)
            signal = self.routing_memory.routing_signal(agent, classification)
            self.routing_memory.record_outcome(
                request_id=request_id,
                request=request,
                classification=classification,
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
                routing_mode=routing_mode,
                memory_adjustment=float(signal.get("adjustment", 0.0) or 0.0),
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
            with self._state_lock:
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
        request: HubRequest | None = None,
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
        if request is not None:
            token_saver = self._token_saver_signal(agent, request, classification=self._classify_request(request))
            score += float(token_saver.get("adjustment", 0.0) or 0.0)
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


def _request_bool_option(request: HubRequest, *keys: str, default: bool = False) -> bool:
    value = _request_option(request, *keys)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"0", "false", "no", "off", "disabled"}:
            return False
        if lowered in {"1", "true", "yes", "on", "enabled"}:
            return True
    if value is None:
        return default
    return bool(value)


def _free_remote_cloud_agent(agent: AgentConfig) -> bool:
    if not is_free_agent(agent):
        return False
    provider_type = (agent.provider_type or agent.provider).lower()
    if provider_type in {"codex-cli", "echo"}:
        return False
    if normalize_provider(agent.provider) == "local-research":
        return False
    if provider_type == "ollama-cloud":
        return True
    if normalize_provider(agent.provider) != "openai-compatible":
        return False
    return not _is_local_or_private_agent(agent)


def _strict_free_policy_enabled(config: HubConfig) -> bool:
    return bool(getattr(config, "disable_non_free_models", False))


def _token_saver_offload_candidate(agent: AgentConfig) -> bool:
    if not is_free_agent(agent):
        return False
    if _codex_like_agent(agent):
        return False
    provider = normalize_provider(agent.provider)
    if provider == "echo":
        return False
    return True


def _codex_like_agent(agent: AgentConfig) -> bool:
    name = agent.name.lower()
    provider = normalize_provider(agent.provider)
    provider_type = (agent.provider_type or agent.provider).lower()
    model = agent.model.lower()
    return (
        name in {"codex", "codex-cli", "chatgpt", "codex-fallback", "chatgpt-fallback"}
        or provider in {"openai", "codex-cli"}
        or provider_type in {"openai", "codex-cli"}
        or "codex" in model
    )


def _token_saver_task_capability(agent: AgentConfig, classification: Any) -> float:
    task_type = str(getattr(classification, "task_type", "") or "general")
    task_category = str(getattr(classification, "task_category", "") or task_type)
    provider = normalize_provider(agent.provider)
    coding = _optional_float(agent.coding_score)
    reasoning = _optional_float(agent.reasoning_score)
    speed = _optional_float(agent.speed_score)
    if task_type in {"coding", "debug", "test_generation", "tool_use"} or task_category in {"refactor", "debugging"}:
        return _bounded_float(coding if coding is not None else 0.52, 0.0, 1.0)
    if task_type in {"review", "security_sensitive_change"}:
        fallback = coding if coding is not None else 0.0
        return _bounded_float(reasoning if reasoning is not None else fallback * 0.8 or 0.55, 0.0, 1.0)
    if task_type == "research":
        if provider == "local-research":
            return 0.82
        fallback = reasoning if reasoning is not None else coding if coding is not None else 0.58
        return _bounded_float(fallback, 0.0, 1.0)
    if task_type in {"simple_explanation", "documentation", "general"}:
        values = [
            value
            for value in (
                reasoning,
                (coding * 0.75 if coding is not None else None),
                (speed * 0.85 if speed is not None else None),
                0.68,
            )
            if value is not None
        ]
        return _bounded_float(max(values), 0.0, 1.0)
    return _bounded_float(max(value for value in (coding or 0.0, reasoning or 0.0, 0.58)), 0.0, 1.0)


def _token_saver_task_penalty(classification: Any) -> float:
    risk = str(getattr(classification, "risk_level", "low") or "low")
    complexity = str(getattr(classification, "complexity", "low") or "low")
    context_estimate = str(getattr(classification, "context_estimate", "small") or "small")
    penalty = {
        "low": 0.0,
        "medium": 0.08,
        "high": 0.26,
        "critical": 0.42,
    }.get(risk, 0.0)
    penalty += {"low": 0.0, "medium": 0.06, "high": 0.18}.get(complexity, 0.0)
    if context_estimate == "medium":
        penalty += 0.04
    elif context_estimate == "large":
        penalty += 0.16
    return penalty


def _codex_efficiency_reference_agent(agents: list[AgentConfig]) -> AgentConfig | None:
    explicit = [
        agent
        for agent in agents
        if _codex_like_agent(agent)
    ]
    if explicit:
        return sorted(
            explicit,
            key=lambda agent: (
                float(agent.coding_score or 0.0) + float(agent.reasoning_score or 0.0),
                float(agent.context_window or 0),
            ),
            reverse=True,
        )[0]
    paid = [agent for agent in agents if not is_free_agent(agent)]
    if not paid:
        return None
    return sorted(
        paid,
        key=lambda agent: (
            float(agent.coding_score or 0.0) + float(agent.reasoning_score or 0.0),
            float(agent.context_window or 0),
        ),
        reverse=True,
    )[0]


def _score_task_aliases(classification: Any) -> list[str]:
    data = classification.to_dict() if hasattr(classification, "to_dict") else {}
    task_type = str(data.get("task_type") or "general")
    task_category = str(data.get("task_category") or task_type)
    aliases = [task_type, task_category]
    if task_type == "simple_explanation" or task_category == "explanation":
        aliases.extend(["summarization", "reasoning", "general"])
    return _dedupe_strings([alias for alias in aliases if alias])


def _dedupe_agents(agents: list[AgentConfig]) -> list[AgentConfig]:
    seen: set[str] = set()
    result: list[AgentConfig] = []
    for agent in agents:
        if agent.name in seen:
            continue
        seen.add(agent.name)
        result.append(agent)
    return result


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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


def _bounded_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))


def _token_efficiency_for_score(input_tokens: int, output_tokens: int) -> float | None:
    try:
        input_count = max(0, int(input_tokens or 0))
        output_count = max(0, int(output_tokens or 0))
    except (TypeError, ValueError):
        return None
    if input_count <= 0:
        return None
    return output_count / input_count


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


def _routing_transparency_metadata(
    *,
    agent: AgentConfig,
    result: ProviderResult,
    failover: list[FailoverEvent],
    decision: RoutingDecision | None,
    latency_seconds: float | None,
) -> dict[str, Any]:
    input_tokens = _usage_int(result.usage, "prompt_tokens", "input_tokens")
    output_tokens = _usage_int(result.usage, "completion_tokens", "output_tokens")
    if output_tokens <= 0:
        output_tokens = _result_output_tokens(result)
    fallback_reason = failover[-1].reason if failover else ""
    summary: dict[str, Any] = {
        "selected_agent": agent.name,
        "selected_provider": agent.provider,
        "selected_model": result.model or agent.model,
        "why_provider_chosen": decision.reason if decision is not None else "Selected provider returned the response.",
        "why_fallback_happened": fallback_reason,
        "fallback_count": len(failover),
        "fallback_happened": bool(failover),
        "latency_ms": round(latency_seconds * 1000, 2) if latency_seconds is not None else None,
        "estimated_cost_usd": estimate_known_cost_usd(
            agent,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
        "error_reason": fallback_reason,
    }
    if decision is not None:
        summary.update(
            {
                "routing_mode": decision.routing_mode,
                "task_type": decision.task_type,
                "fallback_chain": list(decision.fallback_chain),
            }
        )
    return summary


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


def _local_probe_readiness_reason(config: HubConfig, agent: AgentConfig) -> str | None:
    if normalize_provider(agent.provider) != "openai-compatible":
        return None
    if not _is_local_or_private_agent(agent):
        return None
    report = getattr(config, "initialization_report", {}) or {}
    if not isinstance(report, dict):
        return None
    probe_errors = report.get("probe_errors")
    if isinstance(probe_errors, dict) and probe_errors.get(agent.name):
        return f"local endpoint probe failed: {probe_errors[agent.name]}"
    detected_models = report.get("detected_local_models")
    if isinstance(detected_models, dict) and agent.name in detected_models:
        models = detected_models.get(agent.name)
        if isinstance(models, list):
            if not models:
                return "local endpoint returned no model IDs"
            if agent.model not in models:
                return f"configured model {agent.model!r} was not reported by the local endpoint"
    return None


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
    hub = dict(raw.get("agent_hub")) if isinstance(raw.get("agent_hub"), dict) else {}
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
    raw = dict(request.raw) if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
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
    raw = dict(result.raw) if isinstance(result.raw, dict) else {}
    metadata = dict(raw.get("agent_hub")) if isinstance(raw.get("agent_hub"), dict) else {}
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


def _routing_memory_route_reason(candidate_scores: list[dict[str, Any]]) -> str:
    if not candidate_scores:
        return ""
    selected = candidate_scores[0]
    memory = selected.get("routing_memory")
    if not isinstance(memory, dict):
        return ""
    adjustment = _optional_float(memory.get("adjustment")) or 0.0
    if abs(adjustment) < 0.05:
        return ""
    summary = memory.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    direction = "boosted" if adjustment > 0 else "penalized"
    return f"Routing memory {direction} {selected.get('agent')} by {adjustment:+.2f}."


def _token_saver_route_reason(candidate_scores: list[dict[str, Any]]) -> str:
    if not candidate_scores:
        return ""
    selected = candidate_scores[0]
    token_saver = selected.get("token_saver")
    if not isinstance(token_saver, dict) or not token_saver.get("active"):
        return ""
    confidence = _optional_float(token_saver.get("confidence"))
    reference = token_saver.get("codex_reference")
    loss = _optional_float(token_saver.get("estimated_productivity_loss")) or 0.0
    if confidence is None:
        return f"Token saver selected free candidate {selected.get('agent')} ahead of {reference or 'Codex fallback'}."
    return (
        f"Token saver selected free candidate {selected.get('agent')} ahead of "
        f"{reference or 'Codex fallback'} with confidence {confidence:.2f} "
        f"and estimated productivity loss {loss:.2f}."
    )


def _routing_decision_explanation(decision: RoutingDecision) -> RoutingDecisionExplanation:
    selected = _selected_scorecard(decision)
    selected_agent = selected.get("agent") or decision.selected_agent or ""
    selected_provider = selected.get("provider") or decision.selected_provider
    selected_model = selected.get("model") or decision.selected_model
    selected_score = _optional_float(selected.get("final_routing_score")) or _optional_float(selected.get("routing_score"))
    selected_cost = _optional_float(selected.get("estimated_cost_usd"))
    classification = decision.task_classification if isinstance(decision.task_classification, dict) else {}
    capabilities = selected.get("capabilities") if isinstance(selected.get("capabilities"), dict) else {}
    health = selected.get("health") if isinstance(selected.get("health"), dict) else {}
    adaptive = selected.get("adaptive") if isinstance(selected.get("adaptive"), dict) else {}
    token_saver = selected.get("token_saver") if isinstance(selected.get("token_saver"), dict) else {}
    memory = selected.get("routing_memory") if isinstance(selected.get("routing_memory"), dict) else {}
    repository_dna = selected.get("repository_dna") if isinstance(selected.get("repository_dna"), dict) else {}
    summary = (
        f"Selected {selected_provider}/{selected_model}"
        if selected_provider or selected_model
        else "No provider selected"
    )
    if decision.reason:
        summary = f"{summary}: {decision.reason}"
    reasons = _routing_explanation_reasons(
        decision,
        selected=selected,
        classification=classification,
        capabilities=capabilities,
        health=health,
        adaptive=adaptive,
        token_saver=token_saver,
        memory=memory,
        repository_dna=repository_dna,
    )
    provider_rankings = _routing_explanation_rankings(decision.candidate_scores, by="provider")
    model_rankings = _routing_explanation_rankings(decision.candidate_scores, by="model")
    return RoutingDecisionExplanation(
        summary=summary,
        selected={
            "agent": selected_agent,
            "provider": selected_provider,
            "model": selected_model,
            "workflow": decision.selected_workflow,
            "routing_mode": decision.routing_mode,
            "task_type": decision.task_type,
            "task_category": decision.task_category,
            "risk_level": decision.risk,
            "complexity": decision.complexity,
            "final_routing_score": round(selected_score, 3) if selected_score is not None else None,
            "token_saver": token_saver,
        },
        reasons=reasons,
        rejected=_fallback_rejections(decision.candidate_scores),
        provider_rankings=provider_rankings,
        model_rankings=model_rankings,
        adaptive_learning=_routing_explanation_adaptive(decision.candidate_scores, adaptive),
        routing_memory=_routing_explanation_memory(decision, memory),
        repository_dna=_routing_explanation_repository_dna(decision, repository_dna),
        cost_savings=_routing_explanation_cost_savings(decision.candidate_scores, selected_cost),
        context_optimization=_routing_explanation_context(decision, selected, classification, capabilities),
        lifecycle=[
            "User request",
            "Task classification",
            "Workspace analysis",
            "Risk assessment",
            "Workflow selection",
            "Provider selection",
            "Execution",
            "Outcome analysis",
            "Adaptive learning",
            "Future routing improvement",
        ],
    )


def _selected_scorecard(decision: RoutingDecision) -> dict[str, Any]:
    for row in decision.candidate_scores:
        if not isinstance(row, dict):
            continue
        if row.get("agent") == decision.selected_agent:
            return row
    first = decision.candidate_scores[0] if decision.candidate_scores else {}
    return dict(first) if isinstance(first, dict) else {}


def _routing_explanation_reasons(
    decision: RoutingDecision,
    *,
    selected: dict[str, Any],
    classification: dict[str, Any],
    capabilities: dict[str, Any],
    health: dict[str, Any],
    adaptive: dict[str, Any],
    token_saver: dict[str, Any],
    memory: dict[str, Any],
    repository_dna: dict[str, Any],
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    _append_reason(
        reasons,
        "Routing policy",
        decision.reason or "Selected the highest-ranked compatible candidate.",
        "AgentRouter.decide",
    )
    category = " / ".join(
        str(value)
        for value in (
            decision.task_type,
            decision.task_category,
            decision.complexity,
        )
        if value
    )
    if category:
        _append_reason(reasons, "Task classification", category, "TaskClassifier")
    workspace_bits = []
    if decision.language != "unknown":
        workspace_bits.append(decision.language)
    if decision.framework != "unknown":
        workspace_bits.append(decision.framework)
    repo_size = classification.get("repo_size_bucket")
    if repo_size and repo_size != "unknown":
        workspace_bits.append(f"{repo_size} repository")
    file_types = classification.get("file_types")
    if isinstance(file_types, list) and file_types:
        workspace_bits.append("files " + ", ".join(str(item) for item in file_types[:5]))
    if workspace_bits:
        _append_reason(reasons, "Workspace analysis", "; ".join(workspace_bits), "TaskClassifier")
    if decision.risk and decision.risk != "low":
        detail = f"{decision.risk} risk"
        if decision.permission_requirements:
            detail = f"{detail}; permissions: {', '.join(decision.permission_requirements)}"
        _append_reason(reasons, "Risk assessment", detail, "TaskClassifier")
    if decision.selected_workflow:
        _append_reason(
            reasons,
            "Workflow selection",
            decision.selected_workflow,
            "WorkflowSelector / routing memory",
        )
    if capabilities:
        capability_bits = []
        if capabilities.get("supports_tools"):
            capability_bits.append("tool-capable")
        if capabilities.get("supports_streaming"):
            capability_bits.append("streaming")
        if capabilities.get("context_window"):
            capability_bits.append(f"context {capabilities.get('context_window')}")
        if capability_bits:
            _append_reason(reasons, "Capability match", ", ".join(capability_bits), "agent capabilities")
    if health:
        reliability = _optional_float(health.get("reliability_score"))
        latency = _optional_float(health.get("average_latency_ms"))
        parts = []
        if reliability is not None:
            parts.append(f"reliability {reliability:.2f}")
        if latency and latency > 0:
            parts.append(f"avg latency {latency:.0f} ms")
        if health.get("degraded"):
            parts.append("degraded")
        if parts:
            _append_reason(reasons, "Provider health", ", ".join(parts), "provider_health.json")
    if adaptive:
        summary = str(adaptive.get("summary") or "").strip()
        if summary:
            _append_reason(reasons, "Adaptive learning", summary, "adaptive_learning.json")
    if token_saver:
        summary = str(token_saver.get("summary") or "").strip()
        if summary:
            confidence = token_saver.get("confidence")
            detail = summary
            if confidence is not None:
                detail = f"{summary} Confidence {confidence}."
            _append_reason(reasons, "Token saver", detail, "candidate scorecard")
    if memory:
        summary = str(memory.get("summary") or "").strip()
        if summary:
            _append_reason(reasons, "Routing memory", summary, "routing_memory.jsonl")
    if repository_dna:
        summary = str(repository_dna.get("summary") or "").strip()
        if summary:
            _append_reason(reasons, "Repository DNA", summary, "repository_intelligence.json")
    estimated_cost = selected.get("estimated_cost_usd")
    if estimated_cost is not None:
        _append_reason(
            reasons,
            "Cost estimate",
            f"estimated ${float(estimated_cost):.6f} for the selected candidate",
            "candidate scorecard",
        )
    for detail in decision.routing_reasons[:8]:
        text = str(detail or "").strip()
        if text:
            _append_reason(reasons, "Additional signal", text, "routing_reasons")
    return _dedupe_reason_rows(reasons)[:14]


def _append_reason(rows: list[dict[str, Any]], label: str, detail: str, source: str) -> None:
    rows.append(
        {
            "label": label,
            "detail": detail,
            "source": source,
        }
    )


def _dedupe_reason_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("label") or ""), str(row.get("detail") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _routing_explanation_rankings(
    candidate_scores: list[dict[str, Any]],
    *,
    by: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in candidate_scores[:10]:
        if not isinstance(row, dict):
            continue
        health = row.get("health") if isinstance(row.get("health"), dict) else {}
        capabilities = row.get("capabilities") if isinstance(row.get("capabilities"), dict) else {}
        repository_signal = row.get("repository_dna") if isinstance(row.get("repository_dna"), dict) else {}
        token_saver = row.get("token_saver") if isinstance(row.get("token_saver"), dict) else {}
        ranking = {
            "rank": row.get("rank"),
            "agent": row.get("agent"),
            "provider": row.get("provider"),
            "model": row.get("model"),
            "score": row.get("final_routing_score", row.get("routing_score")),
            "original_score": row.get("original_routing_score"),
            "memory_adjustment": row.get("memory_adjustment"),
            "repository_dna_adjustment": row.get("repository_dna_adjustment"),
            "estimated_cost_usd": row.get("estimated_cost_usd"),
            "estimated_input_tokens": row.get("estimated_input_tokens"),
            "estimated_output_tokens": row.get("estimated_output_tokens"),
            "reliability_score": health.get("reliability_score"),
            "average_latency_ms": health.get("average_latency_ms"),
            "supports_tools": capabilities.get("supports_tools"),
            "context_window": capabilities.get("context_window"),
            "repository_dna_summary": repository_signal.get("summary"),
            "token_saver_active": token_saver.get("active"),
            "token_saver_confidence": token_saver.get("confidence"),
            "token_saver_adjustment": row.get("token_saver_adjustment"),
            "why": row.get("why"),
        }
        if by == "provider":
            key = f"{row.get('provider')}"
        else:
            key = f"{row.get('provider')}/{row.get('model')}"
        ranking["key"] = key
        rows.append(ranking)
    return rows


def _routing_explanation_adaptive(
    candidate_scores: list[dict[str, Any]],
    selected_adaptive: dict[str, Any],
) -> dict[str, Any]:
    signals = []
    for row in candidate_scores[:10]:
        adaptive = row.get("adaptive") if isinstance(row.get("adaptive"), dict) else {}
        if not adaptive:
            continue
        signals.append(
            {
                "agent": row.get("agent"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "active": bool(adaptive.get("active")),
                "scope": adaptive.get("scope"),
                "attempts": adaptive.get("attempts", 0),
                "samples_needed": adaptive.get("samples_needed", 0),
                "adaptive_bonus": adaptive.get("adaptive_bonus", 0.0),
                "summary": adaptive.get("summary", ""),
                "scorecard": adaptive.get("scorecard", {}),
            }
        )
    return {
        "selected_signal": _compact_adaptive_signal(selected_adaptive),
        "candidate_signals": signals,
        "active": bool(selected_adaptive.get("active")),
    }


def _routing_explanation_memory(
    decision: RoutingDecision,
    selected_memory: dict[str, Any],
) -> dict[str, Any]:
    return {
        "selected_signal": _compact_memory_signal(selected_memory),
        "memory_adjustments": list(decision.memory_adjustments),
        "active": bool(selected_memory.get("active")) if selected_memory else False,
    }


def _routing_explanation_repository_dna(
    decision: RoutingDecision,
    selected_signal: dict[str, Any],
) -> dict[str, Any]:
    dna = dict(decision.repository_dna or {})
    return {
        "repository": {
            key: dna.get(key)
            for key in (
                "profile_id",
                "project",
                "language",
                "architecture",
                "code_style",
                "testing",
                "risk_areas",
                "summary",
            )
            if key in dna
        },
        "selected_signal": _compact_repository_signal(selected_signal),
        "active": bool(selected_signal.get("active")) if selected_signal else False,
    }


def _compact_adaptive_signal(signal: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(signal, dict):
        return {}
    return {
        key: signal.get(key)
        for key in (
            "agent",
            "active",
            "scope",
            "attempts",
            "samples_needed",
            "adaptive_bonus",
            "summary",
            "scorecard",
        )
        if key in signal
    }


def _compact_memory_signal(signal: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(signal, dict):
        return {}
    return {
        key: signal.get(key)
        for key in (
            "active",
            "agent",
            "provider",
            "model",
            "adjustment",
            "attempts",
            "success_rate",
            "average_outcome_score",
            "timeout_rate",
            "fallback_frequency",
            "similar_outcomes_count",
            "summary",
        )
        if key in signal
    }


def _compact_repository_signal(signal: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(signal, dict):
        return {}
    return {
        key: signal.get(key)
        for key in (
            "active",
            "agent",
            "provider",
            "model",
            "model_family",
            "adjustment",
            "repository_profile_id",
            "project",
            "language",
            "architecture",
            "rules",
            "summary",
        )
        if key in signal
    }


def _routing_explanation_cost_savings(
    candidate_scores: list[dict[str, Any]],
    selected_cost: float | None,
) -> dict[str, Any]:
    costs: list[tuple[dict[str, Any], float]] = [
        (row, _optional_float(row.get("estimated_cost_usd")))
        for row in candidate_scores
        if isinstance(row, dict)
    ]
    costs = [(row, cost) for row, cost in costs if cost is not None]
    if selected_cost is None or not costs:
        return {
            "estimated_selected_cost_usd": selected_cost,
            "estimated_savings_usd": None,
            "comparison": "named_estimated_baselines",
            "measurement_source": "estimated_routing_scorecard",
            "named_baselines": _routing_cost_baseline_rows(
                candidate_scores,
                selected_cost=selected_cost,
            ),
        }
    baseline_rows = _routing_cost_baseline_rows(candidate_scores, selected_cost=selected_cost)
    positive_savings = [
        _optional_float(row.get("savings_usd"))
        for row in baseline_rows
        if _optional_float(row.get("savings_usd")) is not None
        and (_optional_float(row.get("savings_usd")) or 0.0) > 0
    ]
    primary = next(
        (
            row
            for row in baseline_rows
            if row.get("baseline") in {"vs_user_default_model", "vs_static_routing"}
            and _optional_float(row.get("savings_usd")) is not None
        ),
        next((row for row in baseline_rows if _optional_float(row.get("savings_usd")) is not None), {}),
    )
    return {
        "estimated_selected_cost_usd": round(selected_cost, 8),
        "estimated_savings_usd": round(max(positive_savings), 8) if positive_savings else None,
        "comparison": "named_estimated_baselines",
        "measurement_source": "estimated_routing_scorecard",
        "primary_baseline": primary or None,
        "named_baselines": baseline_rows,
    }


def _routing_cost_baseline_rows(
    candidate_scores: list[dict[str, Any]],
    *,
    selected_cost: float | None,
) -> list[dict[str, Any]]:
    rows = [row for row in candidate_scores if isinstance(row, dict)]
    baselines: list[tuple[str, dict[str, Any] | None]] = [
        ("vs_user_default_model", None),
        ("vs_claude_sonnet", _find_candidate_by_terms(rows, required=("claude", "sonnet"))),
        (
            "vs_gpt_4_1",
            _find_candidate_by_terms(
                rows,
                any_terms=("gpt-4.1", "gpt-4-1", "gpt 4.1"),
            ),
        ),
        ("vs_static_routing", rows[0] if rows else None),
        ("vs_cheapest_model_only", _cheapest_candidate(rows)),
    ]
    return [
        _routing_cost_baseline_row(name, row, selected_cost=selected_cost)
        for name, row in baselines
    ]


def _routing_cost_baseline_row(
    baseline: str,
    row: dict[str, Any] | None,
    *,
    selected_cost: float | None,
) -> dict[str, Any]:
    if row is None:
        return {
            "baseline": baseline,
            "status": "unavailable",
            "reason": "No matching configured candidate with known estimated pricing.",
            "cost_usd": None,
            "savings_usd": None,
            "savings_pct": None,
        }
    baseline_cost = _optional_float(row.get("estimated_cost_usd"))
    if baseline_cost is None or selected_cost is None:
        return {
            "baseline": baseline,
            "agent": row.get("agent"),
            "provider": row.get("provider"),
            "model": row.get("model"),
            "status": "unpriced",
            "reason": "Candidate is missing complete configured pricing.",
            "cost_usd": None,
            "savings_usd": None,
            "savings_pct": None,
        }
    savings = float(baseline_cost) - float(selected_cost)
    savings_pct = savings / float(baseline_cost) if baseline_cost > 0 else 0.0
    return {
        "baseline": baseline,
        "agent": row.get("agent"),
        "provider": row.get("provider"),
        "model": row.get("model"),
        "status": "priced",
        "cost_usd": round(float(baseline_cost), 8),
        "savings_usd": round(savings, 8),
        "savings_pct": round(savings_pct, 6),
    }


def _find_candidate_by_terms(
    rows: list[dict[str, Any]],
    *,
    required: tuple[str, ...] = (),
    any_terms: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    required = tuple(term.lower() for term in required)
    any_terms = tuple(term.lower() for term in any_terms)
    for row in rows:
        haystack = " ".join(
            str(row.get(key) or "").lower()
            for key in ("agent", "provider", "provider_type", "model")
        )
        required_match = all(term in haystack for term in required) if required else True
        any_match = any(term in haystack for term in any_terms) if any_terms else True
        if required_match and any_match:
            return row
    return None


def _cheapest_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    priced = [
        (row, _optional_float(row.get("estimated_cost_usd")))
        for row in rows
    ]
    priced = [(row, cost) for row, cost in priced if cost is not None]
    if not priced:
        return None
    return min(priced, key=lambda item: (float(item[1] or 0.0), str(item[0].get("agent") or "")))[0]


def _routing_explanation_context(
    decision: RoutingDecision,
    selected: dict[str, Any],
    classification: dict[str, Any],
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    estimated_input = _optional_int(selected.get("estimated_input_tokens")) or decision.estimated_input_tokens
    estimated_output = _optional_int(selected.get("estimated_output_tokens")) or 0
    context_window = _optional_int(capabilities.get("context_window"))
    required_total = max(0, int(estimated_input or 0)) + max(0, int(estimated_output or 0))
    fits_context = None if context_window is None else context_window >= required_total
    return {
        "estimated_input_tokens": estimated_input,
        "estimated_output_tokens": estimated_output,
        "estimated_total_tokens": required_total,
        "context_estimate": decision.context_estimate,
        "context_strategy": classification.get("context_strategy"),
        "repo_size_bucket": classification.get("repo_size_bucket"),
        "repository_context_needed": classification.get("repository_context_needed"),
        "selected_context_window": context_window,
        "fits_selected_context_window": fits_context,
    }


def _fallback_rejections(candidate_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(candidate_scores) <= 1:
        return []
    selected = candidate_scores[0]
    selected_score = _optional_float(selected.get("final_routing_score")) or _optional_float(selected.get("routing_score")) or 0.0
    selected_cost = _optional_float(selected.get("estimated_cost_usd"))
    selected_health = selected.get("health") if isinstance(selected.get("health"), dict) else {}
    selected_reliability = _optional_float(selected_health.get("reliability_score"))
    result: list[dict[str, Any]] = []
    for row in candidate_scores[1:8]:
        final_score = _optional_float(row.get("final_routing_score")) or _optional_float(row.get("routing_score")) or 0.0
        memory_adjustment = _optional_float(row.get("memory_adjustment")) or 0.0
        reasons: list[str] = []
        row_cost = _optional_float(row.get("estimated_cost_usd"))
        if selected_cost is not None and row_cost is not None:
            if selected_cost > 0 and row_cost > selected_cost * 1.2:
                reasons.append(f"{row_cost / selected_cost:.1f}x higher estimated cost.")
            elif row_cost < selected_cost * 0.9:
                reasons.append("Lower estimated cost, but weaker overall routing fit.")
        if final_score < selected_score:
            reasons.append(f"Lower final routing score ({final_score:.2f} vs {selected_score:.2f}).")
        if memory_adjustment < -0.05:
            reasons.append(f"Routing memory penalty {memory_adjustment:+.2f}.")
        elif memory_adjustment > 0.05:
            reasons.append(f"Routing memory boost {memory_adjustment:+.2f} was not enough to win.")
        health = row.get("health") if isinstance(row.get("health"), dict) else {}
        reliability = _optional_float(health.get("reliability_score"))
        if (
            selected_reliability is not None
            and reliability is not None
            and abs(reliability - selected_reliability) <= 0.03
            and row_cost is not None
            and selected_cost is not None
            and row_cost > selected_cost
        ):
            reasons.append("Similar success rate, higher cost.")
        repository_adjustment = _optional_float(row.get("repository_dna_adjustment")) or 0.0
        if repository_adjustment > 0.05:
            reasons.append(f"Repository DNA boost {repository_adjustment:+.2f} was not enough to win.")
        token_saver = row.get("token_saver") if isinstance(row.get("token_saver"), dict) else {}
        if token_saver:
            if token_saver.get("active"):
                reasons.append("Token saver marked this as a safe free candidate, but another candidate ranked higher.")
            elif token_saver.get("free_candidate"):
                summary = str(token_saver.get("summary") or "").strip()
                if summary:
                    reasons.append(summary)
        if health.get("degraded"):
            reasons.append("Provider health is degraded.")
        if not reasons:
            reasons.append("Ranked behind selected provider by route priority, capability, health, or cost.")
        result.append(
            {
                "agent": row.get("agent"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "reason": " ".join(reasons),
            }
        )
    return result


__all__ = [
    "ProviderFactory",
    "HEALTH_STATE_VERSION",
    "HEALTH_STATE_FILE",
    "HEALTH_STALE_SECONDS",
    "MAX_FAILOVER_HISTORY",
    "ERROR_TYPE_ALIASES",
    "ROUTING_MODES",
    "DEFAULT_ROUTING_MODE",
    "LONG_CONTEXT_TOKEN_THRESHOLD",
    "RoutingDecision",
    "RoutingDecisionExplanation",
    "StreamingRoute",
    "RouterError",
    "AgentRouter",
    "_provider_health_to_state",
    "_request_option",
    "_routing_value",
    "_routing_bool",
    "_routing_int",
    "_routing_float",
    "_canonical_error_type",
    "_request_is_cline",
    "_compatibility_reductions_enabled",
    "_context_cap",
    "_compress_messages_for_budget",
    "_compact_repo_context_message",
    "_truncate_message_content",
    "_with_compaction_summary",
    "_dedupe_messages",
    "_minimal_tool_schema",
    "_privacy_requested",
    "_negated_sort_tuple",
    "_agent_limit_metadata",
    "_routing_transparency_metadata",
    "_temporary_health_path",
    "_provider_metadata_from_raw",
    "_provider_stream_metadata",
    "_apply_agent_capabilities",
    "_apply_provider_metadata",
    "_health_quota_state",
    "_remaining_quota_value",
    "_assign_int",
    "_assign_float",
    "_optional_int",
    "_optional_float",
    "_optional_timestamp",
    "_is_prefix",
    "_context_usage",
    "_request_workflow_pattern",
    "_request_workflow_role",
    "_continuation_request",
    "_merge_continuation_result",
    "_trim_text_overlap",
    "_next_candidate_name",
    "_public_model_name",
    "_token_limit_finish_reason",
    "_usage_int",
    "_result_output_tokens",
    "_adaptive_route_reason",
    "_no_fallback_reason",
    "_route_error_type",
    "_router_error_category",
    "_router_user_message",
    "_route_status_code",
    "_suggested_fix",
    "_no_model_available_message",
    "_no_model_available_fix",
    "_no_tool_capable_message",
    "_no_tool_capable_fix",
    "_checked_model_summary",
    "_missing_key_names",
    "_looks_like_coding_task",
    "_classification_text",
    "_looks_like_debug_task",
    "_looks_like_review_task",
    "_looks_like_research_task",
    "_looks_like_reasoning_task",
    "_repo_or_tool_task",
    "_tool_task_requested",
    "_repo_context_useful",
    "_agent_runner_managed_request",
    "_recommendation_reason",
    "ProviderHealth",
    "CONFIGURATION_ERROR",
    "ECHO_DISABLED",
    "NO_TOOL_CAPABLE_MODEL",
    "estimate_input_tokens",
    "expected_output_tokens",
    "output_token_budget",
]
