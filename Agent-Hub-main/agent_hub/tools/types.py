from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


ToolExecutor = Callable[["ToolCall", "ToolExecutionContextLike"], "ToolResult"]


class ToolExecutionContextLike:
    workspace_dir: Any
    config: Any
    request: Any


@dataclass(slots=True)
class Tool:
    """Executable tool metadata plus its permission and schema contract.

    The shape intentionally mirrors MCP/OpenAI function metadata while keeping
    the executor provider-agnostic. Provider adapters should only serialize the
    metadata; execution always flows through ToolExecutionPipeline.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    executor: ToolExecutor
    read_only: bool = True
    permission: str = "read"
    output_schema: dict[str, Any] = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def to_agent_hub_spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
            "input_schema": self.input_schema,
            "output": self.output_schema,
            "permissions": self.effective_permissions(),
            "metadata": dict(self.metadata),
        }

    def effective_permissions(self) -> list[str]:
        if self.permissions:
            return list(self.permissions)
        return [self.permission] if self.permission else []


@dataclass(slots=True)
class ToolCall:
    """A provider-neutral request to execute one registered tool."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex}")
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_openai(cls, value: dict[str, Any]) -> "ToolCall":
        function = value.get("function") if isinstance(value.get("function"), dict) else {}
        args = function.get("arguments", {})
        if isinstance(args, str):
            import json

            try:
                parsed = json.loads(args)
            except json.JSONDecodeError:
                parsed = {}
            args = parsed
        return cls(
            id=str(value.get("id") or f"call_{uuid.uuid4().hex}"),
            name=str(function.get("name") or value.get("name") or ""),
            arguments=args if isinstance(args, dict) else {},
            raw=dict(value),
        )


@dataclass(slots=True)
class ToolResult:
    """A provider-neutral result that can be fed back as an OpenAI tool message."""

    call_id: str
    name: str
    ok: bool
    content: Any = None
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "ok": self.ok,
            "content": self.content,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round((self.finished_at - self.started_at) * 1000, 2),
            "metadata": self.metadata,
        }

    def to_openai_message(self) -> dict[str, Any]:
        import json

        return {
            "role": "tool",
            "tool_call_id": self.call_id,
            "content": json.dumps(self.to_dict(), ensure_ascii=False),
        }
