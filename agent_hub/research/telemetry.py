from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ResearchRun:
    task_id: str
    task_type: str = ""
    selected_model: str = ""
    candidate_models: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    context_files: list[str] = field(default_factory=list)
    context_token_count: int = 0
    latency_ms: float = 0.0
    cost_estimate: float = 0.0
    success: bool | None = None
    validation_score: float = 0.0
    retry_count: int = 0
    user_feedback: str = ""
    route: str = ""
    selected_agent: str = ""
    provider: str = ""
    event_type: str = "route"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def research_dir(state_dir: str | Path) -> Path:
    state = Path(state_dir)
    if state.name == "state":
        return state.parent / "research"
    return state / "research"


def runs_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "runs.jsonl"


def append_research_run(state_dir: str | Path, run: ResearchRun | dict[str, Any]) -> Path:
    path = runs_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = run.to_dict() if isinstance(run, ResearchRun) else dict(run)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_json_safe(data), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def record_research_route_start(
    state_dir: str | Path,
    *,
    request_id: str,
    request: Any,
    routing_decision: dict[str, Any] | None = None,
    candidates: list[str] | None = None,
) -> None:
    decision = routing_decision or {}
    try:
        usage = _context_usage(request)
        run = ResearchRun(
            task_id=request_id,
            task_type=str(decision.get("task_type") or getattr(request, "task", "") or ""),
            selected_model=str(decision.get("selected_model") or ""),
            candidate_models=_candidate_models(decision, candidates or []),
            input_tokens=int(decision.get("estimated_input_tokens") or usage.get("estimated_input_tokens") or 0),
            context_files=_context_files(request, usage),
            context_token_count=int(usage.get("context_tokens") or usage.get("estimated_input_tokens") or 0),
            route=str(getattr(request, "route", "") or ""),
            selected_agent=str(decision.get("selected_agent") or ""),
            provider=str(decision.get("selected_provider") or ""),
            event_type="route_started",
        )
        append_research_run(state_dir, run)
    except Exception:
        return


def record_research_outcome(
    state_dir: str | Path,
    *,
    request_id: str | None,
    request: Any,
    agent: Any,
    model: str,
    success: bool,
    latency_seconds: float | None,
    failover_attempts: int,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: float | None,
    task_type: str = "",
    validation_score: float | None = None,
    user_feedback: str = "",
) -> None:
    if not request_id:
        return
    try:
        usage = _context_usage(request)
        run = ResearchRun(
            task_id=request_id,
            task_type=task_type,
            selected_model=model or getattr(agent, "model", ""),
            candidate_models=[model or getattr(agent, "model", "")],
            input_tokens=max(0, int(input_tokens or 0)),
            output_tokens=max(0, int(output_tokens or 0)),
            context_files=_context_files(request, usage),
            context_token_count=int(usage.get("context_tokens") or usage.get("estimated_input_tokens") or input_tokens or 0),
            latency_ms=max(0.0, float(latency_seconds or 0.0) * 1000.0),
            cost_estimate=max(0.0, float(estimated_cost_usd or 0.0)),
            success=bool(success),
            validation_score=float(validation_score if validation_score is not None else (1.0 if success else 0.0)),
            retry_count=max(0, int(failover_attempts or 0)),
            user_feedback=user_feedback,
            route=str(getattr(request, "route", "") or ""),
            selected_agent=str(getattr(agent, "name", "") or ""),
            provider=str(getattr(agent, "provider", "") or ""),
            event_type="route_outcome",
        )
        append_research_run(state_dir, run)
    except Exception:
        return


def _context_usage(request: Any) -> dict[str, Any]:
    raw = getattr(request, "raw", {})
    raw = raw if isinstance(raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    usage = hub.get("context_usage") if isinstance(hub.get("context_usage"), dict) else {}
    return dict(usage)


def _context_files(request: Any, usage: dict[str, Any]) -> list[str]:
    for key in ("context_files", "files", "selected_files"):
        value = usage.get(key)
        if isinstance(value, list):
            return [str(item) for item in value[:200]]
    metadata = getattr(request, "metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    value = metadata.get("context_files")
    if isinstance(value, list):
        return [str(item) for item in value[:200]]
    return []


def _candidate_models(decision: dict[str, Any], candidate_agents: list[str]) -> list[str]:
    rows = decision.get("candidate_scores")
    if isinstance(rows, list):
        models = [str(row.get("model") or row.get("agent") or "") for row in rows if isinstance(row, dict)]
        return [model for model in models if model]
    return [str(item) for item in candidate_agents if item]


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


__all__ = [
    "ResearchRun",
    "append_research_run",
    "record_research_outcome",
    "record_research_route_start",
    "research_dir",
    "runs_path",
]
