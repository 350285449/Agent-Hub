from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import HubConfig
from ..events import TOOL_EXECUTED, record_internal_event
from ..models import HubRequest
from ..observability import record_event
from .permissions import ToolPermissionLayer
from .registry import ToolRegistry
from .types import ToolCall, ToolResult


@dataclass(slots=True)
class ToolExecutionContext:
    config: HubConfig
    request: HubRequest | None = None

    @property
    def workspace_dir(self) -> Path:
        raw = self.request.raw if self.request is not None and isinstance(self.request.raw, dict) else {}
        value = raw.get("workspace_dir") or self.config.workspace_dir
        return Path(value).expanduser().resolve()


class ToolExecutionPipeline:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        permission_layer: ToolPermissionLayer | None = None,
    ) -> None:
        self.registry = registry
        self.permission_layer = permission_layer

    def execute(self, call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        started = time.time()
        tool = self.registry.get(call.name)
        if tool is None:
            result = ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=f"Unknown tool {call.name!r}",
                started_at=started,
                finished_at=time.time(),
            )
            _record(context, "tool_executed", result)
            return result
        if tool.name != call.name:
            call = ToolCall(
                id=call.id,
                name=tool.name,
                arguments=dict(call.arguments),
                raw={**call.raw, "alias": call.name},
            )
        permission_layer = self.permission_layer or ToolPermissionLayer(context.config, context.request)
        denied = permission_layer.check(tool, call)
        if denied is not None:
            denied.started_at = started
            denied.finished_at = time.time()
            _record(context, "tool_denied", denied)
            return denied
        try:
            result = tool.executor(call, context)
        except Exception as exc:
            result = ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=str(exc),
                started_at=started,
                finished_at=time.time(),
            )
        result.started_at = started
        result.finished_at = time.time()
        _record(context, "tool_executed", result)
        return result


def openai_tool_specs(registry: ToolRegistry) -> list[dict[str, Any]]:
    return [tool.to_openai_tool() for tool in registry.list()]


def _record(context: ToolExecutionContext, event_type: str, result: ToolResult) -> None:
    try:
        record_event(
            context.config.state_dir,
            "tools",
            {
                "type": event_type,
                "tool": result.name,
                "call_id": result.call_id,
                "ok": result.ok,
                "error": result.error,
                "metadata": result.metadata,
            },
        )
        record_internal_event(
            context.config.state_dir,
            TOOL_EXECUTED,
            tool=result.name,
            call_id=result.call_id,
            ok=result.ok,
            error=result.error,
            event_type=event_type,
            duration_ms=result.to_dict().get("duration_ms"),
            result_size=len(result.to_openai_message().get("content", "")),
            session_id=context.request.session_id if context.request is not None else None,
            route=context.request.route if context.request is not None else None,
        )
    except Exception:
        return
