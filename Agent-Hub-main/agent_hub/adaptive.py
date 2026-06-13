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
WORKFLOW_UPGRADE_SAMPLE_THRESHOLD = 5
WORKFLOW_UPGRADE_MIN_SUCCESS_RATE = 0.70
WORKFLOW_UPGRADE_MIN_DELTA = 0.15
WORKFLOW_PATTERN_COMPLEXITY = {
    "direct_route": 0,
    "single_worker": 1,
    "planned_worker": 2,
    "reviewed_worker": 3,
    "team_reviewed": 4,
}


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
        retry_count: int | None = None,
        final: bool = False,
    ) -> None:
        state = self.load()
        now = time.time()
        normalized_retry_count = max(
            0,
            int(failover_attempts if retry_count is None else retry_count or 0),
        )
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
                retry_count=normalized_retry_count,
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
                retry_count=normalized_retry_count,
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
            "retry_count": normalized_retry_count,
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
                "retry_count": normalized_retry_count,
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
        retry_count: int = 0,
        estimated_cost_usd: float | None = None,
    ) -> None:
        if not pattern:
            return
        state = self.load()
        task_type = str(task_type or "general").strip().lower() or "general"
        retry_count = max(0, int(retry_count or 0))
        key = _workflow_key(pattern)
        task_key = _workflow_task_key(pattern, task_type)
        existing = state["request_index"].get(request_id)
        previous_workflow_success = (
            existing.get("workflow_success")
            if isinstance(existing, dict) and isinstance(existing.get("workflow_success"), bool)
            else None
        )
        workflow_keys = [key, task_key]
        for workflow_key in workflow_keys:
            scope = "workflow_task" if workflow_key == task_key else "workflow"
            aggregate = state["workflow_patterns"].setdefault(
                workflow_key,
                {
                    "key": workflow_key,
                    "scope": scope,
                    "workflow_pattern": pattern,
                    "agent": agent,
                    "provider": provider,
                    "model": model,
                    "task_type": task_type,
                    "attempts": 0,
                    "workflow_successes": 0,
                    "workflow_failures": 0,
                    "recovered_by_failover_count": 0,
                    "total_latency_ms": 0.0,
                    "latency_sample_count": 0,
                    "total_known_cost_usd": 0.0,
                    "known_cost_count": 0,
                    "total_retry_count": 0,
                },
            )
            aggregate["key"] = workflow_key
            aggregate["scope"] = scope
            aggregate["workflow_pattern"] = pattern
            aggregate["task_type"] = task_type
            aggregate["agent"] = agent
            aggregate["provider"] = provider
            aggregate["model"] = model
            aggregate["attempts"] = int(aggregate.get("attempts", 0)) + 1
            _replace_workflow_success(aggregate, previous_workflow_success, success)
            aggregate["recovered_by_failover_count"] = int(aggregate.get("recovered_by_failover_count", 0)) + int(bool(recovered_by_failover))
            aggregate["total_retry_count"] = int(aggregate.get("total_retry_count", 0)) + retry_count
            aggregate["last_final_status"] = final_status
            aggregate["last_seen_at"] = time.time()
            if latency_seconds >= 0:
                aggregate["total_latency_ms"] = float(aggregate.get("total_latency_ms", 0.0)) + latency_seconds * 1000
                aggregate["latency_sample_count"] = int(aggregate.get("latency_sample_count", 0)) + 1
            if estimated_cost_usd is not None:
                aggregate["total_known_cost_usd"] = float(aggregate.get("total_known_cost_usd", 0.0)) + max(
                    0.0,
                    float(estimated_cost_usd),
                )
                aggregate["known_cost_count"] = int(aggregate.get("known_cost_count", 0)) + 1

        if isinstance(existing, dict):
            keys = [key for key in existing.get("aggregate_keys", []) if isinstance(key, str)]
            related = [state["aggregates"].get(key) for key in keys]
            role_key = existing.get("role_key") if isinstance(existing.get("role_key"), str) else ""
            if role_key:
                related.append(state["role_agents"].get(role_key))
            for item in related:
                if isinstance(item, dict):
                    _replace_workflow_success(item, previous_workflow_success, success)

        if isinstance(existing, dict):
            existing["workflow_key"] = key
            existing["workflow_keys"] = workflow_keys
            existing["workflow_pattern"] = pattern
            existing["workflow_success"] = success
            existing["workflow_retry_count"] = retry_count
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
                "retry_count": retry_count,
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
        workflow_keys = [
            key
            for key in target.get("workflow_keys", [])
            if isinstance(key, str) and key
        ]
        workflow_key = target.get("workflow_key") if isinstance(target.get("workflow_key"), str) else ""
        if workflow_key and workflow_key not in workflow_keys:
            workflow_keys.append(workflow_key)
        role_key = target.get("role_key") if isinstance(target.get("role_key"), str) else ""
        aggregates = [
            state["aggregates"].get(key)
            for key in keys
        ]
        for key in workflow_keys:
            aggregates.append(state["workflow_patterns"].get(key))
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
        return float(
            self.routing_signal(
                agent_name,
                route=route,
                task_type=task_type,
                workflow_pattern=workflow_pattern,
                workflow_role=workflow_role,
            ).get("adaptive_bonus", 0.0)
        )

    def routing_signal(
        self,
        agent_name: str,
        *,
        route: str,
        task_type: str,
        workflow_pattern: str = "",
        workflow_role: str = "",
    ) -> dict[str, Any]:
        """Return the active adaptive signal, including cold-start scorecards."""

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
        task = aggregates.get(_aggregate_key("task", agent_name, task_type=task_type))
        global_stats = aggregates.get(_aggregate_key("global", agent_name))
        candidates = [
            ("exact", exact, EXACT_SAMPLE_THRESHOLD),
            ("task", task, TASK_SAMPLE_THRESHOLD),
            ("global", global_stats, GLOBAL_SAMPLE_THRESHOLD),
        ]
        for scope, row, threshold in candidates:
            if isinstance(row, dict) and int(row.get("attempts", 0)) >= threshold:
                return _routing_signal_from_row(
                    row,
                    scope=scope,
                    threshold=threshold,
                    active=True,
                    agent_name=agent_name,
                    route=route,
                    task_type=task_type,
                    workflow_pattern=workflow_pattern,
                    workflow_role=workflow_role,
                )
        for scope, row, threshold in candidates:
            if isinstance(row, dict):
                return _routing_signal_from_row(
                    row,
                    scope=scope,
                    threshold=threshold,
                    active=False,
                    agent_name=agent_name,
                    route=route,
                    task_type=task_type,
                    workflow_pattern=workflow_pattern,
                    workflow_role=workflow_role,
                )
        return {
            "agent": agent_name,
            "route": route,
            "task_type": task_type or "general",
            "workflow_pattern": workflow_pattern,
            "workflow_role": workflow_role,
            "scope": "none",
            "active": False,
            "sample_threshold": EXACT_SAMPLE_THRESHOLD,
            "samples_needed": EXACT_SAMPLE_THRESHOLD,
            "attempts": 0,
            "adaptive_bonus": 0.0,
            "scorecard": _adaptive_scorecard({}),
            "summary": "No adaptive samples yet.",
        }

    def workflow_upgrade(self, current_pattern: str, *, task_type: str) -> dict[str, Any] | None:
        current_pattern = str(current_pattern or "").strip().lower()
        current_rank = WORKFLOW_PATTERN_COMPLEXITY.get(current_pattern)
        if current_rank is None:
            return None
        state = self.load()
        workflows = [
            row
            for row in state.get("workflow_patterns", {}).values()
            if isinstance(row, dict) and _workflow_scope(row) == "workflow"
        ]
        current = _workflow_pattern_row(workflows, current_pattern)
        if current is None or _workflow_attempts(current) < WORKFLOW_UPGRADE_SAMPLE_THRESHOLD:
            return None
        current_rate = _workflow_rate(current)
        candidates: list[dict[str, Any]] = []
        for row in workflows:
            pattern = _workflow_pattern_name(row)
            rank = WORKFLOW_PATTERN_COMPLEXITY.get(pattern)
            if rank is None or rank <= current_rank:
                continue
            attempts = _workflow_attempts(row)
            if attempts < WORKFLOW_UPGRADE_SAMPLE_THRESHOLD:
                continue
            rate = _workflow_rate(row)
            if rate < WORKFLOW_UPGRADE_MIN_SUCCESS_RATE:
                continue
            if rate < current_rate + WORKFLOW_UPGRADE_MIN_DELTA:
                continue
            candidates.append(
                {
                    "pattern": pattern,
                    "task_type": task_type,
                    "attempts": attempts,
                    "success_rate": round(rate, 4),
                    "baseline_pattern": current_pattern,
                    "baseline_attempts": _workflow_attempts(current),
                    "baseline_success_rate": round(current_rate, 4),
                    "min_delta": WORKFLOW_UPGRADE_MIN_DELTA,
                }
            )
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda row: (
                WORKFLOW_PATTERN_COMPLEXITY.get(str(row.get("pattern") or ""), 999),
                -float(row.get("success_rate", 0.0)),
                -int(row.get("attempts", 0)),
            ),
        )[0]

    def optimization_summary(self) -> dict[str, Any]:
        state = self.load()
        aggregates = [row for row in state.get("aggregates", {}).values() if isinstance(row, dict)]
        global_aggregates = [row for row in aggregates if str(row.get("key", "")).startswith("global|")]
        workflow_state_rows = [row for row in state.get("workflow_patterns", {}).values() if isinstance(row, dict)]
        workflows = [row for row in workflow_state_rows if _workflow_scope(row) == "workflow"]
        workflow_tasks = [row for row in workflow_state_rows if _workflow_scope(row) == "workflow_task"]
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
        total_retries = sum(int(row.get("total_retry_count", 0)) for row in workflows)
        retry_attempts = sum(_workflow_attempts(row) for row in workflows)
        workflow_analytics = _workflow_analytics(aggregates, workflow_tasks)
        return {
            "object": "agent_hub.optimization",
            "adaptive_learning_enabled": True,
            "sample_thresholds": {
                "exact": EXACT_SAMPLE_THRESHOLD,
                "task": TASK_SAMPLE_THRESHOLD,
                "global": GLOBAL_SAMPLE_THRESHOLD,
                "workflow_upgrade": WORKFLOW_UPGRADE_SAMPLE_THRESHOLD,
            },
            "workflow_upgrade_policy": {
                "min_success_rate": WORKFLOW_UPGRADE_MIN_SUCCESS_RATE,
                "min_delta": WORKFLOW_UPGRADE_MIN_DELTA,
            },
            "workflow_success_rate": _workflow_success_rate(workflows),
            "model_win_rates": _model_win_rates(aggregates),
            "task_model_winners": _task_model_winners(aggregates),
            "model_scorecards": _model_scorecards(aggregates),
            "average_known_cost_usd": round(sum(known_costs) / len(known_costs), 6) if known_costs else None,
            "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            "total_retries": total_retries,
            "average_retries": round(total_retries / retry_attempts, 4) if retry_attempts else 0.0,
            "failed_requests_recovered": sum(int(row.get("recovered_by_failover_count", 0)) for row in workflows),
            "best_providers": _best_providers(aggregates),
            "most_effective_providers": _most_effective_providers(aggregates),
            "best_provider_by_workflow_role": _best_by_role(roles),
            "role_model_winners": _best_by_role(roles),
            "workflow_patterns": _workflow_rows(workflows),
            "workflow_analytics": workflow_analytics,
            "dashboard": _dashboard_summary(aggregates, workflows, roles, workflow_analytics),
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


def _workflow_task_key(pattern: str, task_type: str) -> str:
    return f"workflow_task|{pattern or 'unknown'}|{_key_part(task_type or 'general')}"


def _role_agent_key(role: str, agent_name: str) -> str:
    return f"role|{role or 'unknown'}|{agent_name}"


def _key_part(value: str) -> str:
    return str(value or "unknown").strip().lower().replace("|", "/") or "unknown"


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
            "total_retry_count": 0,
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
    retry_count: int,
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
    aggregate["total_retry_count"] = int(aggregate.get("total_retry_count", 0)) + max(0, int(retry_count or 0))
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


def _routing_signal_from_row(
    row: dict[str, Any],
    *,
    scope: str,
    threshold: int,
    active: bool,
    agent_name: str,
    route: str,
    task_type: str,
    workflow_pattern: str,
    workflow_role: str,
) -> dict[str, Any]:
    attempts = int(row.get("attempts", 0))
    scorecard = _adaptive_scorecard(row)
    bonus = _adaptive_bonus(row) if active else 0.0
    success_pct = round(float(scorecard["success_rate"]) * 100, 1)
    if active:
        summary = (
            f"{scope} adaptive signal from {attempts} sample(s): "
            f"{success_pct}% success, bonus {bonus:+.2f}."
        )
    else:
        summary = (
            f"{scope} adaptive samples are warming up "
            f"({attempts}/{threshold}); no routing bonus yet."
        )
    return {
        "agent": row.get("agent") or agent_name,
        "provider": row.get("provider"),
        "provider_type": row.get("provider_type"),
        "model": row.get("model"),
        "route": route,
        "task_type": task_type or row.get("task_type") or "general",
        "workflow_pattern": workflow_pattern or row.get("workflow_pattern") or "",
        "workflow_role": workflow_role or row.get("workflow_role") or "",
        "scope": scope,
        "active": active,
        "sample_threshold": threshold,
        "samples_needed": max(0, threshold - attempts),
        "attempts": attempts,
        "adaptive_bonus": bonus,
        "scorecard": scorecard,
        "summary": summary,
    }


def _adaptive_scorecard(aggregate: dict[str, Any]) -> dict[str, Any]:
    attempts = int(aggregate.get("attempts", 0))
    successes = int(aggregate.get("successes", 0))
    failures = int(aggregate.get("failures", 0))
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
        avg_cost = None
        cost = 0.5
    quality = (0.55 * success) + (0.20 * feedback) + (0.15 * workflow) + (0.05 * latency) + (0.05 * cost)
    return {
        "attempts": attempts,
        "successes": successes,
        "failures": failures,
        "total_retries": int(aggregate.get("total_retry_count", 0)),
        "average_retries": round(int(aggregate.get("total_retry_count", 0)) / max(1, attempts), 4),
        "success_rate": round(successes / attempts, 4) if attempts else 0.0,
        "smoothed_success_rate": round(success, 4),
        "thumbs_up": thumbs_up,
        "thumbs_down": thumbs_down,
        "feedback_rate": round(thumbs_up / max(1, thumbs_up + thumbs_down), 4) if thumbs_up or thumbs_down else 0.0,
        "smoothed_feedback_rate": round(feedback, 4),
        "workflow_successes": workflow_successes,
        "workflow_failures": workflow_failures,
        "workflow_success_rate": round(
            workflow_successes / max(1, workflow_successes + workflow_failures),
            4,
        )
        if workflow_successes or workflow_failures
        else 0.0,
        "smoothed_workflow_success_rate": round(workflow, 4),
        "average_latency_ms": round(avg_latency_ms, 2),
        "latency_score": round(latency, 4),
        "average_known_cost_usd": round(avg_cost, 8) if avg_cost is not None else None,
        "cost_score": round(cost, 4),
        "quality_score": round(quality, 4),
    }


def _adaptive_bonus(aggregate: dict[str, Any]) -> float:
    quality = float(_adaptive_scorecard(aggregate)["quality_score"])
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
                "average_retries": round(int(row.get("total_retry_count", 0)) / max(1, attempts), 4),
                "average_latency_ms": round(_safe_float(row.get("total_latency_ms"), 0.0) / max(1, int(row.get("latency_sample_count", 0))), 2),
                "average_known_cost_usd": (
                    round(_safe_float(row.get("total_known_cost_usd"), 0.0) / max(1, int(row.get("known_cost_count", 0))), 8)
                    if int(row.get("known_cost_count", 0)) > 0
                    else None
                ),
                "adaptive_bonus": _adaptive_bonus(row) if attempts >= TASK_SAMPLE_THRESHOLD else 0.0,
                "scorecard": _adaptive_scorecard(row),
            }
        )
    return sorted(result, key=lambda row: (-float(row["success_rate"]), -int(row["attempts"]), str(row["agent"])))[:25]


def _task_model_winners(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    winners: dict[str, dict[str, Any]] = {}
    for row in _model_win_rates(rows):
        task_type = str(row.get("task_type") or "general")
        current = winners.get(task_type)
        candidate = {
            "task_type": task_type,
            "agent": row.get("agent"),
            "provider": row.get("provider"),
            "model": row.get("model"),
            "attempts": row.get("attempts", 0),
            "success_rate": row.get("success_rate", 0.0),
            "average_latency_ms": row.get("average_latency_ms", 0.0),
            "average_known_cost_usd": row.get("average_known_cost_usd"),
            "adaptive_bonus": row.get("adaptive_bonus", 0.0),
        }
        if current is None or (
            float(candidate["success_rate"]),
            int(candidate["attempts"]),
            float(candidate["adaptive_bonus"]),
        ) > (
            float(current.get("success_rate", 0.0)),
            int(current.get("attempts", 0)),
            float(current.get("adaptive_bonus", 0.0)),
        ):
            winners[task_type] = candidate
    return winners


def _model_scorecards(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("key", ""))
        if not (key.startswith("task|") or key.startswith("global|")):
            continue
        attempts = int(row.get("attempts", 0))
        if attempts <= 0:
            continue
        scorecard = _adaptive_scorecard(row)
        result.append(
            {
                "scope": "task" if key.startswith("task|") else "global",
                "task_type": row.get("task_type") or "general",
                "agent": row.get("agent"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "adaptive_bonus": _adaptive_bonus(row),
                "scorecard": scorecard,
            }
        )
    return sorted(
        result,
        key=lambda row: (
            -float(row["scorecard"].get("quality_score", 0.0)),
            -int(row["scorecard"].get("attempts", 0)),
            str(row.get("agent")),
        ),
    )[:25]


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


def _most_effective_providers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    providers: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not str(row.get("key", "")).startswith("global|"):
            continue
        provider = str(row.get("provider") or row.get("provider_type") or "").strip()
        if not provider:
            continue
        target = providers.setdefault(
            provider,
            {
                "provider": provider,
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "total_latency_ms": 0.0,
                "latency_sample_count": 0,
                "total_known_cost_usd": 0.0,
                "known_cost_count": 0,
                "agents": set(),
                "models": set(),
            },
        )
        target["attempts"] += int(row.get("attempts", 0))
        target["successes"] += int(row.get("successes", 0))
        target["failures"] += int(row.get("failures", 0))
        target["total_latency_ms"] += _safe_float(row.get("total_latency_ms"), 0.0)
        target["latency_sample_count"] += int(row.get("latency_sample_count", 0))
        target["total_known_cost_usd"] += _safe_float(row.get("total_known_cost_usd"), 0.0)
        target["known_cost_count"] += int(row.get("known_cost_count", 0))
        if row.get("agent"):
            target["agents"].add(str(row.get("agent")))
        if row.get("model"):
            target["models"].add(str(row.get("model")))
    result: list[dict[str, Any]] = []
    for row in providers.values():
        attempts = int(row["attempts"])
        if attempts <= 0:
            continue
        result.append(
            {
                "provider": row["provider"],
                "attempts": attempts,
                "success_rate": round(int(row["successes"]) / attempts, 4),
                "failure_rate": round(int(row["failures"]) / attempts, 4),
                "average_latency_ms": round(float(row["total_latency_ms"]) / max(1, int(row["latency_sample_count"])), 2),
                "average_known_cost_usd": (
                    round(float(row["total_known_cost_usd"]) / max(1, int(row["known_cost_count"])), 8)
                    if int(row["known_cost_count"]) > 0
                    else None
                ),
                "agents": sorted(row["agents"]),
                "models": sorted(row["models"])[:8],
            }
        )
    return sorted(
        result,
        key=lambda item: (
            -float(item["success_rate"]),
            float(item["average_known_cost_usd"] or 0.0),
            float(item["average_latency_ms"]),
            -int(item["attempts"]),
            str(item["provider"]),
        ),
    )[:10]


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


def _dashboard_summary(
    aggregates: list[dict[str, Any]],
    workflows: list[dict[str, Any]],
    roles: list[dict[str, Any]],
    workflow_analytics: list[dict[str, Any]],
) -> dict[str, Any]:
    workflow_rate = _workflow_success_rate(workflows)
    task_winners = _task_model_winners(aggregates)
    role_winners = _best_by_role(roles)
    best_providers = _most_effective_providers(aggregates)
    model_win_rates = _model_win_rates(aggregates)
    total_retries = sum(int(row.get("total_retry_count", 0)) for row in workflows)
    retry_attempts = sum(_workflow_attempts(row) for row in workflows)
    return {
        "cards": [
            {
                "id": "workflow_success",
                "label": "Workflow Success",
                "value": workflow_rate["rate"],
                "attempts": workflow_rate["attempts"],
            },
            {
                "id": "best_coding_model",
                "label": "Best Coding Model",
                "value": _winner_label(task_winners.get("coding") or task_winners.get("debug")),
                "attempts": (task_winners.get("coding") or task_winners.get("debug") or {}).get("attempts", 0),
            },
            {
                "id": "best_planner",
                "label": "Best Planner",
                "value": _winner_label(role_winners.get("planner")),
                "attempts": (role_winners.get("planner") or {}).get("attempts", 0),
            },
            {
                "id": "best_worker",
                "label": "Best Worker",
                "value": _winner_label(role_winners.get("coder") or role_winners.get("worker")),
                "attempts": (role_winners.get("coder") or role_winners.get("worker") or {}).get("attempts", 0),
            },
            {
                "id": "average_retries",
                "label": "Average Retries",
                "value": round(total_retries / retry_attempts, 4) if retry_attempts else 0.0,
                "attempts": retry_attempts,
            },
        ],
        "task_model_winners": task_winners,
        "role_model_winners": role_winners,
        "most_effective_providers": best_providers,
        "workflow_analytics": workflow_analytics[:10],
        "top_model_win_rates": model_win_rates[:10],
        "recommendations": _optimization_recommendations(
            workflow_rate=workflow_rate,
            task_winners=task_winners,
            role_winners=role_winners,
            providers=best_providers,
        ),
    }


def _winner_label(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    return " / ".join(str(row.get(key) or "") for key in ("provider", "model") if row.get(key))


def _optimization_recommendations(
    *,
    workflow_rate: dict[str, Any],
    task_winners: dict[str, dict[str, Any]],
    role_winners: dict[str, dict[str, Any]],
    providers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    if int(workflow_rate.get("attempts", 0)) < WORKFLOW_UPGRADE_SAMPLE_THRESHOLD:
        recommendations.append(
            {
                "type": "collect_samples",
                "message": "Run more auto workflows before trusting adaptive workflow upgrades.",
                "samples_needed": max(0, WORKFLOW_UPGRADE_SAMPLE_THRESHOLD - int(workflow_rate.get("attempts", 0))),
            }
        )
    if "coding" not in task_winners:
        recommendations.append(
            {
                "type": "coding_samples_needed",
                "message": "Coding model win rates need more samples.",
                "samples_needed": TASK_SAMPLE_THRESHOLD,
            }
        )
    if "planner" not in role_winners:
        recommendations.append(
            {
                "type": "planner_samples_needed",
                "message": "Planner role optimization needs workflow-role samples.",
                "samples_needed": EXACT_SAMPLE_THRESHOLD,
            }
        )
    if providers:
        best = providers[0]
        recommendations.append(
            {
                "type": "provider_leader",
                "message": (
                    f"{best['provider']} is currently the strongest provider "
                    f"({float(best['success_rate']) * 100:.0f}% success over {best['attempts']} samples)."
                ),
                "provider": best["provider"],
            }
        )
    return recommendations[:6]


def _workflow_analytics(
    aggregates: list[dict[str, Any]],
    workflow_tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in workflow_tasks:
        successes = int(row.get("workflow_successes", 0))
        failures = int(row.get("workflow_failures", 0))
        attempts = successes + failures
        if attempts <= 0:
            attempts = int(row.get("attempts", 0))
        if attempts <= 0:
            continue
        pattern = _workflow_pattern_name(row)
        task_type = str(row.get("task_type") or "general").strip().lower() or "general"
        best_roles = _workflow_role_winners(
            aggregates,
            workflow_pattern=pattern,
            task_type=task_type,
        )
        avg_cost = _workflow_average_cost(
            row,
            aggregates,
            workflow_pattern=pattern,
            task_type=task_type,
            attempts=attempts,
        )
        result.append(
            {
                "label": _workflow_label(pattern, task_type),
                "workflow_pattern": pattern,
                "task_type": task_type,
                "attempts": attempts,
                "success_rate": round(successes / attempts, 4) if attempts else 0.0,
                "average_known_cost_usd": avg_cost,
                "average_latency_ms": round(
                    _safe_float(row.get("total_latency_ms"), 0.0)
                    / max(1, int(row.get("latency_sample_count", 0))),
                    2,
                ),
                "total_retries": int(row.get("total_retry_count", 0)),
                "average_retries": round(int(row.get("total_retry_count", 0)) / max(1, attempts), 4),
                "recovered_by_failover_count": int(row.get("recovered_by_failover_count", 0)),
                "best_roles": best_roles,
                "best_planner": best_roles.get("planner"),
                "best_worker": best_roles.get("coder") or best_roles.get("worker"),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            -float(item["success_rate"]),
            -int(item["attempts"]),
            str(item["workflow_pattern"]),
            str(item["task_type"]),
        ),
    )[:25]


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
                "total_retries": int(row.get("total_retry_count", 0)),
                "average_retries": round(int(row.get("total_retry_count", 0)) / max(1, attempts or int(row.get("attempts", 0))), 4),
                "recovered_by_failover_count": int(row.get("recovered_by_failover_count", 0)),
            }
        )
    return sorted(result, key=lambda item: (-float(item["success_rate"]), -int(item["attempts"]), str(item["workflow_pattern"])))


def _workflow_pattern_row(rows: list[dict[str, Any]], pattern: str) -> dict[str, Any] | None:
    for row in rows:
        if _workflow_pattern_name(row) == pattern:
            return row
    return None


def _workflow_pattern_name(row: dict[str, Any]) -> str:
    pattern = row.get("workflow_pattern")
    if isinstance(pattern, str) and pattern.strip():
        return pattern.strip().lower()
    key_parts = str(row.get("key", "")).split("|")
    if key_parts and key_parts[0] == "workflow_task" and len(key_parts) >= 2:
        return key_parts[1].strip().lower()
    return key_parts[-1].strip().lower()


def _workflow_scope(row: dict[str, Any]) -> str:
    scope = row.get("scope")
    if isinstance(scope, str) and scope.strip():
        return scope.strip().lower()
    key = str(row.get("key", "")).strip().lower()
    if key.startswith("workflow_task|"):
        return "workflow_task"
    return "workflow"


def _workflow_attempts(row: dict[str, Any]) -> int:
    successes = int(row.get("workflow_successes", 0))
    failures = int(row.get("workflow_failures", 0))
    return successes + failures


def _workflow_rate(row: dict[str, Any]) -> float:
    attempts = _workflow_attempts(row)
    if attempts <= 0:
        return 0.0
    return int(row.get("workflow_successes", 0)) / attempts


def _workflow_role_winners(
    rows: list[dict[str, Any]],
    *,
    workflow_pattern: str,
    task_type: str,
) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("key", ""))
        if not key.startswith("exact|"):
            continue
        if str(row.get("workflow_pattern") or "").strip().lower() != workflow_pattern:
            continue
        if str(row.get("task_type") or "general").strip().lower() != task_type:
            continue
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
            "success_rate": round(int(row.get("successes", 0)) / attempts, 4),
            "average_latency_ms": round(
                _safe_float(row.get("total_latency_ms"), 0.0)
                / max(1, int(row.get("latency_sample_count", 0))),
                2,
            ),
            "average_known_cost_usd": (
                round(_safe_float(row.get("total_known_cost_usd"), 0.0) / max(1, int(row.get("known_cost_count", 0))), 8)
                if int(row.get("known_cost_count", 0)) > 0
                else None
            ),
        }
        current = candidates.get(role)
        if current is None or (
            float(candidate["success_rate"]),
            int(candidate["attempts"]),
            -float(candidate["average_latency_ms"]),
        ) > (
            float(current.get("success_rate", 0.0)),
            int(current.get("attempts", 0)),
            -float(current.get("average_latency_ms", 0.0)),
        ):
            candidates[role] = candidate
    return candidates


def _workflow_average_cost(
    workflow_row: dict[str, Any],
    aggregates: list[dict[str, Any]],
    *,
    workflow_pattern: str,
    task_type: str,
    attempts: int,
) -> float | None:
    workflow_cost_count = int(workflow_row.get("known_cost_count", 0))
    if workflow_cost_count > 0:
        return round(_safe_float(workflow_row.get("total_known_cost_usd"), 0.0) / max(1, workflow_cost_count), 8)
    total = 0.0
    for row in aggregates:
        if not str(row.get("key", "")).startswith("exact|"):
            continue
        if str(row.get("workflow_pattern") or "").strip().lower() != workflow_pattern:
            continue
        if str(row.get("task_type") or "general").strip().lower() != task_type:
            continue
        total += _safe_float(row.get("total_known_cost_usd"), 0.0)
    if total <= 0:
        return None
    return round(total / max(1, attempts), 8)


def _workflow_label(pattern: str, task_type: str) -> str:
    task = str(task_type or "general").replace("_", " ").strip()
    if task and task != "general":
        return f"{task.title()} Workflow"
    return str(pattern or "workflow").replace("_", " ").title()


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
