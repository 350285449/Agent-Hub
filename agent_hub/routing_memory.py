from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from threading import RLock
from typing import Any

from .config import AgentConfig
from .models import HubRequest
from .payloads import request_text


ROUTING_MEMORY_FILE = "routing_memory.jsonl"
MAX_MEMORY_READ = 5000
MAX_SIMILAR_OUTCOMES = 250
TEACH_WORKSPACE_MIN_SAMPLES = 12
TEACH_WORKSPACE_MIN_SPAN_SECONDS = 4 * 60 * 60
TEACH_SIMILAR_MIN_SAMPLES = 16
TEACH_BACKUP_MIN_SAMPLES = 24
TEACH_MIN_SUCCESS_RATE = 0.65
TEACH_MIN_GOOD_RATE = 0.70
TEACH_MAX_BAD_RATE = 0.25
TEACH_BAD_DATA_MIN_SAMPLES = 6


class RoutingMemoryStore:
    """Metadata-only routing outcome memory with similarity scoring."""

    def __init__(
        self,
        state_dir: str | Path,
        *,
        enabled: bool = True,
        store_prompts: bool = False,
        retention_days: int = 30,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / ROUTING_MEMORY_FILE
        self.enabled = bool(enabled)
        self.store_prompts = bool(store_prompts)
        self.retention_days = max(1, int(retention_days or 30))
        self._lock = RLock()

    @classmethod
    def from_config(cls, config: Any) -> "RoutingMemoryStore":
        return cls(
            getattr(config, "state_dir"),
            enabled=bool(getattr(config, "routing_memory_enabled", True)),
            store_prompts=bool(getattr(config, "routing_memory_store_prompts", False)),
            retention_days=int(getattr(config, "routing_memory_retention_days", 30) or 30),
        )

    def record_outcome(
        self,
        *,
        request_id: str | None,
        request: HubRequest,
        classification: Any,
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
        routing_mode: str = "",
        memory_adjustment: float | None = None,
    ) -> None:
        if not self.enabled:
            return
        pattern = pattern_from_classification(classification)
        now = time.time()
        error = str(error_type or "").strip().lower()
        timeout = "timeout" in error or "timed_out" in error
        permission_denial = error in {"permission_required", "permission_denied"}
        tool_failure = "tool" in error
        reviewer_failure = "review" in error or "validator" in error
        user_cancellation = "cancel" in error
        fallback_count = max(0, int(failover_attempts or 0))
        retry_total = max(0, int(retry_count if retry_count is not None else fallback_count))
        final_outcome = _final_outcome(
            success=success,
            final=final,
            timeout=timeout,
            permission_denial=permission_denial,
            tool_failure=tool_failure,
            reviewer_failure=reviewer_failure,
            user_cancellation=user_cancellation,
        )
        score = outcome_score(
            success=success,
            latency_seconds=latency_seconds,
            fallback_count=fallback_count,
            timeout=timeout,
            tool_failure=tool_failure,
            reviewer_pass=not reviewer_failure,
            user_cancellation=user_cancellation,
            token_efficiency=_token_efficiency(input_tokens, output_tokens),
        )
        record: dict[str, Any] = {
            "time": now,
            "request_id": request_id,
            "routing_mode": routing_mode,
            **pattern,
            "agent": agent.name,
            "provider": agent.provider,
            "provider_type": agent.provider_type or agent.provider,
            "model": model or agent.model,
            "workflow": pattern.get("workflow_hint") or "",
            "latency_ms": round(max(0.0, float(latency_seconds or 0.0)) * 1000, 2),
            "success": bool(success),
            "failure": not bool(success),
            "retry_count": retry_total,
            "fallback_count": fallback_count,
            "fallback_used": fallback_count > 0,
            "timeout": timeout,
            "user_cancellation": user_cancellation,
            "tool_permission_denial": permission_denial,
            "tool_failure": tool_failure,
            "reviewer_failure": reviewer_failure,
            "final": bool(final),
            "final_outcome": final_outcome,
            "input_tokens": max(0, int(input_tokens or 0)),
            "output_tokens": max(0, int(output_tokens or 0)),
            "estimated_cost_usd": estimated_cost_usd,
            "outcome_score": score,
            "memory_adjustment": round(float(memory_adjustment or 0.0), 4),
        }
        if _request_bool(request, "routing_memory_prompt_hash", False):
            record["prompt_hash"] = _prompt_hash(request)
        if self.store_prompts:
            record["prompt"] = request_text(request)
        self._append(record)

    def routing_signal(
        self,
        agent: AgentConfig,
        classification: Any,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {
                "active": False,
                "agent": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "adjustment": 0.0,
                "summary": "Routing memory is disabled.",
                "similar_outcomes": [],
            }
        pattern = pattern_from_classification(classification)
        similar = self.similar_outcomes(pattern, limit=MAX_SIMILAR_OUTCOMES)
        all_rows = self._read_recent(limit=MAX_MEMORY_READ)
        candidate = [
            item
            for item in similar
            if item.get("agent") == agent.name
            or (
                item.get("provider") == agent.provider
                and item.get("model") == agent.model
            )
        ]
        teach_ready = _teach_ready_signal(
            agent=agent,
            pattern=pattern,
            candidate=candidate,
            all_rows=all_rows,
        )
        teach_adjustment = _safe_float(teach_ready.get("adjustment"), 0.0)
        attempts = len(candidate)
        if attempts <= 0:
            active = abs(teach_adjustment) >= 0.25
            return {
                "active": active,
                "agent": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "adjustment": round(teach_adjustment, 4) if active else 0.0,
                "raw_adjustment": 0.0,
                "teach_adjustment": round(teach_adjustment, 4),
                "teach_ready": teach_ready,
                "attempts": 0,
                "similar_outcomes": _public_similar(similar[:5]),
                "summary": _memory_summary(
                    agent=agent.name,
                    active=active,
                    adjustment=teach_adjustment,
                    attempts=0,
                    success_rate=0.0,
                    teach_ready=teach_ready,
                ),
            }
        successes = sum(1 for item in candidate if item.get("success") is True)
        timeouts = sum(1 for item in candidate if item.get("timeout") is True)
        fallback_count = sum(1 for item in candidate if item.get("fallback_used") is True)
        average_score = sum(_safe_float(item.get("outcome_score"), 0.0) for item in candidate) / attempts
        success_rate = successes / attempts
        timeout_rate = timeouts / attempts
        sample_weight = min(1.0, attempts / 8.0)
        adjustment = (average_score - 0.65) * 24.0 * sample_weight
        if attempts >= 3 and success_rate >= 0.85:
            adjustment += min(3.0, attempts / 5.0)
        if attempts >= 3 and success_rate < 0.50:
            adjustment -= min(6.0, attempts * 0.75)
        if (
            attempts >= 3
            and timeout_rate >= 0.30
            and str(pattern.get("context_size_bucket") or "") in {"large", "xlarge"}
        ):
            adjustment -= 6.0
        adjustment = _clamp(adjustment + teach_adjustment, -18.0, 18.0)
        active = attempts >= 2 and abs(adjustment) >= 0.25
        return {
            "active": active,
            "agent": agent.name,
            "provider": agent.provider,
            "model": agent.model,
            "adjustment": round(adjustment, 4) if active else 0.0,
            "raw_adjustment": round(adjustment - teach_adjustment, 4),
            "teach_adjustment": round(teach_adjustment, 4),
            "teach_ready": teach_ready,
            "attempts": attempts,
            "success_rate": round(success_rate, 4),
            "average_outcome_score": round(average_score, 4),
            "timeout_rate": round(timeout_rate, 4),
            "fallback_frequency": round(fallback_count / attempts, 4),
            "similar_outcomes_count": len(similar),
            "similar_outcomes": _public_similar(candidate[:5] or similar[:5]),
            "summary": _memory_summary(
                agent=agent.name,
                active=active,
                adjustment=adjustment,
                attempts=attempts,
                success_rate=success_rate,
                teach_ready=teach_ready,
            ),
        }

    def reviewer_signal(self, classification: Any) -> dict[str, Any]:
        pattern = pattern_from_classification(classification)
        similar = self.similar_outcomes(pattern, limit=MAX_SIMILAR_OUTCOMES)
        reviewer_rows = [
            item
            for item in similar
            if item.get("reviewer_failure") is True
            or "review" in str(item.get("workflow") or "")
        ]
        attempts = len(similar)
        if attempts < 3:
            return {"required": False, "reason": "", "similar_outcomes": attempts}
        rate = len(reviewer_rows) / attempts
        if rate < 0.25:
            return {"required": False, "reason": "", "similar_outcomes": attempts}
        return {
            "required": True,
            "reason": (
                "Routing memory found reviewer issues or review-heavy outcomes "
                f"in {len(reviewer_rows)} of {attempts} similar request(s)."
            ),
            "similar_outcomes": attempts,
        }

    def similar_outcomes(self, pattern: dict[str, Any], *, limit: int = 25) -> list[dict[str, Any]]:
        rows = self._read_recent(limit=MAX_MEMORY_READ)
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            score = similarity_score(pattern, row)
            if score <= 0:
                continue
            scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], -_safe_float(item[1].get("time"), 0.0)))
        result: list[dict[str, Any]] = []
        for score, row in scored[: max(1, int(limit))]:
            item = dict(row)
            item["similarity"] = round(score, 4)
            item.pop("prompt", None)
            result.append(item)
        return result

    def recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [
            _public_record(row)
            for row in self._read_recent(limit=max(1, min(int(limit or 50), 500)))
        ]

    def record_feedback(self, *, request_id: str, rating: str, reason: str = "") -> dict[str, Any]:
        if not self.enabled:
            return {"matched": False, "enabled": False}
        rating = str(rating or "").strip().lower()
        rows = self._read_recent(limit=MAX_MEMORY_READ)
        target = next((row for row in rows if str(row.get("request_id") or "") == request_id), None)
        if not isinstance(target, dict):
            return {"matched": False, "enabled": True}
        positive = rating == "up"
        adjusted = dict(target)
        adjusted["time"] = time.time()
        adjusted["feedback_rating"] = rating
        adjusted["feedback_reason"] = str(reason or "")[:120]
        adjusted["final"] = True
        adjusted["final_outcome"] = "user_confirmed" if positive else "user_rejected"
        adjusted["success"] = positive
        adjusted["failure"] = not positive
        adjusted["outcome_score"] = round(
            _clamp(_safe_float(target.get("outcome_score"), 0.5) + (0.18 if positive else -0.24), 0.0, 1.0),
            4,
        )
        self._append(adjusted)
        return {"matched": True, "enabled": True, "outcome_score": adjusted["outcome_score"]}

    def stats(self) -> dict[str, Any]:
        rows = self._read_recent(limit=MAX_MEMORY_READ)
        data_state = "measured_ready" if rows else ("baseline_ready" if self.enabled else "disabled")
        return {
            "object": "agent_hub.routing_memory.stats",
            "enabled": self.enabled,
            "store_prompts": self.store_prompts,
            "retention_days": self.retention_days,
            "summary": {
                "data_state": data_state,
                "total_records": len(rows),
                "signals_tracked": [
                    "task_type",
                    "provider",
                    "model",
                    "latency",
                    "failover",
                    "cost",
                    "feedback",
                    "repository_profile",
                    "teach_ready",
                ],
                "prompt_storage": "hash_or_disabled" if not self.store_prompts else "enabled",
            },
            "empty_state": None
            if rows
            else {
                "title": "Routing memory is ready for outcome samples"
                if self.enabled
                else "Routing memory is disabled",
                "message": (
                    "Agent Hub will learn provider, model, cost, latency, failover, and feedback "
                    "patterns as routed requests complete."
                    if self.enabled
                    else "Enable routing_memory_enabled to collect local routing outcome history."
                ),
                "actions": [
                    "Send requests through Agent Hub.",
                    "Record feedback with POST /v1/feedback.",
                    "Inspect recent records at /v1/routing-memory/recent.",
                ]
                if self.enabled
                else ["Set routing_memory_enabled=true."],
            },
            "baseline_policy": {
                "store_prompts": self.store_prompts,
                "retention_days": self.retention_days,
                "max_records": MAX_MEMORY_READ,
                "privacy": "Prompts are not stored unless routing_memory_store_prompts=true.",
            },
            "total_records": len(rows),
            "most_successful_models_by_task_type": _most_successful_models(rows),
            "failure_prone_models_by_task_type": _failure_prone_models(rows),
            "average_latency_by_provider": _average_latency_by_provider(rows),
            "fallback_frequency": _fallback_frequency(rows),
            "cost_performance_winner": _cost_performance_winner(rows),
            "routing_memory_influence_per_request": _memory_influence(rows[-25:]),
            "self_adjusting": _self_adjusting_memory_summary(rows),
            "teach_ready": _teach_ready_summary(rows),
        }

    def reset(self) -> dict[str, Any]:
        count = len(self._read_recent(limit=MAX_MEMORY_READ))
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        return {
            "object": "agent_hub.routing_memory.reset",
            "deleted_records": count,
            "ok": True,
        }

    def _append(self, record: dict[str, Any]) -> None:
        with self._lock:
            try:
                self.state_dir.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
                self._prune_if_needed()
            except OSError:
                return

    def _read_recent(self, *, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
            rows: list[dict[str, Any]] = []
            cutoff = time.time() - self.retention_days * 86400
            for line in lines[-max(1, int(limit)) :]:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(value, dict):
                    continue
                if _safe_float(value.get("time"), 0.0) < cutoff:
                    continue
                rows.append(value)
            return rows

    def _prune_if_needed(self) -> None:
        rows = self._read_recent(limit=MAX_MEMORY_READ)
        _atomic_write_jsonl(self.path, rows[-MAX_MEMORY_READ:])


def pattern_from_classification(classification: Any) -> dict[str, Any]:
    data = classification.to_dict() if hasattr(classification, "to_dict") else dict(classification or {})
    return {
        "task_type": str(data.get("task_type") or "general"),
        "task_category": str(data.get("task_category") or data.get("task_type") or "general"),
        "language": str(data.get("language") or "unknown"),
        "framework": str(data.get("framework") or "unknown"),
        "complexity": str(data.get("complexity") or "low"),
        "risk_level": str(data.get("risk_level") or data.get("risk") or "low"),
        "repo_size_bucket": str(data.get("repo_size_bucket") or "unknown"),
        "repository_profile_id": str(data.get("repository_profile_id") or ""),
        "repository_project": str(data.get("repository_project") or ""),
        "repository_architecture": str(data.get("repository_architecture") or ""),
        "context_size_bucket": str(data.get("context_estimate") or data.get("context_size_bucket") or "small"),
        "file_types": [
            str(item)
            for item in data.get("file_types", [])
            if isinstance(item, str) and item
        ][:20],
        "workflow_hint": str(data.get("workflow_hint") or ""),
        "reviewer_required": bool(data.get("reviewer_required", False)),
    }


def outcome_score(
    *,
    success: bool,
    latency_seconds: float | None,
    fallback_count: int,
    timeout: bool,
    tool_failure: bool,
    reviewer_pass: bool,
    user_cancellation: bool,
    token_efficiency: float | None = None,
) -> float:
    score = 1.0 if success else 0.20
    latency = max(0.0, float(latency_seconds or 0.0))
    if success and latency > 0:
        if latency <= 2:
            score += 0.04
        elif latency > 15:
            score -= 0.12
        elif latency > 6:
            score -= 0.06
    score -= min(0.18, max(0, int(fallback_count or 0)) * 0.05)
    if timeout:
        score -= 0.25
    if tool_failure:
        score -= 0.18
    if not reviewer_pass:
        score -= 0.15
    if user_cancellation:
        score -= 0.25
    if token_efficiency is not None:
        if token_efficiency > 0 and token_efficiency < 0.4:
            score += 0.03
        elif token_efficiency > 2.0:
            score -= 0.04
    return round(_clamp(score, 0.0, 1.0), 4)


def similarity_score(pattern: dict[str, Any], row: dict[str, Any]) -> float:
    score = 0.0
    total = 0.0
    weights = {
        "task_category": 3.0,
        "task_type": 2.0,
        "language": 2.0,
        "framework": 1.25,
        "complexity": 1.0,
        "risk_level": 1.0,
        "repo_size_bucket": 1.0,
        "repository_profile_id": 1.25,
        "repository_project": 0.75,
        "repository_architecture": 0.5,
        "context_size_bucket": 1.0,
    }
    for key, weight in weights.items():
        total += weight
        left = str(pattern.get(key) or "").lower()
        right = str(row.get(key) or "").lower()
        if left and right and left == right:
            score += weight
    pattern_types = set(pattern.get("file_types") or [])
    row_types = set(row.get("file_types") or [])
    if pattern_types or row_types:
        total += 1.0
        overlap = pattern_types & row_types
        union = pattern_types | row_types
        score += len(overlap) / max(1, len(union))
    if total <= 0:
        return 0.0
    normalized = score / total
    return normalized if normalized >= 0.35 else 0.0


def _final_outcome(
    *,
    success: bool,
    final: bool,
    timeout: bool,
    permission_denial: bool,
    tool_failure: bool,
    reviewer_failure: bool,
    user_cancellation: bool,
) -> str:
    if user_cancellation:
        return "cancelled"
    if timeout:
        return "timeout"
    if permission_denial:
        return "permission_denied"
    if tool_failure:
        return "tool_failure"
    if reviewer_failure:
        return "reviewer_failure"
    if success:
        return "success"
    return "failure" if final else "failed_attempt"


def _token_efficiency(input_tokens: int, output_tokens: int) -> float | None:
    if input_tokens <= 0 or output_tokens <= 0:
        return None
    return max(0.0, output_tokens / max(1, input_tokens))


def _prompt_hash(request: HubRequest) -> str:
    return hashlib.sha256(request_text(request).encode("utf-8", errors="replace")).hexdigest()


def _request_bool(request: HubRequest, key: str, default: bool) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    for value in (hub.get(key), raw.get(key)):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _public_similar(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: row.get(key)
            for key in (
                "request_id",
                "task_type",
                "task_category",
                "language",
                "framework",
                "repo_size_bucket",
                "repository_profile_id",
                "repository_project",
                "repository_architecture",
                "context_size_bucket",
                "risk_level",
                "agent",
                "provider",
                "model",
                "success",
                "final_outcome",
                "outcome_score",
                "similarity",
            )
            if key in row
        }
        for row in rows
    ]


def _public_record(row: dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    value.pop("prompt", None)
    return value


def _memory_summary(
    *,
    agent: str,
    active: bool,
    adjustment: float,
    attempts: int,
    success_rate: float,
    teach_ready: dict[str, Any] | None = None,
) -> str:
    teach = teach_ready if isinstance(teach_ready, dict) else {}
    teach_summary = str(teach.get("summary") or "").strip()
    if not active:
        summary = (
            f"Routing memory has {attempts} similar sample(s) for {agent}; "
            "not enough influence to change ranking."
        )
        return f"{summary} {teach_summary}".strip() if teach_summary else summary
    direction = "boosted" if adjustment > 0 else "penalized"
    summary = (
        f"Routing memory {direction} {agent} by {adjustment:+.2f} "
        f"from {attempts} similar sample(s), {success_rate * 100:.0f}% success."
    )
    return f"{summary} {teach_summary}".strip() if teach_summary else summary


def _teach_ready_signal(
    *,
    agent: AgentConfig,
    pattern: dict[str, Any],
    candidate: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    workspace_rows = _workspace_history_rows(agent, pattern, all_rows)
    model_rows = _model_history_rows(agent, all_rows)
    workspace_profile = _teach_profile(workspace_rows)
    similar_profile = _teach_profile(candidate)
    backup_profile = _teach_profile(model_rows)
    profiles = {
        "workspace_history": workspace_profile,
        "similar_assessments": similar_profile,
        "backup_model_history": backup_profile,
    }
    bad_profile = _worst_bad_profile(profiles)
    if (
        bad_profile
        and bad_profile["samples"] >= TEACH_BAD_DATA_MIN_SAMPLES
        and bad_profile["bad_rate"] > TEACH_MAX_BAD_RATE
    ):
        adjustment = -min(4.0, 1.0 + bad_profile["bad_rate"] * 4.0)
        return {
            "active": False,
            "basis": str(bad_profile["basis"]),
            "backup": {"active": False, "basis": "blocked_by_bad_data"},
            "adjustment": round(adjustment, 4),
            "workspace_samples": workspace_profile["samples"],
            "similar_samples": similar_profile["samples"],
            "backup_samples": backup_profile["samples"],
            "good_samples": bad_profile["good_samples"],
            "bad_samples": bad_profile["bad_samples"],
            "neutral_samples": bad_profile["neutral_samples"],
            "good_rate": round(bad_profile["good_rate"], 4),
            "bad_rate": round(bad_profile["bad_rate"], 4),
            "success_rate": round(bad_profile["success_rate"], 4),
            "average_outcome_score": round(bad_profile["average_outcome_score"], 4),
            "minimum_workspace_samples": TEACH_WORKSPACE_MIN_SAMPLES,
            "minimum_similar_samples": TEACH_SIMILAR_MIN_SAMPLES,
            "minimum_backup_samples": TEACH_BACKUP_MIN_SAMPLES,
            "summary": (
                f"{agent.name} teaching data is blocked by bad {bad_profile['basis']} samples "
                f"({bad_profile['bad_rate'] * 100:.0f}% bad data)."
            ),
        }
    basis = ""
    selected = {}
    backup = {"active": False, "basis": ""}
    if _teachable_profile(
        workspace_profile,
        minimum_samples=TEACH_WORKSPACE_MIN_SAMPLES,
        require_timespan=True,
    ):
        basis = "workspace_history"
        selected = workspace_profile
    elif _teachable_profile(
        similar_profile,
        minimum_samples=TEACH_SIMILAR_MIN_SAMPLES,
        require_timespan=False,
    ):
        basis = "similar_assessments"
        selected = similar_profile
    elif _teachable_profile(
        backup_profile,
        minimum_samples=TEACH_BACKUP_MIN_SAMPLES,
        require_timespan=False,
        backup=True,
    ):
        basis = "backup_model_history"
        selected = backup_profile
        backup = {"active": True, "basis": "model_history"}
    if not basis:
        return {
            "active": False,
            "basis": "",
            "backup": backup,
            "adjustment": 0.0,
            "workspace_samples": workspace_profile["samples"],
            "similar_samples": similar_profile["samples"],
            "backup_samples": backup_profile["samples"],
            "good_samples": max(
                workspace_profile["good_samples"],
                similar_profile["good_samples"],
                backup_profile["good_samples"],
            ),
            "bad_samples": max(
                workspace_profile["bad_samples"],
                similar_profile["bad_samples"],
                backup_profile["bad_samples"],
            ),
            "neutral_samples": max(
                workspace_profile["neutral_samples"],
                similar_profile["neutral_samples"],
                backup_profile["neutral_samples"],
            ),
            "minimum_workspace_samples": TEACH_WORKSPACE_MIN_SAMPLES,
            "minimum_similar_samples": TEACH_SIMILAR_MIN_SAMPLES,
            "minimum_backup_samples": TEACH_BACKUP_MIN_SAMPLES,
            "summary": "Teaching data is not reliable enough yet.",
        }
    divisor = 24.0 if basis == "workspace_history" else 32.0
    if basis == "backup_model_history":
        divisor = 48.0
    confidence = min(1.0, selected["good_samples"] / divisor)
    quality = max(0.0, selected["success_rate"] - TEACH_MIN_SUCCESS_RATE)
    score_quality = max(0.0, selected["average_outcome_score"] - 0.62)
    bad_penalty = selected["bad_rate"] * 3.0
    maximum_adjustment = 2.0 if basis == "backup_model_history" else 4.0
    adjustment = min(
        maximum_adjustment,
        0.75 + confidence * 1.8 + quality * 3.0 + score_quality * 1.5 - bad_penalty,
    )
    label = {
        "workspace_history": "workspace history",
        "similar_assessments": "similar assessments",
        "backup_model_history": "backup model history",
    }[basis]
    return {
        "active": True,
        "basis": basis,
        "backup": backup,
        "adjustment": round(adjustment, 4),
        "workspace_samples": workspace_profile["samples"],
        "similar_samples": similar_profile["samples"],
        "backup_samples": backup_profile["samples"],
        "usable_samples": selected["usable_samples"],
        "good_samples": selected["good_samples"],
        "bad_samples": selected["bad_samples"],
        "neutral_samples": selected["neutral_samples"],
        "good_rate": round(selected["good_rate"], 4),
        "bad_rate": round(selected["bad_rate"], 4),
        "success_rate": round(selected["success_rate"], 4),
        "average_outcome_score": round(selected["average_outcome_score"], 4),
        "timespan_seconds": round(selected["timespan_seconds"], 2),
        "minimum_workspace_samples": TEACH_WORKSPACE_MIN_SAMPLES,
        "minimum_similar_samples": TEACH_SIMILAR_MIN_SAMPLES,
        "minimum_backup_samples": TEACH_BACKUP_MIN_SAMPLES,
        "summary": (
            f"{agent.name} is teachable from {selected['good_samples']} good {label} samples "
            f"({selected['success_rate'] * 100:.0f}% success, "
            f"{selected['bad_rate'] * 100:.0f}% bad data)."
        ),
    }


def _workspace_history_rows(
    agent: AgentConfig,
    pattern: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    repository_profile_id = str(pattern.get("repository_profile_id") or "")
    repository_project = str(pattern.get("repository_project") or "")
    if not repository_profile_id and not repository_project:
        return []
    return [
        row
        for row in rows
        if _same_agent_or_model(row, agent)
        and (
            (repository_profile_id and str(row.get("repository_profile_id") or "") == repository_profile_id)
            or (repository_project and str(row.get("repository_project") or "") == repository_project)
        )
    ]


def _model_history_rows(agent: AgentConfig, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if _same_agent_or_model(row, agent)]


def _same_agent_or_model(row: dict[str, Any], agent: AgentConfig) -> bool:
    return row.get("agent") == agent.name or (
        row.get("provider") == agent.provider
        and row.get("model") == agent.model
    )


def _teachable_profile(
    profile: dict[str, Any],
    *,
    minimum_samples: int,
    require_timespan: bool,
    backup: bool = False,
) -> bool:
    if int(profile.get("samples") or 0) < minimum_samples:
        return False
    if require_timespan and float(profile.get("timespan_seconds") or 0.0) < TEACH_WORKSPACE_MIN_SPAN_SECONDS:
        return False
    min_good_rate = TEACH_MIN_GOOD_RATE + (0.05 if backup else 0.0)
    min_success_rate = TEACH_MIN_SUCCESS_RATE + (0.05 if backup else 0.0)
    return (
        float(profile.get("success_rate") or 0.0) >= min_success_rate
        and float(profile.get("good_rate") or 0.0) >= min_good_rate
        and float(profile.get("bad_rate") or 0.0) <= TEACH_MAX_BAD_RATE
    )


def _worst_bad_profile(profiles: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    for basis, profile in profiles.items():
        item = dict(profile)
        item["basis"] = basis
        candidates.append(item)
    bad = [
        item
        for item in candidates
        if int(item.get("samples") or 0) >= TEACH_BAD_DATA_MIN_SAMPLES
        and float(item.get("bad_rate") or 0.0) > TEACH_MAX_BAD_RATE
    ]
    if not bad:
        return None
    return max(
        bad,
        key=lambda item: (
            float(item.get("bad_rate") or 0.0),
            int(item.get("bad_samples") or 0),
            int(item.get("samples") or 0),
        ),
    )


def _teach_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    samples = len(rows)
    if samples <= 0:
        return {
            "samples": 0,
            "usable_samples": 0,
            "good_samples": 0,
            "bad_samples": 0,
            "neutral_samples": 0,
            "success_rate": 0.0,
            "good_rate": 0.0,
            "bad_rate": 0.0,
            "average_outcome_score": 0.0,
            "timespan_seconds": 0.0,
        }
    successes = sum(1 for row in rows if row.get("success") is True)
    scores = [_safe_float(row.get("outcome_score"), 0.0) for row in rows]
    times = [_safe_float(row.get("time"), 0.0) for row in rows if _safe_float(row.get("time"), 0.0) > 0]
    good = sum(1 for row in rows if _training_data_label(row) == "good")
    bad = sum(1 for row in rows if _training_data_label(row) == "bad")
    neutral = max(0, samples - good - bad)
    usable = good + bad
    return {
        "samples": samples,
        "usable_samples": usable,
        "good_samples": good,
        "bad_samples": bad,
        "neutral_samples": neutral,
        "success_rate": successes / samples,
        "good_rate": good / max(1, usable),
        "bad_rate": bad / max(1, usable),
        "average_outcome_score": sum(scores) / max(1, len(scores)),
        "timespan_seconds": max(times) - min(times) if len(times) >= 2 else 0.0,
    }


def _training_data_label(row: dict[str, Any]) -> str:
    final_outcome = str(row.get("final_outcome") or "").strip().lower()
    feedback = str(row.get("feedback_rating") or "").strip().lower()
    score = _safe_float(row.get("outcome_score"), 0.0)
    retry_count = int(row.get("retry_count") or row.get("fallback_count") or 0)
    if (
        feedback == "down"
        or final_outcome in {"user_rejected", "failure", "failed_attempt", "timeout", "tool_failure", "reviewer_failure"}
        or row.get("timeout") is True
        or row.get("tool_failure") is True
        or row.get("reviewer_failure") is True
        or row.get("user_cancellation") is True
        or score <= 0.45
    ):
        return "bad"
    if (
        (row.get("success") is True or final_outcome in {"success", "user_confirmed"} or feedback == "up")
        and final_outcome not in {"permission_denied", "cancelled"}
        and row.get("fallback_used") is not True
        and retry_count <= 1
        and score >= 0.72
    ):
        return "good"
    return "neutral"


def _most_successful_models(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = _group_model_task(rows)
    winners = []
    for row in grouped.values():
        attempts = row["attempts"]
        if attempts <= 0:
            continue
        success_rate = row["successes"] / attempts
        winners.append(
            {
                "task_type": row["task_type"],
                "agent": row["agent"],
                "provider": row["provider"],
                "model": row["model"],
                "attempts": attempts,
                "success_rate": round(success_rate, 4),
                "average_outcome_score": round(row["score_total"] / attempts, 4),
                "retry_frequency": round(row["retry_total"] / max(1, attempts), 4),
                "average_cost_usd": round(row["cost_total"] / max(1, row["cost_count"]), 8)
                if row["cost_count"]
                else None,
                "cost_performance_score": round(
                    (row["score_total"] / attempts)
                    / max(0.000001, (row["cost_total"] / row["cost_count"]) + 0.000001),
                    4,
                )
                if row["cost_count"]
                else None,
            }
        )
    return sorted(
        winners,
        key=lambda item: (
            str(item["task_type"]),
            -float(item["success_rate"]),
            -float(item["average_outcome_score"]),
            -int(item["attempts"]),
        ),
    )[:25]


def _failure_prone_models(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = _group_model_task(rows)
    result = []
    for row in grouped.values():
        attempts = row["attempts"]
        if attempts <= 0:
            continue
        failure_rate = row["failures"] / attempts
        if failure_rate <= 0:
            continue
        result.append(
            {
                "task_type": row["task_type"],
                "agent": row["agent"],
                "provider": row["provider"],
                "model": row["model"],
                "attempts": attempts,
                "failure_rate": round(failure_rate, 4),
                "timeout_rate": round(row["timeouts"] / attempts, 4),
            }
        )
    return sorted(
        result,
        key=lambda item: (-float(item["failure_rate"]), -float(item["timeout_rate"]), -int(item["attempts"])),
    )[:25]


def _average_latency_by_provider(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    providers: dict[str, dict[str, Any]] = {}
    for row in rows:
        provider = str(row.get("provider") or "")
        if not provider:
            continue
        target = providers.setdefault(provider, {"provider": provider, "count": 0, "latency_total": 0.0})
        latency = _safe_float(row.get("latency_ms"), 0.0)
        if latency <= 0:
            continue
        target["count"] += 1
        target["latency_total"] += latency
    return [
        {
            "provider": row["provider"],
            "samples": row["count"],
            "average_latency_ms": round(row["latency_total"] / max(1, row["count"]), 2),
        }
        for row in sorted(providers.values(), key=lambda item: item["provider"])
        if row["count"] > 0
    ]


def _fallback_frequency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    fallbacks = sum(1 for row in rows if row.get("fallback_used") is True)
    return {
        "requests": total,
        "fallbacks": fallbacks,
        "rate": round(fallbacks / total, 4) if total else 0.0,
    }


def _cost_performance_winner(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    grouped = _group_model_task(rows)
    candidates = []
    for row in grouped.values():
        attempts = row["attempts"]
        cost_count = row["cost_count"]
        if attempts <= 0 or cost_count <= 0:
            continue
        average_cost = row["cost_total"] / cost_count
        average_score = row["score_total"] / attempts
        candidates.append(
            {
                "task_type": row["task_type"],
                "agent": row["agent"],
                "provider": row["provider"],
                "model": row["model"],
                "attempts": attempts,
                "average_outcome_score": round(average_score, 4),
                "average_cost_usd": round(average_cost, 8),
                "cost_performance_score": round(average_score / max(0.000001, average_cost + 0.000001), 4),
            }
        )
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            -float(item["average_outcome_score"]),
            float(item["average_cost_usd"]),
            -int(item["attempts"]),
        ),
    )[0]


def _memory_influence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        adjustment = _safe_float(row.get("memory_adjustment"), 0.0)
        if abs(adjustment) < 0.0001:
            continue
        result.append(
            {
                "request_id": row.get("request_id"),
                "task_type": row.get("task_type"),
                "agent": row.get("agent"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "memory_adjustment": round(adjustment, 4),
                "outcome_score": row.get("outcome_score"),
                "success": row.get("success"),
            }
        )
    return result[-25:]


def _self_adjusting_memory_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    segments: dict[str, dict[str, Any]] = {}
    for row in rows:
        agent = str(row.get("agent") or "")
        language = str(row.get("language") or "unknown")
        framework = str(row.get("framework") or "unknown")
        if not agent:
            continue
        key = "|".join((agent, language, framework))
        target = segments.setdefault(
            key,
            {
                "agent": agent,
                "language": language,
                "framework": framework,
                "attempts": 0,
                "successes": 0,
                "token_total": 0,
                "retry_total": 0,
                "score_total": 0.0,
            },
        )
        target["attempts"] += 1
        target["successes"] += int(row.get("success") is True)
        target["token_total"] += int(row.get("input_tokens") or 0) + int(row.get("output_tokens") or 0)
        target["retry_total"] += int(row.get("retry_count") or row.get("fallback_count") or 0)
        target["score_total"] += _safe_float(row.get("outcome_score"), 0.0)
    profiles = []
    for segment in segments.values():
        attempts = int(segment["attempts"])
        if attempts <= 0:
            continue
        success_rate = segment["successes"] / attempts
        avg_retries = segment["retry_total"] / attempts
        avg_tokens = segment["token_total"] / attempts
        confidence = min(1.0, attempts / 10.0)
        adjustment = ((success_rate - 0.68) * 18.0 - min(5.0, avg_retries * 3.0) - min(3.0, avg_tokens / 40000.0)) * confidence
        profiles.append(
            {
                "agent": segment["agent"],
                "segment": f"{segment['language']}/{segment['framework']}",
                "attempts": attempts,
                "success_rate": round(success_rate, 4),
                "average_tokens": round(avg_tokens, 2),
                "average_retries": round(avg_retries, 2),
                "average_outcome_score": round(segment["score_total"] / attempts, 4),
                "suggested_adjustment": round(_clamp(adjustment, -10.0, 10.0), 4),
                "active": attempts >= 2 and abs(adjustment) >= 0.2,
            }
        )
    profiles.sort(
        key=lambda item: (
            -int(item["attempts"]),
            -abs(float(item["suggested_adjustment"])),
            str(item["agent"]),
        )
    )
    return {
        "active_profiles": sum(1 for item in profiles if item["active"]),
        "profile_count": len(profiles),
        "minimum_samples": 2,
        "profiles": profiles[:25],
    }


def _teach_ready_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        agent = str(row.get("agent") or "")
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        if not agent and not model:
            continue
        repository_profile_id = str(row.get("repository_profile_id") or "")
        repository_project = str(row.get("repository_project") or "")
        workspace_key = repository_profile_id or repository_project
        if not workspace_key:
            continue
        key = "|".join((agent, provider, model, workspace_key))
        target = groups.setdefault(
            key,
            {
                "agent": agent,
                "provider": provider,
                "model": model,
                "workspace": workspace_key,
                "rows": [],
            },
        )
        target["rows"].append(row)
    profiles = []
    for group in groups.values():
        profile = _teach_profile(group["rows"])
        active = _teachable_profile(
            profile,
            minimum_samples=TEACH_WORKSPACE_MIN_SAMPLES,
            require_timespan=True,
        )
        profiles.append(
            {
                "agent": group["agent"],
                "provider": group["provider"],
                "model": group["model"],
                "workspace": group["workspace"],
                "samples": profile["samples"],
                "usable_samples": profile["usable_samples"],
                "good_samples": profile["good_samples"],
                "bad_samples": profile["bad_samples"],
                "neutral_samples": profile["neutral_samples"],
                "success_rate": round(profile["success_rate"], 4),
                "good_rate": round(profile["good_rate"], 4),
                "bad_rate": round(profile["bad_rate"], 4),
                "average_outcome_score": round(profile["average_outcome_score"], 4),
                "timespan_seconds": round(profile["timespan_seconds"], 2),
                "active": active,
            }
        )
    profiles.sort(
        key=lambda item: (
            not bool(item["active"]),
            -int(item["samples"]),
            -float(item["success_rate"]),
            str(item["agent"]),
        )
    )
    return {
        "active_profiles": sum(1 for item in profiles if item["active"]),
        "profile_count": len(profiles),
        "workspace_minimum_samples": TEACH_WORKSPACE_MIN_SAMPLES,
        "workspace_minimum_span_seconds": TEACH_WORKSPACE_MIN_SPAN_SECONDS,
        "similar_minimum_samples": TEACH_SIMILAR_MIN_SAMPLES,
        "backup_minimum_samples": TEACH_BACKUP_MIN_SAMPLES,
        "minimum_success_rate": TEACH_MIN_SUCCESS_RATE,
        "minimum_good_rate": TEACH_MIN_GOOD_RATE,
        "maximum_bad_rate": TEACH_MAX_BAD_RATE,
        "profiles": profiles[:25],
    }


def _group_model_task(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_type = str(row.get("task_type") or "general")
        agent = str(row.get("agent") or "")
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        key = "|".join((task_type, agent, provider, model))
        target = grouped.setdefault(
            key,
            {
                "task_type": task_type,
                "agent": agent,
                "provider": provider,
                "model": model,
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "timeouts": 0,
                "score_total": 0.0,
                "cost_total": 0.0,
                "cost_count": 0,
                "retry_total": 0,
            },
        )
        target["attempts"] += 1
        target["successes"] += int(row.get("success") is True)
        target["failures"] += int(row.get("success") is not True)
        target["timeouts"] += int(row.get("timeout") is True)
        target["score_total"] += _safe_float(row.get("outcome_score"), 0.0)
        target["retry_total"] += int(row.get("retry_count") or row.get("fallback_count") or 0)
        cost = row.get("estimated_cost_usd")
        if cost is not None:
            target["cost_total"] += _safe_float(cost, 0.0)
            target["cost_count"] += 1
    return grouped


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
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
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
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
    "ROUTING_MEMORY_FILE",
    "RoutingMemoryStore",
    "outcome_score",
    "pattern_from_classification",
    "similarity_score",
]
