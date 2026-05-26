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
    name: str
    description: str
    input_schema: dict[str, Any]
    executor: ToolExecutor
    read_only: bool = True
    permission: str = "read"
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


@dataclass(slots=True)
class ToolCall:
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
