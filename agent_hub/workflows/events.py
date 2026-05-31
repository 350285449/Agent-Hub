from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..observability import record_event


WorkflowEventSink = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class WorkflowEventRecorder:
    """Records workflow events while keeping execution code free of JSONL details."""

    state_dir: str | Path

    def emit(self, event_sink: WorkflowEventSink | None, event_type: str, **data: Any) -> None:
        if event_sink is None:
            return
        try:
            event_sink({"type": event_type, **data})
        except Exception:
            return

    def record(self, event_type: str, **data: Any) -> None:
        try:
            record_event(self.state_dir, "workflows", {"type": event_type, **data})
        except Exception:
            return


__all__ = ["WorkflowEventRecorder", "WorkflowEventSink"]
