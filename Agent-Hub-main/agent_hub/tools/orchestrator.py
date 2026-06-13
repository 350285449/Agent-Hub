from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from ..config import AgentConfig, HubConfig
from ..models import HubRequest, ProviderResult
from .loop import (
    ToolLoopMetadata,
    assistant_message_from_result,
    compact_tool_result_for_loop,
    extract_tool_calls,
    max_loop_result,
    merge_tool_loop_metadata,
    tool_call_signature,
    valid_tool_calls,
)
from .registry import ToolRegistry
from .runtime import ToolExecutionContext, ToolExecutionPipeline
from .types import ToolCall


ProviderChat = Callable[[AgentConfig, HubRequest], ProviderResult]
ToolResultRecorder = Callable[[str, bool], None]
ToolLoopEventRecorder = Callable[..., None]


@dataclass(slots=True)
class ToolLoopRunResult:
    result: ProviderResult
    metadata: ToolLoopMetadata
    latency_seconds: float = 0.0

    def to_router_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "metadata": self.metadata,
            "latency_seconds": self.latency_seconds,
        }


class ToolLoopRunner:
    """Run provider tool-call loops behind the tool execution layer boundary."""

    def __init__(
        self,
        *,
        config: HubConfig,
        registry: ToolRegistry,
        pipeline: ToolExecutionPipeline,
        chat_provider: ProviderChat,
        record_tool_result: ToolResultRecorder | None = None,
        record_event: ToolLoopEventRecorder | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.pipeline = pipeline
        self.chat_provider = chat_provider
        self.record_tool_result = record_tool_result or _ignore_tool_result
        self.record_event = record_event or _ignore_event

    def run(
        self,
        *,
        request_id: str,
        agent: AgentConfig,
        request: HubRequest,
        initial_result: ProviderResult,
    ) -> ToolLoopRunResult:
        max_iterations = _max_tool_iterations(request, self.config.max_tool_iterations)
        metadata = ToolLoopMetadata(max_tool_iterations=max_iterations)
        if (
            max_iterations <= 0
            or not getattr(self.config, "tool_loop_enabled", True)
            or (
                _request_is_cline(request)
                and not getattr(self.config, "tool_loop_enabled_for_cline", False)
            )
        ):
            return ToolLoopRunResult(initial_result, metadata)

        current = initial_result
        messages = [dict(message) for message in request.messages]
        latency_seconds = 0.0
        seen_signatures: set[str] = set()
        while True:
            calls = valid_tool_calls(extract_tool_calls(current), metadata)
            if not calls:
                if metadata.tool_calls or metadata.tool_results:
                    current = replace_provider_result_raw(
                        current,
                        merge_tool_loop_metadata(
                            current.raw if isinstance(current.raw, dict) else {},
                            metadata,
                        ),
                    )
                return ToolLoopRunResult(current, metadata, latency_seconds)

            if not self.should_execute_tool_calls(request, calls):
                return ToolLoopRunResult(current, metadata, latency_seconds)

            if metadata.tool_iteration_count >= max_iterations:
                metadata.max_tool_iterations_reached = True
                stopped = max_loop_result(current, metadata)
                self.record_event(
                    "tool_loop_max_reached",
                    request_id=request_id,
                    request=request,
                    agent=agent.name,
                    provider=agent.provider,
                    model=agent.model,
                    tool_iteration_count=metadata.tool_iteration_count,
                )
                return ToolLoopRunResult(stopped, metadata, latency_seconds)

            signatures = [tool_call_signature(call) for call in calls]
            duplicate = next((signature for signature in signatures if signature in seen_signatures), None)
            if duplicate is not None:
                metadata.duplicate_tool_call_detected = True
                stopped = max_loop_result(current, metadata)
                self.record_event(
                    "tool_loop_duplicate_stopped",
                    request_id=request_id,
                    request=request,
                    agent=agent.name,
                    provider=agent.provider,
                    model=agent.model,
                    duplicate_signature=duplicate,
                    tool_iteration_count=metadata.tool_iteration_count,
                )
                return ToolLoopRunResult(stopped, metadata, latency_seconds)
            seen_signatures.update(signatures)

            metadata.tool_iteration_count += 1
            messages.append(assistant_message_from_result(current, calls))
            context = ToolExecutionContext(config=self.config, request=request)
            results = []
            for call in calls:
                result = self.pipeline.execute(call, context)
                result = compact_tool_result_for_loop(result)
                results.append(result)
                self.record_tool_result(agent.name, result.ok)
                metadata.tool_calls.append(
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": dict(call.arguments),
                        "iteration": metadata.tool_iteration_count,
                    }
                )
                metadata.tool_results.append(result.to_dict())
                messages.append(result.to_openai_message())

            self.record_event(
                "tool_loop_iteration",
                request_id=request_id,
                request=request,
                agent=agent.name,
                provider=agent.provider,
                model=agent.model,
                tool_calls=[call.name for call in calls],
                tool_results=[result.ok for result in results],
                tool_result_sizes=[
                    len(json.dumps(result.to_dict(), ensure_ascii=False, default=str))
                    for result in results
                ],
                tool_execution_ms=[result.to_dict().get("duration_ms") for result in results],
                tool_iteration_count=metadata.tool_iteration_count,
            )

            next_request = replace(
                request,
                messages=messages,
                raw=tool_loop_raw(request, metadata),
                stream=False,
                record_session=False,
            )
            started = time.perf_counter()
            current = self.chat_provider(agent, next_request)
            latency_seconds += time.perf_counter() - started

    def should_execute_tool_calls(self, request: HubRequest, calls: list[ToolCall]) -> bool:
        if _agent_runner_managed_request(request):
            return False
        if _request_option(request, "auto_execute_tools", "execute_tools") is True:
            return True
        raw = request.raw if isinstance(request.raw, dict) else {}
        hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
        compatibility = (
            hub.get("tool_compatibility")
            if isinstance(hub.get("tool_compatibility"), dict)
            else {}
        )
        if compatibility.get("client_owned_tools"):
            return False
        if _request_has_client_tool_specs(request) and not isinstance(raw.get("agent_hub_tools"), list):
            return False
        return all(self.registry.get(call.name) is not None for call in calls)


def tool_loop_raw(request: HubRequest, metadata: ToolLoopMetadata) -> dict[str, Any]:
    raw = dict(request.raw) if isinstance(request.raw, dict) else {}
    hub = dict(raw.get("agent_hub")) if isinstance(raw.get("agent_hub"), dict) else {}
    hub["tool_loop"] = metadata.to_dict()
    hub["auto_execute_tools"] = True
    raw["agent_hub"] = hub
    return raw


def replace_provider_result_raw(result: ProviderResult, raw: dict[str, Any]) -> ProviderResult:
    return ProviderResult(
        text=result.text,
        model=result.model,
        raw=raw,
        usage=dict(result.usage),
        finish_reason=result.finish_reason,
        citations=list(result.citations),
        search_results=list(result.search_results),
        related_questions=list(result.related_questions),
    )


def _max_tool_iterations(request: HubRequest, default: int) -> int:
    value = _request_option(request, "max_tool_iterations", "tool_loop_max_iterations")
    try:
        number = int(value if value is not None else default)
    except (TypeError, ValueError):
        number = default
    return max(0, min(number, 20))


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


def _agent_runner_managed_request(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    return isinstance(raw.get("agent_hub_runtime"), dict)


def _request_has_client_tool_specs(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    return bool(
        (isinstance(raw.get("tools"), list) and raw["tools"])
        or (isinstance(raw.get("functions"), list) and raw["functions"])
    )


def _ignore_tool_result(agent_name: str, ok: bool) -> None:
    return None


def _ignore_event(event_type: str, **data: Any) -> None:
    return None


__all__ = [
    "ToolLoopRunner",
    "ToolLoopRunResult",
    "replace_provider_result_raw",
    "tool_loop_raw",
]
