from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .observability import record_event


ADAPTIVE_STATE_FILE = "adaptive_learning.json"
MAX_RECENT_DECISIONS = 100
EXACT_SAMPLE_THRESHOLD = 5
TASK_SAMPLE_THRESHOLD = 10
GLOBAL_SAMPLE_THRESHOLD = 20


class AdaptiveLearningStore:
    """Persist compact outcome aggregates for adaptive routing and dashboards."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / ADAPTIVE_STATE_FILE

    def load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_state()
        if not isinstance(raw, dict):
            return _empty_state()
        state = _empty_state()
        for key in ("aggregates", "workflow_patterns", "role_agents", "request_index"):
            value = raw.get(key)
            if isinstance(value, dict):
                state[key] = value
        recent = raw.get("recent_decisions")
        if isinstance(recent, list):
            state["recent_decisions"] = [item for item in recent if isinstance(item, dict)][-MAX_RECENT_DECISIONS:]
        state["version"] = 1
        state["updated_at"] = _safe_float(raw.get("updated_at"), 0.0)
        return state

    def save(self, state: dict[str, Any]) -> None:
        payload = {
            "version": 1,
            "updated_at": time.time(),
            "aggregates": dict(state.get("aggregates") or {}),
            "workflow_patterns": dict(state.get("workflow_patterns") or {}),
            "role_agents": dict(state.get("role_agents") or {}),
            "request_index": dict(state.get("request_index") or {}),
            "recent_decisions": list(state.get("recent_decisions") or [])[-MAX_RECENT_DECISIONS:],
        }
        _atomic_write_text(self.path, json.dumps(payload, indent=2, ensure_ascii=False))

    def record_outcome(
        self,
        *,
        request_id: str | None,
        route: str,
        task_type: str,
        workflow_pattern: str,
        workflow_role: str,
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
        state = self.load()
        now = time.time()
        aggregate_keys = _aggregate_keys(
            agent.name,
            route=route,
            task_type=task_type,
            workflow_pattern=workflow_pattern,
            workflow_role=workflow_role,
        )
        for key in aggregate_keys:
            aggregate = _aggregate(
                state["aggregates"],
                key,
                agent=agent,
                model=model,
                route=route,
                task_type=task_type,
                workflow_pattern=workflow_pattern,
                workflow_role=workflow_role,
            )
            _apply_attempt(
                aggregate,
                success=success,
                latency_seconds=latency_seconds,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=estimated_cost_usd,
                failover_attempts=failover_attempts,
                error_type=error_type,
                now=now,
            )

        workflow_key = ""
        if workflow_pattern:
            workflow_key = _workflow_key(workflow_pattern)
            _aggregate(
                state["workflow_patterns"],
                workflow_key,
                agent=agent,
                model=model,
                route=route,
                task_type=task_type,
                workflow_pattern=workflow_pattern,
                workflow_role=workflow_role,
            )

        role_key = ""
        if workflow_role:
            role_key = _role_agent_key(workflow_role, agent.name)
            aggregate = _aggregate(
                state["role_agents"],
                role_key,
                agent=agent,
                model=model,
                route=route,
                task_type=task_type,
                workflow_pattern=workflow_pattern,
                workflow_role=workflow_role,
            )
            _apply_attempt(
                aggregate,
                success=success,
                latency_seconds=latency_seconds,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=estimated_cost_usd,
                failover_attempts=failover_attempts,
                error_type=error_type,
                now=now,
            )

        decision = {
            "time": now,
            "request_id": request_id,
            "route": route,
            "task_type": task_type,
            "workflow_pattern": workflow_pattern,
            "workflow_role": workflow_role,
            "agent": agent.name,
            "provider": agent.provider,
            "provider_type": agent.provider_type or agent.provider,
            "model": model,
            "success": success,
            "latency_ms": round(max(0.0, float(latency_seconds or 0.0)) * 1000, 2),
            "input_tokens": max(0, int(input_tokens or 0)),
            "output_tokens": max(0, int(output_tokens or 0)),
            "estimated_cost_usd": estimated_cost_usd,
            "failover_attempts": max(0, int(failover_attempts or 0)),
            "error_type": error_type or "",
            "final": bool(final),
        }
        state["recent_decisions"] = [*list(state.get("recent_decisions") or []), decision][-MAX_RECENT_DECISIONS:]
        if request_id and final:
            state["request_index"][request_id] = {
                "request_id": request_id,
                "aggregate_keys": aggregate_keys,
                "workflow_key": workflow_key,
                "role_key": role_key,
                "agent": agent.name,
                "provider": agent.provider,
                "model": model,
                "task_type": task_type,
                "route": route,
                "workflow_pattern": workflow_pattern,
                "workflow_role": workflow_role,
                "rating": None,
                "workflow_success": None,
                "updated_at": now,
            }
            state["request_index"] = _trim_request_index(state["request_index"])
        self.save(state)
        record_event(self.state_dir, "adaptive", {"type": "adaptive_outcome", **decision})

    def record_workflow_result(
        self,
        *,
        request_id: str,
        pattern: str,
        task_type: str,
        success: bool,
        latency_seconds: float,
        recovered_by_failover: bool,
        final_status: str,
        agent: str,
        provider: str,
        model: str,
    ) -> None:
        if not pattern:
            return
        state = self.load()
        key = _workflow_key(pattern)
        aggregate = state["workflow_patterns"].setdefault(
            key,
            {
                "scope": "workflow",
                "workflow_pattern": pattern,
                "agent": agent,
                "provider": provider,
                "model": model,
                "task_type": task_type,
            },
        )
        aggregate.setdefault("workflow_pattern", pattern)
        aggregate.setdefault("task_type", task_type)
        aggregate["attempts"] = int(aggregate.get("attempts", 0)) + 1
        existing = state["request_index"].get(request_id)
        previous_workflow_success = (
            existing.get("workflow_success")
            if isinstance(existing, dict) and isinstance(existing.get("workflow_success"), bool)
            else None
        )
        _replace_workflow_success(aggregate, previous_workflow_success, success)

        if isinstance(existing, dict):
            keys = [key for key in existing.get("aggregate_keys", []) if isinstance(key, str)]
            related = [state["aggregates"].get(key) for key in keys]
            role_key = existing.get("role_key") if isinstance(existing.get("role_key"), str) else ""
            if role_key:
                related.append(state["role_agents"].get(role_key))
            for item in related:
                if isinstance(item, dict):
                    _replace_workflow_success(item, previous_workflow_success, success)

        aggregate["recovered_by_failover_count"] = int(aggregate.get("recovered_by_failover_count", 0)) + int(bool(recovered_by_failover))
        aggregate["last_final_status"] = final_status
        aggregate["last_seen_at"] = time.time()
        if latency_seconds >= 0:
            aggregate["total_latency_ms"] = float(aggregate.get("total_latency_ms", 0.0)) + latency_seconds * 1000
            aggregate["latency_sample_count"] = int(aggregate.get("latency_sample_count", 0)) + 1
        if isinstance(existing, dict):
            existing["workflow_key"] = key
            existing["workflow_pattern"] = pattern
            existing["workflow_success"] = success
            existing["updated_at"] = time.time()
        self.save(state)
        record_event(
            self.state_dir,
            "adaptive",
            {
                "type": "adaptive_workflow_result",
                "request_id": request_id,
                "workflow_pattern": pattern,
                "task_type": task_type,
                "success": success,
                "recovered_by_failover": recovered_by_failover,
                "final_status": final_status,
            },
        )

    def record_feedback(
        self,
        *,
        request_id: str,
        rating: str,
        workflow_success: bool | None = None,
    ) -> dict[str, Any]:
        rating = str(rating or "").strip().lower()
        if rating not in {"up", "down"}:
            raise ValueError("rating must be 'up' or 'down'")
        state = self.load()
        target = state["request_index"].get(request_id)
        if not isinstance(target, dict):
            return {"ok": False, "matched": False, "request_id": request_id}

        keys = [key for key in target.get("aggregate_keys", []) if isinstance(key, str)]
        workflow_key = target.get("workflow_key") if isinstance(target.get("workflow_key"), str) else ""
        role_key = target.get("role_key") if isinstance(target.get("role_key"), str) else ""
        aggregates = [
            state["aggregates"].get(key)
            for key in keys
        ]
        if workflow_key:
            aggregates.append(state["workflow_patterns"].get(workflow_key))
        if role_key:
            aggregates.append(state["role_agents"].get(role_key))
        aggregates = [item for item in aggregates if isinstance(item, dict)]

        previous_rating = target.get("rating")
        for aggregate in aggregates:
            _replace_rating(aggregate, previous_rating, rating)
            if workflow_success is not None:
                _replace_workflow_success(
                    aggregate,
                    target.get("workflow_success"),
                    bool(workflow_success),
                )
        target["rating"] = rating
        if workflow_success is not None:
            target["workflow_success"] = bool(workflow_success)
        target["updated_at"] = time.time()
        self.save(state)
        record_event(
            self.state_dir,
            "adaptive",
            {
                "type": "adaptive_feedback",
                "request_id": request_id,
                "rating": rating,
                "workflow_success": workflow_success,
                "matched": True,
            },
        )
        return {
            "ok": True,
            "matched": True,
            "request_id": request_id,
            "rating": rating,
            "workflow_success": workflow_success,
        }

    def routing_bonus(
        self,
        agent_name: str,
        *,
        route: str,
        task_type: str,
        workflow_pattern: str = "",
        workflow_role: str = "",
    ) -> float:
        state = self.load()
        aggregates = state.get("aggregates") if isinstance(state.get("aggregates"), dict) else {}
        exact = aggregates.get(
            _aggregate_key(
                "exact",
                agent_name,
                route=route,
                task_type=task_type,
                workflow_pattern=workflow_pattern,
                workflow_role=workflow_role,
            )
        )
        if isinstance(exact, dict) and int(exact.get("attempts", 0)) >= EXACT_SAMPLE_THRESHOLD:
            return _adaptive_bonus(exact)
        task = aggregates.get(_aggregate_key("task", agent_name, task_type=task_type))
        if isinstance(task, dict) and int(task.get("attempts", 0)) >= TASK_SAMPLE_THRESHOLD:
            return _adaptive_bonus(task)
        global_stats = aggregates.get(_aggregate_key("global", agent_name))
        if isinstance(global_stats, dict) and int(global_stats.get("attempts", 0)) >= GLOBAL_SAMPLE_THRESHOLD:
            return _adaptive_bonus(global_stats)
        return 0.0

    def optimization_summary(self) -> dict[str, Any]:
        state = self.load()
        aggregates = [row for row in state.get("aggregates", {}).values() if isinstance(row, dict)]
        global_aggregates = [row for row in aggregates if str(row.get("key", "")).startswith("global|")]
        workflows = [row for row in state.get("workflow_patterns", {}).values() if isinstance(row, dict)]
        roles = [row for row in state.get("role_agents", {}).values() if isinstance(row, dict)]
        recent = list(state.get("recent_decisions") or [])[-25:]
        known_costs = [
            _safe_float(row.get("total_known_cost_usd"), 0.0) / max(1, int(row.get("known_cost_count", 0)))
            for row in global_aggregates or aggregates
            if int(row.get("known_cost_count", 0)) > 0
        ]
        latencies = [
            _safe_float(row.get("total_latency_ms"), 0.0) / max(1, int(row.get("latency_sample_count", 0)))
            for row in global_aggregates or aggregates
            if int(row.get("latency_sample_count", 0)) > 0
        ]
        return {
            "object": "agent_hub.optimization",
            "adaptive_learning_enabled": True,
            "sample_thresholds": {
                "exact": EXACT_SAMPLE_THRESHOLD,
                "task": TASK_SAMPLE_THRESHOLD,
                "global": GLOBAL_SAMPLE_THRESHOLD,
            },
            "workflow_success_rate": _workflow_success_rate(workflows),
            "model_win_rates": _model_win_rates(aggregates),
            "average_known_cost_usd": round(sum(known_costs) / len(known_costs), 6) if known_costs else None,
            "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            "failed_requests_recovered": sum(int(row.get("recovered_by_failover_count", 0)) for row in workflows),
            "best_providers": _best_providers(aggregates),
            "best_provider_by_workflow_role": _best_by_role(roles),
            "workflow_patterns": _workflow_rows(workflows),
            "recent_optimization_decisions": recent,
        }


def estimate_known_cost_usd(
    agent: AgentConfig,
    *,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    input_cost = _optional_cost(agent.cost_per_million_input)
    output_cost = _optional_cost(agent.cost_per_million_output)
    if input_cost is None and output_cost is None:
        return None
    total = 0.0
    if input_cost is not None:
        total += max(0, int(input_tokens or 0)) * input_cost / 1_000_000
    if output_cost is not None:
        total += max(0, int(output_tokens or 0)) * output_cost / 1_000_000
    return round(total, 8)


def _empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": 0.0,
        "aggregates": {},
        "workflow_patterns": {},
        "role_agents": {},
        "request_index": {},
        "recent_decisions": [],
    }


def _aggregate_keys(
    agent_name: str,
    *,
    route: str,
    task_type: str,
    workflow_pattern: str,
    workflow_role: str,
) -> list[str]:
    return [
        _aggregate_key(
            "exact",
            agent_name,
            route=route,
            task_type=task_type,
            workflow_pattern=workflow_pattern,
            workflow_role=workflow_role,
        ),
        _aggregate_key("task", agent_name, task_type=task_type),
        _aggregate_key("global", agent_name),
    ]


def _aggregate_key(
    scope: str,
    agent_name: str,
    *,
    route: str = "",
    task_type: str = "",
    workflow_pattern: str = "",
    workflow_role: str = "",
) -> str:
    parts = [scope, agent_name]
    if scope == "exact":
        parts.extend([route or "default", task_type or "general", workflow_pattern or "none", workflow_role or "none"])
    elif scope == "task":
        parts.append(task_type or "general")
    return "|".join(parts)


def _workflow_key(pattern: str) -> str:
    return f"workflow|{pattern or 'unknown'}"


def _role_agent_key(role: str, agent_name: str) -> str:
    return f"role|{role or 'unknown'}|{agent_name}"


def _aggregate(
    bucket: dict[str, Any],
    key: str,
    *,
    agent: AgentConfig,
    model: str,
    route: str,
    task_type: str,
    workflow_pattern: str,
    workflow_role: str,
) -> dict[str, Any]:
    row = bucket.setdefault(
        key,
        {
            "key": key,
            "agent": agent.name,
            "provider": agent.provider,
            "provider_type": agent.provider_type or agent.provider,
            "model": model or agent.model,
            "route": route,
            "task_type": task_type,
            "workflow_pattern": workflow_pattern,
            "workflow_role": workflow_role,
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "thumbs_up": 0,
            "thumbs_down": 0,
            "workflow_successes": 0,
            "workflow_failures": 0,
            "total_latency_ms": 0.0,
            "latency_sample_count": 0,
            "total_known_cost_usd": 0.0,
            "known_cost_count": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "recovered_by_failover_count": 0,
            "last_error_type": "",
            "last_seen_at": 0.0,
        },
    )
    row["agent"] = agent.name
    row["provider"] = agent.provider
    row["provider_type"] = agent.provider_type or agent.provider
    row["model"] = model or agent.model
    row.setdefault("route", route)
    row.setdefault("task_type", task_type)
    row.setdefault("workflow_pattern", workflow_pattern)
    row.setdefault("workflow_role", workflow_role)
    return row


def _apply_attempt(
    aggregate: dict[str, Any],
    *,
    success: bool,
    latency_seconds: float | None,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: float | None,
    failover_attempts: int,
    error_type: str | None,
    now: float,
) -> None:
    aggregate["attempts"] = int(aggregate.get("attempts", 0)) + 1
    if success:
        aggregate["successes"] = int(aggregate.get("successes", 0)) + 1
    else:
        aggregate["failures"] = int(aggregate.get("failures", 0)) + 1
    latency = _safe_float(latency_seconds, 0.0)
    if latency > 0:
        aggregate["total_latency_ms"] = _safe_float(aggregate.get("total_latency_ms"), 0.0) + latency * 1000
        aggregate["latency_sample_count"] = int(aggregate.get("latency_sample_count", 0)) + 1
    if estimated_cost_usd is not None:
        aggregate["total_known_cost_usd"] = _safe_float(aggregate.get("total_known_cost_usd"), 0.0) + max(0.0, float(estimated_cost_usd))
        aggregate["known_cost_count"] = int(aggregate.get("known_cost_count", 0)) + 1
    aggregate["total_input_tokens"] = int(aggregate.get("total_input_tokens", 0)) + max(0, int(input_tokens or 0))
    aggregate["total_output_tokens"] = int(aggregate.get("total_output_tokens", 0)) + max(0, int(output_tokens or 0))
    aggregate["recovered_by_failover_count"] = int(aggregate.get("recovered_by_failover_count", 0)) + int(success and failover_attempts > 0)
    if error_type:
        aggregate["last_error_type"] = error_type
    aggregate["last_seen_at"] = now


def _apply_workflow_success(aggregate: dict[str, Any], success: bool) -> None:
    key = "workflow_successes" if success else "workflow_failures"
    aggregate[key] = int(aggregate.get(key, 0)) + 1


def _replace_rating(aggregate: dict[str, Any], previous: Any, current: str) -> None:
    if previous == current:
        return
    if previous == "up":
        aggregate["thumbs_up"] = max(0, int(aggregate.get("thumbs_up", 0)) - 1)
    if previous == "down":
        aggregate["thumbs_down"] = max(0, int(aggregate.get("thumbs_down", 0)) - 1)
    if current == "up":
        aggregate["thumbs_up"] = int(aggregate.get("thumbs_up", 0)) + 1
    if current == "down":
        aggregate["thumbs_down"] = int(aggregate.get("thumbs_down", 0)) + 1


def _replace_workflow_success(aggregate: dict[str, Any], previous: Any, current: bool) -> None:
    if previous is current:
        return
    if previous is True:
        aggregate["workflow_successes"] = max(0, int(aggregate.get("workflow_successes", 0)) - 1)
    if previous is False:
        aggregate["workflow_failures"] = max(0, int(aggregate.get("workflow_failures", 0)) - 1)
    _apply_workflow_success(aggregate, current)


def _adaptive_bonus(aggregate: dict[str, Any]) -> float:
    attempts = int(aggregate.get("attempts", 0))
    successes = int(aggregate.get("successes", 0))
    thumbs_up = int(aggregate.get("thumbs_up", 0))
    thumbs_down = int(aggregate.get("thumbs_down", 0))
    workflow_successes = int(aggregate.get("workflow_successes", 0))
    workflow_failures = int(aggregate.get("workflow_failures", 0))
    success = (successes + 1) / max(1, attempts + 2)
    feedback = (thumbs_up + 1) / max(1, thumbs_up + thumbs_down + 2)
    workflow = (workflow_successes + 1) / max(1, workflow_successes + workflow_failures + 2)
    avg_latency_ms = (
        _safe_float(aggregate.get("total_latency_ms"), 0.0)
        / max(1, int(aggregate.get("latency_sample_count", 0)))
    )
    latency = 1 / (1 + avg_latency_ms / 15000)
    if int(aggregate.get("known_cost_count", 0)) > 0:
        avg_cost = _safe_float(aggregate.get("total_known_cost_usd"), 0.0) / max(1, int(aggregate.get("known_cost_count", 0)))
        cost = 1 / (1 + avg_cost / 0.05)
    else:
        cost = 0.5
    quality = (0.55 * success) + (0.20 * feedback) + (0.15 * workflow) + (0.05 * latency) + (0.05 * cost)
    return round(_clamp((quality - 0.5) * 20, -10.0, 15.0), 4)


def _workflow_success_rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successes = sum(int(row.get("workflow_successes", 0)) for row in rows)
    failures = sum(int(row.get("workflow_failures", 0)) for row in rows)
    total = successes + failures
    return {
        "successes": successes,
        "failures": failures,
        "attempts": total,
        "rate": round(successes / total, 4) if total else 0.0,
    }


def _model_win_rates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    task_rows = [row for row in rows if str(row.get("key", "")).startswith("task|")]
    result: list[dict[str, Any]] = []
    for row in task_rows:
        attempts = int(row.get("attempts", 0))
        if attempts <= 0:
            continue
        result.append(
            {
                "task_type": row.get("task_type") or "general",
                "agent": row.get("agent"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "attempts": attempts,
                "success_rate": round(int(row.get("successes", 0)) / attempts, 4),
                "adaptive_bonus": _adaptive_bonus(row) if attempts >= TASK_SAMPLE_THRESHOLD else 0.0,
            }
        )
    return sorted(result, key=lambda row: (-float(row["success_rate"]), -int(row["attempts"]), str(row["agent"])))[:25]


def _best_providers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    global_rows = [
        row for row in rows
        if str(row.get("key", "")).startswith("global|") and int(row.get("attempts", 0)) > 0
    ]
    return [
        {
            "agent": row.get("agent"),
            "provider": row.get("provider"),
            "model": row.get("model"),
            "attempts": row.get("attempts", 0),
            "success_rate": round(int(row.get("successes", 0)) / max(1, int(row.get("attempts", 0))), 4),
            "adaptive_bonus": _adaptive_bonus(row) if int(row.get("attempts", 0)) >= GLOBAL_SAMPLE_THRESHOLD else 0.0,
        }
        for row in sorted(global_rows, key=lambda item: (-_adaptive_bonus(item), -int(item.get("successes", 0))))[:10]
    ]


def _best_by_role(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        role = str(row.get("workflow_role") or "").strip() or "unknown"
        attempts = int(row.get("attempts", 0))
        if attempts <= 0:
            continue
        candidate = {
            "role": role,
            "agent": row.get("agent"),
            "provider": row.get("provider"),
            "model": row.get("model"),
            "attempts": attempts,
            "success_rate": round(int(row.get("successes", 0)) / max(1, attempts), 4),
            "average_latency_ms": round(_safe_float(row.get("total_latency_ms"), 0.0) / max(1, int(row.get("latency_sample_count", 0))), 2),
        }
        current = best.get(role)
        if current is None or (candidate["success_rate"], candidate["attempts"]) > (current["success_rate"], current["attempts"]):
            best[role] = candidate
    return best


def _workflow_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        successes = int(row.get("workflow_successes", 0))
        failures = int(row.get("workflow_failures", 0))
        attempts = successes + failures
        result.append(
            {
                "workflow_pattern": row.get("workflow_pattern") or str(row.get("key", "")).split("|")[-1],
                "attempts": attempts or int(row.get("attempts", 0)),
                "success_rate": round(successes / attempts, 4) if attempts else 0.0,
                "average_latency_ms": round(_safe_float(row.get("total_latency_ms"), 0.0) / max(1, int(row.get("latency_sample_count", 0))), 2),
                "recovered_by_failover_count": int(row.get("recovered_by_failover_count", 0)),
            }
        )
    return sorted(result, key=lambda item: (-float(item["success_rate"]), -int(item["attempts"]), str(item["workflow_pattern"])))


def _trim_request_index(index: dict[str, Any]) -> dict[str, Any]:
    if len(index) <= 500:
        return index
    rows = [
        (key, value)
        for key, value in index.items()
        if isinstance(value, dict)
    ]
    rows.sort(key=lambda item: _safe_float(item[1].get("updated_at"), 0.0), reverse=True)
    return dict(rows[:500])


def _optional_cost(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            temp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


__all__ = [
    "AdaptiveLearningStore",
    "estimate_known_cost_usd",
]
