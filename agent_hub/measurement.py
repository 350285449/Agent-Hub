from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AgentConfig, HubConfig
from .models import FailoverEvent, HubRequest


LEDGER_SCHEMA_VERSION = 1
DEFAULT_LEDGER_ENV = "AGENT_HUB_USAGE_LEDGER"


@dataclass(frozen=True, slots=True)
class ModelPrice:
    provider: str
    model: str
    input_per_million: float | None
    output_per_million: float | None
    cached_input_per_million: float | None = None
    effective_from: str = "config"
    source: str = "config"
    agent: str = ""

    @property
    def priced(self) -> bool:
        return self.input_per_million is not None and self.output_per_million is not None

    @property
    def free(self) -> bool:
        return self.input_per_million == 0.0 and self.output_per_million == 0.0


@dataclass(slots=True)
class UsageEvent:
    request_id: str
    timestamp: float
    session_id: str
    route: str
    task_type: str
    selected_agent: str
    selected_provider: str
    selected_model: str
    input_tokens_actual: int | None
    output_tokens_actual: int | None
    input_tokens_estimated: int
    output_tokens_estimated: int
    cost_usd_actual: float | None
    cost_usd_estimated: float | None
    cost_source: str
    latency_ms: float | None
    success: bool
    failover_count: int
    tests_passed_count: int = 0
    tests_failed_count: int = 0
    files_changed_count: int = 0
    user_accepted: bool | None = None
    measurement_source: str = "estimated"
    rejected_alternatives: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class BaselineComparison:
    baseline_name: str
    baseline_agent: str
    baseline_provider: str
    baseline_model: str
    cost_usd: float | None
    cost_source: str
    savings_usd: float | None
    savings_pct: float | None
    comparison: str


@dataclass(slots=True)
class EvaluationResult:
    request_id: str
    timestamp: float
    success_boolean: bool
    quality_score_0_to_1: float | None
    evaluation_method: str
    test_command: str = ""
    tests_passed: bool | None = None
    user_rating: float | None = None
    judge_model: str = ""


class UsageLedger:
    """Durable request/cost/evaluation ledger for credible analytics."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(
        self,
        event: UsageEvent,
        *,
        provider_attempts: list[dict[str, Any]],
        model_prices: list[ModelPrice],
        baselines: list[BaselineComparison],
        evaluation: EvaluationResult,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                _ensure_schema(connection)
                _upsert_model_prices(connection, model_prices)
                connection.execute(
                    """
                    INSERT OR REPLACE INTO requests (
                        request_id, timestamp, session_id, route, task_type,
                        selected_agent, selected_provider, selected_model,
                        input_tokens_actual, output_tokens_actual,
                        input_tokens_estimated, output_tokens_estimated,
                        cost_usd_actual, cost_usd_estimated, cost_source,
                        latency_ms, success, failover_count, tests_passed_count,
                        tests_failed_count, files_changed_count, user_accepted,
                        measurement_source,
                        rejected_alternatives_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.request_id,
                        event.timestamp,
                        event.session_id,
                        event.route,
                        event.task_type,
                        event.selected_agent,
                        event.selected_provider,
                        event.selected_model,
                        event.input_tokens_actual,
                        event.output_tokens_actual,
                        event.input_tokens_estimated,
                        event.output_tokens_estimated,
                        event.cost_usd_actual,
                        event.cost_usd_estimated,
                        event.cost_source,
                        event.latency_ms,
                        int(event.success),
                        event.failover_count,
                        event.tests_passed_count,
                        event.tests_failed_count,
                        event.files_changed_count,
                        None if event.user_accepted is None else int(event.user_accepted),
                        event.measurement_source,
                        _json(event.rejected_alternatives),
                    ),
                )
                connection.execute("DELETE FROM provider_attempts WHERE request_id = ?", (event.request_id,))
                for attempt in provider_attempts:
                    connection.execute(
                        """
                        INSERT INTO provider_attempts (
                            request_id, timestamp, attempt_index, agent, provider, model,
                            success, latency_ms, error_type, status_code, cost_usd, cost_source
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.request_id,
                            event.timestamp,
                            int(attempt.get("attempt_index") or 0),
                            str(attempt.get("agent") or ""),
                            str(attempt.get("provider") or ""),
                            str(attempt.get("model") or ""),
                            int(bool(attempt.get("success"))),
                            _optional_float(attempt.get("latency_ms")),
                            str(attempt.get("error_type") or ""),
                            _optional_int(attempt.get("status_code")),
                            _optional_float(attempt.get("cost_usd")),
                            str(attempt.get("cost_source") or event.cost_source),
                        ),
                    )
                connection.execute("DELETE FROM baseline_comparisons WHERE request_id = ?", (event.request_id,))
                for baseline in baselines:
                    connection.execute(
                        """
                        INSERT INTO baseline_comparisons (
                            request_id, baseline_name, baseline_provider, baseline_model,
                            baseline_agent, cost_usd, cost_source, savings_usd,
                            savings_pct, comparison
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.request_id,
                            baseline.baseline_name,
                            baseline.baseline_provider,
                            baseline.baseline_model,
                            baseline.baseline_agent,
                            baseline.cost_usd,
                            baseline.cost_source,
                            baseline.savings_usd,
                            baseline.savings_pct,
                            baseline.comparison,
                        ),
                    )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO evaluations (
                        request_id, timestamp, success_boolean, quality_score_0_to_1,
                        evaluation_method, test_command, tests_passed, user_rating, judge_model
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evaluation.request_id,
                        evaluation.timestamp,
                        int(evaluation.success_boolean),
                        evaluation.quality_score_0_to_1,
                        evaluation.evaluation_method,
                        evaluation.test_command,
                        None if evaluation.tests_passed is None else int(evaluation.tests_passed),
                        evaluation.user_rating,
                        evaluation.judge_model,
                    ),
                )

    def summary(self, *, limit: int = 25) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_summary(self.path)
        try:
            with closing(sqlite3.connect(self.path)) as connection:
                with connection:
                    _ensure_schema(connection)
                connection.row_factory = sqlite3.Row
                request_count = int(connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0] or 0)
                source_rows = connection.execute(
                    """
                    SELECT measurement_source, COUNT(*) AS count
                    FROM requests
                    GROUP BY measurement_source
                    ORDER BY measurement_source
                    """
                ).fetchall()
                costs = connection.execute(
                    """
                    SELECT
                        SUM(COALESCE(cost_usd_actual, 0.0)) AS actual,
                        SUM(COALESCE(cost_usd_estimated, 0.0)) AS estimated,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) AS successes,
                        SUM(CASE WHEN success THEN 0 ELSE 1 END) AS failures,
                        SUM(COALESCE(tests_passed_count, 0)) AS tests_passed,
                        SUM(COALESCE(tests_failed_count, 0)) AS tests_failed,
                        SUM(COALESCE(files_changed_count, 0)) AS files_changed,
                        SUM(CASE WHEN user_accepted THEN 1 ELSE 0 END) AS accepted
                    FROM requests
                    """
                ).fetchone()
                baselines = connection.execute(
                    """
                    SELECT
                        baseline_name,
                        COUNT(*) AS request_count,
                        SUM(CASE WHEN cost_usd IS NOT NULL THEN 1 ELSE 0 END) AS priced_count,
                        SUM(COALESCE(cost_usd, 0.0)) AS baseline_cost_usd,
                        SUM(COALESCE(savings_usd, 0.0)) AS savings_usd
                    FROM baseline_comparisons
                    GROUP BY baseline_name
                    ORDER BY baseline_name
                    """
                ).fetchall()
                token_baselines = connection.execute(
                    """
                    SELECT
                        baseline_name,
                        SUM(
                            CASE
                                WHEN cost_usd > COALESCE(r.cost_usd_actual, r.cost_usd_estimated, 0.0)
                                THEN COALESCE(r.input_tokens_actual, r.input_tokens_estimated, 0)
                                   + COALESCE(r.output_tokens_actual, r.output_tokens_estimated, 0)
                                ELSE 0
                            END
                        ) AS tokens_saved
                    FROM baseline_comparisons b
                    JOIN requests r ON r.request_id = b.request_id
                    GROUP BY baseline_name
                    ORDER BY baseline_name
                    """
                ).fetchall()
                recent = connection.execute(
                    """
                    SELECT request_id, timestamp, route, task_type, selected_provider,
                           selected_model, cost_usd_actual, cost_usd_estimated,
                           cost_source, measurement_source, success, failover_count,
                           tests_passed_count, tests_failed_count, files_changed_count,
                           user_accepted, input_tokens_actual, output_tokens_actual,
                           input_tokens_estimated, output_tokens_estimated,
                           rejected_alternatives_json
                    FROM requests
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (max(1, min(100, int(limit))),),
                ).fetchall()
        except sqlite3.Error:
            return _empty_summary(self.path, unavailable=True)
        measurement_sources = {
            str(row["measurement_source"] or "unknown"): int(row["count"] or 0)
            for row in source_rows
        }
        actual_count = int(measurement_sources.get("actual") or 0)
        mixed_count = int(measurement_sources.get("mixed") or 0)
        estimated_count = int(measurement_sources.get("estimated") or 0)
        actual_usage_pct = round((actual_count / max(1, request_count)) * 100, 2)
        estimated_usage_pct = round((estimated_count / max(1, request_count)) * 100, 2)
        confidence_level = (
            "high"
            if request_count > 0 and actual_usage_pct >= 95
            else "medium"
            if request_count > 0 and (actual_usage_pct + mixed_count / max(1, request_count) * 100) >= 70
            else "low"
            if request_count > 0
            else "none"
        )
        return {
            "object": "agent_hub.usage_ledger",
            "path": str(self.path),
            "schema_version": LEDGER_SCHEMA_VERSION,
            "request_count": request_count,
            "measurement_sources": measurement_sources,
            "success_count": int(costs["successes"] or 0) if costs else 0,
            "failure_count": int(costs["failures"] or 0) if costs else 0,
            "tests_passed_count": int(costs["tests_passed"] or 0) if costs else 0,
            "tests_failed_count": int(costs["tests_failed"] or 0) if costs else 0,
            "files_changed_count": int(costs["files_changed"] or 0) if costs else 0,
            "user_accepted_count": int(costs["accepted"] or 0) if costs else 0,
            "confidence": {
                "level": confidence_level,
                "actual_usage_pct": actual_usage_pct,
                "mixed_usage_pct": round((mixed_count / max(1, request_count)) * 100, 2),
                "estimated_usage_pct": estimated_usage_pct,
                "actual_usage_requests": actual_count,
                "mixed_usage_requests": mixed_count,
                "estimated_usage_requests": estimated_count,
            },
            "total_actual_cost_usd": round(float(costs["actual"] or 0.0), 8) if costs else 0.0,
            "total_estimated_cost_usd": round(float(costs["estimated"] or 0.0), 8) if costs else 0.0,
            "baseline_savings": [
                {
                    "baseline_name": row["baseline_name"],
                    "request_count": int(row["request_count"] or 0),
                    "priced_count": int(row["priced_count"] or 0),
                    "baseline_cost_usd": round(float(row["baseline_cost_usd"] or 0.0), 8),
                    "savings_usd": round(float(row["savings_usd"] or 0.0), 8),
                    "tokens_saved": _tokens_saved_for_baseline(token_baselines, str(row["baseline_name"] or "")),
                }
                for row in baselines
            ],
            "recent_requests": [_recent_request_dict(row) for row in recent],
        }


def usage_ledger_path(config: HubConfig) -> Path:
    configured = os.environ.get(DEFAULT_LEDGER_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    state_dir = Path(config.state_dir)
    if not state_dir.is_absolute() and state_dir.as_posix().replace("\\", "/") == ".agent-hub/state":
        return Path.home() / ".agent-hub" / "usage.sqlite"
    if state_dir.name == "state" and state_dir.parent.name == ".agent-hub":
        return Path.home() / ".agent-hub" / "usage.sqlite"
    if state_dir.name:
        return state_dir.parent / "usage.sqlite"
    return Path.home() / ".agent-hub" / "usage.sqlite"


def usage_ledger_summary(config: HubConfig, *, limit: int = 25) -> dict[str, Any]:
    return UsageLedger(usage_ledger_path(config)).summary(limit=limit)


def configured_model_prices(config: HubConfig) -> list[ModelPrice]:
    rows: list[ModelPrice] = []
    for agent in config.agents.values():
        rows.append(model_price_for_agent(agent))
    return rows


def model_price_for_agent(agent: AgentConfig) -> ModelPrice:
    if agent.free is True:
        input_price = 0.0
        output_price = 0.0
    else:
        input_price = _optional_float(agent.cost_per_million_input)
        output_price = _optional_float(agent.cost_per_million_output)
    return ModelPrice(
        provider=agent.provider,
        model=agent.model,
        input_per_million=input_price,
        output_per_million=output_price,
        cached_input_per_million=None,
        effective_from="config",
        source=f"config:{agent.name}",
        agent=agent.name,
    )


def record_completed_request(
    *,
    config: HubConfig,
    request_id: str,
    request: HubRequest,
    agent: AgentConfig,
    model: str,
    usage: dict[str, Any],
    output_text: str,
    latency_seconds: float | None,
    success: bool,
    failover: list[FailoverEvent],
    candidate_scores: list[dict[str, Any]] | None = None,
    task_type: str = "",
    input_tokens_estimated: int = 0,
    output_tokens_estimated: int = 0,
    tests_passed_count: int = 0,
    tests_failed_count: int = 0,
    files_changed_count: int = 0,
    user_accepted: bool | None = None,
) -> None:
    now = time.time()
    selected_model = model or agent.model
    token_measurement = _token_measurement(
        usage,
        output_text=output_text,
        input_tokens_estimated=input_tokens_estimated,
        output_tokens_estimated=output_tokens_estimated,
    )
    selected_price = model_price_for_agent(agent)
    cost_actual, cost_estimated, cost_source = _request_costs(
        selected_price,
        token_measurement,
    )
    event = UsageEvent(
        request_id=request_id,
        timestamp=now,
        session_id=request.session_id,
        route=request.route or "",
        task_type=task_type or "general",
        selected_agent=agent.name,
        selected_provider=agent.provider,
        selected_model=selected_model,
        input_tokens_actual=token_measurement["input_actual"],
        output_tokens_actual=token_measurement["output_actual"],
        input_tokens_estimated=token_measurement["input_estimated"],
        output_tokens_estimated=token_measurement["output_estimated"],
        cost_usd_actual=cost_actual,
        cost_usd_estimated=cost_estimated,
        cost_source=cost_source,
        latency_ms=round(max(0.0, float(latency_seconds or 0.0)) * 1000, 2) if latency_seconds is not None else None,
        success=success,
        failover_count=len(failover),
        tests_passed_count=max(0, int(tests_passed_count or 0)),
        tests_failed_count=max(0, int(tests_failed_count or 0)),
        files_changed_count=max(0, int(files_changed_count or 0)),
        user_accepted=user_accepted,
        measurement_source=token_measurement["source"],
        rejected_alternatives=_rejected_alternatives(candidate_scores or [], selected_agent=agent.name),
    )
    baselines = _baseline_comparisons(config, event, candidate_scores or [], selected_price)
    attempts = _provider_attempt_rows(
        event,
        failover=failover,
        selected_price=selected_price,
        selected_cost=cost_actual if cost_actual is not None else cost_estimated,
    )
    evaluation = EvaluationResult(
        request_id=request_id,
        timestamp=now,
        success_boolean=success,
        quality_score_0_to_1=None,
        evaluation_method="provider_success_only",
        tests_passed=(tests_failed_count <= 0) if tests_passed_count or tests_failed_count else None,
        user_rating=1.0 if user_accepted is True else (0.0 if user_accepted is False else None),
    )
    UsageLedger(usage_ledger_path(config)).record(
        event,
        provider_attempts=attempts,
        model_prices=configured_model_prices(config),
        baselines=baselines,
        evaluation=evaluation,
    )


def estimate_cost_for_agent(agent: AgentConfig, *, input_tokens: int, output_tokens: int) -> float | None:
    return _cost_for_price(
        model_price_for_agent(agent),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def estimate_named_baselines(
    config: HubConfig,
    *,
    selected_agent: str,
    input_tokens: int,
    output_tokens: int,
    candidate_agents: list[str] | None = None,
) -> dict[str, Any]:
    agent = config.agents.get(selected_agent)
    if agent is None:
        return {
            "selected_agent": selected_agent,
            "selected_cost_usd": None,
            "measurement_source": "estimated",
            "named_baselines": [],
        }
    event = UsageEvent(
        request_id="estimate",
        timestamp=time.time(),
        session_id="",
        route="",
        task_type="general",
        selected_agent=agent.name,
        selected_provider=agent.provider,
        selected_model=agent.model,
        input_tokens_actual=None,
        output_tokens_actual=None,
        input_tokens_estimated=max(0, int(input_tokens or 0)),
        output_tokens_estimated=max(0, int(output_tokens or 0)),
        cost_usd_actual=None,
        cost_usd_estimated=estimate_cost_for_agent(
            agent,
            input_tokens=max(0, int(input_tokens or 0)),
            output_tokens=max(0, int(output_tokens or 0)),
        ),
        cost_source="estimated",
        latency_ms=None,
        success=True,
        failover_count=0,
        measurement_source="estimated",
    )
    candidate_scores = [{"agent": name} for name in (candidate_agents or []) if name in config.agents]
    baselines = _baseline_comparisons(config, event, candidate_scores, model_price_for_agent(agent))
    return {
        "selected_agent": agent.name,
        "selected_provider": agent.provider,
        "selected_model": agent.model,
        "selected_cost_usd": event.cost_usd_estimated,
        "measurement_source": "estimated",
        "named_baselines": [
            {
                "baseline_name": row.baseline_name,
                "baseline_agent": row.baseline_agent,
                "baseline_provider": row.baseline_provider,
                "baseline_model": row.baseline_model,
                "cost_usd": row.cost_usd,
                "cost_source": row.cost_source,
                "savings_usd": row.savings_usd,
                "savings_pct": row.savings_pct,
                "comparison": row.comparison,
            }
            for row in baselines
        ],
    }


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS requests (
            request_id TEXT PRIMARY KEY,
            timestamp REAL NOT NULL,
            session_id TEXT,
            route TEXT,
            task_type TEXT,
            selected_agent TEXT,
            selected_provider TEXT,
            selected_model TEXT,
            input_tokens_actual INTEGER,
            output_tokens_actual INTEGER,
            input_tokens_estimated INTEGER NOT NULL DEFAULT 0,
            output_tokens_estimated INTEGER NOT NULL DEFAULT 0,
            cost_usd_actual REAL,
            cost_usd_estimated REAL,
            cost_source TEXT NOT NULL DEFAULT 'estimated',
            latency_ms REAL,
            success INTEGER NOT NULL DEFAULT 0,
            failover_count INTEGER NOT NULL DEFAULT 0,
            tests_passed_count INTEGER NOT NULL DEFAULT 0,
            tests_failed_count INTEGER NOT NULL DEFAULT 0,
            files_changed_count INTEGER NOT NULL DEFAULT 0,
            user_accepted INTEGER,
            measurement_source TEXT NOT NULL DEFAULT 'estimated',
            rejected_alternatives_json TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            attempt_index INTEGER NOT NULL,
            agent TEXT,
            provider TEXT,
            model TEXT,
            success INTEGER NOT NULL DEFAULT 0,
            latency_ms REAL,
            error_type TEXT,
            status_code INTEGER,
            cost_usd REAL,
            cost_source TEXT,
            FOREIGN KEY(request_id) REFERENCES requests(request_id)
        )
        """
    )
    _ensure_columns(
        connection,
        "requests",
        {
            "tests_passed_count": "INTEGER NOT NULL DEFAULT 0",
            "tests_failed_count": "INTEGER NOT NULL DEFAULT 0",
            "files_changed_count": "INTEGER NOT NULL DEFAULT 0",
            "user_accepted": "INTEGER",
        },
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS model_prices (
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            input_per_million REAL,
            output_per_million REAL,
            cached_input_per_million REAL,
            effective_from TEXT NOT NULL,
            source TEXT NOT NULL,
            recorded_at REAL NOT NULL,
            PRIMARY KEY(provider, model, effective_from, source)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS evaluations (
            request_id TEXT PRIMARY KEY,
            timestamp REAL NOT NULL,
            success_boolean INTEGER NOT NULL,
            quality_score_0_to_1 REAL,
            evaluation_method TEXT NOT NULL,
            test_command TEXT,
            tests_passed INTEGER,
            user_rating REAL,
            judge_model TEXT,
            FOREIGN KEY(request_id) REFERENCES requests(request_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS baseline_comparisons (
            request_id TEXT NOT NULL,
            baseline_name TEXT NOT NULL,
            baseline_provider TEXT,
            baseline_model TEXT,
            baseline_agent TEXT,
            cost_usd REAL,
            cost_source TEXT NOT NULL,
            savings_usd REAL,
            savings_pct REAL,
            comparison TEXT,
            PRIMARY KEY(request_id, baseline_name),
            FOREIGN KEY(request_id) REFERENCES requests(request_id)
        )
        """
    )
    connection.execute("PRAGMA user_version = 1")


def _upsert_model_prices(connection: sqlite3.Connection, prices: list[ModelPrice]) -> None:
    now = time.time()
    for price in prices:
        connection.execute(
            """
            INSERT OR REPLACE INTO model_prices (
                provider, model, input_per_million, output_per_million,
                cached_input_per_million, effective_from, source, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                price.provider,
                price.model,
                price.input_per_million,
                price.output_per_million,
                price.cached_input_per_million,
                price.effective_from,
                price.source,
                now,
            ),
        )


def _ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _token_measurement(
    usage: dict[str, Any],
    *,
    output_text: str,
    input_tokens_estimated: int,
    output_tokens_estimated: int,
) -> dict[str, Any]:
    input_actual = _usage_int(usage, "prompt_tokens", "input_tokens")
    output_actual = _usage_int(usage, "completion_tokens", "output_tokens")
    total_actual = _usage_int(usage, "total_tokens")
    if total_actual is not None and input_actual is None and output_actual is not None:
        input_actual = max(0, total_actual - output_actual)
    if total_actual is not None and output_actual is None and input_actual is not None:
        output_actual = max(0, total_actual - input_actual)
    cost_actual = _usage_cost(
        usage,
        "cost_usd",
        "total_cost_usd",
        "provider_cost_usd",
        "price_usd",
    )
    estimated_input = max(0, int(input_tokens_estimated or 0))
    estimated_output = max(0, int(output_tokens_estimated or 0))
    if estimated_output <= 0:
        estimated_output = max(1, len(str(output_text or "")) // 4) if output_text else 0
    has_input = input_actual is not None
    has_output = output_actual is not None
    if has_input and has_output:
        source = "actual"
    elif has_input or has_output:
        source = "mixed"
    else:
        source = "estimated"
    return {
        "source": source,
        "input_actual": input_actual,
        "output_actual": output_actual,
        "input_effective": input_actual if input_actual is not None else estimated_input,
        "output_effective": output_actual if output_actual is not None else estimated_output,
        "input_estimated": estimated_input,
        "output_estimated": estimated_output,
        "cost_actual": cost_actual,
    }


def _request_costs(price: ModelPrice, token_measurement: dict[str, Any]) -> tuple[float | None, float | None, str]:
    reported_actual = _optional_float(token_measurement.get("cost_actual"))
    actual = round(max(0.0, float(reported_actual)), 8) if reported_actual is not None else None
    estimated = _cost_for_price(
        price,
        input_tokens=int(token_measurement["input_estimated"]),
        output_tokens=int(token_measurement["output_estimated"]),
    )
    if token_measurement["source"] == "actual" and actual is None:
        actual = _cost_for_price(
            price,
            input_tokens=int(token_measurement["input_effective"]),
            output_tokens=int(token_measurement["output_effective"]),
        )
    elif token_measurement["source"] == "mixed":
        estimated = _cost_for_price(
            price,
            input_tokens=int(token_measurement["input_effective"]),
            output_tokens=int(token_measurement["output_effective"]),
        )
    if not price.priced:
        if actual is not None:
            return actual, None, "provider_reported"
        return None, None, "unpriced"
    if reported_actual is not None:
        return actual, estimated, "provider_reported"
    return actual, estimated, str(token_measurement["source"])


def _cost_for_price(price: ModelPrice, *, input_tokens: int, output_tokens: int) -> float | None:
    if not price.priced:
        return None
    total = (
        max(0, int(input_tokens or 0)) * float(price.input_per_million or 0.0)
        + max(0, int(output_tokens or 0)) * float(price.output_per_million or 0.0)
    ) / 1_000_000
    return round(total, 8)


def _baseline_comparisons(
    config: HubConfig,
    event: UsageEvent,
    candidate_scores: list[dict[str, Any]],
    selected_price: ModelPrice,
) -> list[BaselineComparison]:
    selected_cost = event.cost_usd_actual if event.cost_usd_actual is not None else event.cost_usd_estimated
    baselines = [
        ("vs_user_default_model", _default_agent(config)),
        ("vs_claude_sonnet", _find_named_agent(config, terms=("claude", "sonnet"))),
        ("vs_gpt_4_1", _find_named_agent(config, terms=("gpt-4.1",), alternates=("gpt-4-1",))),
        ("vs_static_routing", _static_route_agent(config, candidate_scores)),
        ("vs_cheapest_model_only", _cheapest_priced_agent(config, event, candidate_scores)),
    ]
    rows: list[BaselineComparison] = []
    for name, baseline_agent in baselines:
        rows.append(_baseline_row(name, baseline_agent, event, selected_cost))
    return rows


def _baseline_row(
    baseline_name: str,
    baseline_agent: AgentConfig | None,
    event: UsageEvent,
    selected_cost: float | None,
) -> BaselineComparison:
    if baseline_agent is None:
        return BaselineComparison(
            baseline_name=baseline_name,
            baseline_agent="",
            baseline_provider="",
            baseline_model="",
            cost_usd=None,
            cost_source="unpriced",
            savings_usd=None,
            savings_pct=None,
            comparison=f"{baseline_name}: no configured priced baseline",
        )
    baseline_price = model_price_for_agent(baseline_agent)
    input_tokens = event.input_tokens_actual if event.input_tokens_actual is not None else event.input_tokens_estimated
    output_tokens = event.output_tokens_actual if event.output_tokens_actual is not None else event.output_tokens_estimated
    baseline_cost = _cost_for_price(
        baseline_price,
        input_tokens=max(0, int(input_tokens or 0)),
        output_tokens=max(0, int(output_tokens or 0)),
    )
    if baseline_cost is None or selected_cost is None:
        return BaselineComparison(
            baseline_name=baseline_name,
            baseline_agent=baseline_agent.name,
            baseline_provider=baseline_agent.provider,
            baseline_model=baseline_agent.model,
            cost_usd=None,
            cost_source="unpriced",
            savings_usd=None,
            savings_pct=None,
            comparison=f"{baseline_name}: baseline or selected model is missing complete pricing",
        )
    savings = baseline_cost - selected_cost
    savings_pct = (savings / baseline_cost) if baseline_cost > 0 else 0.0
    return BaselineComparison(
        baseline_name=baseline_name,
        baseline_agent=baseline_agent.name,
        baseline_provider=baseline_agent.provider,
        baseline_model=baseline_agent.model,
        cost_usd=baseline_cost,
        cost_source=event.measurement_source,
        savings_usd=round(savings, 8),
        savings_pct=round(savings_pct, 6),
        comparison=f"{baseline_name}: selected cost compared with {baseline_agent.name}",
    )


def _provider_attempt_rows(
    event: UsageEvent,
    *,
    failover: list[FailoverEvent],
    selected_price: ModelPrice,
    selected_cost: float | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(failover, start=1):
        rows.append(
            {
                "attempt_index": index,
                "agent": item.agent,
                "provider": item.provider,
                "model": item.model,
                "success": False,
                "latency_ms": None,
                "error_type": item.error_type or "",
                "status_code": item.status_code,
                "cost_usd": None,
                "cost_source": "failed",
            }
        )
    if not event.success and rows:
        return rows
    rows.append(
        {
            "attempt_index": len(rows) + 1,
            "agent": event.selected_agent,
            "provider": event.selected_provider,
            "model": event.selected_model,
            "success": event.success,
            "latency_ms": event.latency_ms,
            "error_type": "",
            "status_code": None,
            "cost_usd": selected_cost,
            "cost_source": event.cost_source if selected_price.priced else "unpriced",
        }
    )
    return rows


def _default_agent(config: HubConfig) -> AgentConfig | None:
    for name in config.default_route:
        agent = config.agents.get(name)
        if agent and agent.enabled:
            return agent
    return next((agent for agent in config.agents.values() if agent.enabled), None)


def _static_route_agent(config: HubConfig, candidate_scores: list[dict[str, Any]]) -> AgentConfig | None:
    for row in candidate_scores:
        agent = config.agents.get(str(row.get("agent") or ""))
        if agent and agent.enabled:
            return agent
    return _default_agent(config)


def _find_named_agent(
    config: HubConfig,
    *,
    terms: tuple[str, ...],
    alternates: tuple[str, ...] = (),
) -> AgentConfig | None:
    lowered_terms = tuple(term.lower() for term in terms)
    lowered_alternates = tuple(term.lower() for term in alternates)
    for agent in config.agents.values():
        if not agent.enabled:
            continue
        haystack = " ".join(
            str(value or "").lower()
            for value in (agent.name, agent.provider, agent.provider_type, agent.model)
        )
        if all(term in haystack for term in lowered_terms) or any(term in haystack for term in lowered_alternates):
            return agent
    return None


def _cheapest_priced_agent(
    config: HubConfig,
    event: UsageEvent,
    candidate_scores: list[dict[str, Any]],
) -> AgentConfig | None:
    candidate_names = [str(row.get("agent") or "") for row in candidate_scores if isinstance(row, dict)]
    agents = [config.agents[name] for name in candidate_names if name in config.agents]
    if not agents:
        agents = [agent for agent in config.agents.values() if agent.enabled]
    priced: list[tuple[AgentConfig, float]] = []
    for agent in agents:
        if not agent.enabled:
            continue
        cost = _cost_for_price(
            model_price_for_agent(agent),
            input_tokens=event.input_tokens_actual if event.input_tokens_actual is not None else event.input_tokens_estimated,
            output_tokens=event.output_tokens_actual if event.output_tokens_actual is not None else event.output_tokens_estimated,
        )
        if cost is not None:
            priced.append((agent, cost))
    if not priced:
        return None
    return min(priced, key=lambda item: (item[1], item[0].name))[0]


def _rejected_alternatives(candidate_scores: list[dict[str, Any]], *, selected_agent: str) -> list[dict[str, Any]]:
    rows = []
    for row in candidate_scores:
        if not isinstance(row, dict) or row.get("agent") == selected_agent:
            continue
        rows.append(
            {
                "agent": row.get("agent"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "estimated_cost_usd": row.get("estimated_cost_usd"),
                "routing_score": row.get("routing_score") or row.get("final_routing_score"),
                "why": row.get("why"),
            }
        )
    return rows[:12]


def _usage_int(usage: dict[str, Any], *keys: str) -> int | None:
    if not isinstance(usage, dict):
        return None
    for key in keys:
        if key not in usage:
            continue
        value = _optional_int(usage.get(key))
        if value is not None:
            return max(0, value)
    return None


def _usage_cost(usage: dict[str, Any], *keys: str) -> float | None:
    if not isinstance(usage, dict):
        return None
    for key in keys:
        value = _optional_float(usage.get(key))
        if value is not None:
            return max(0.0, value)
    return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _json_list(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        import json

        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _recent_request_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["rejected_models"] = _json_list(str(data.pop("rejected_alternatives_json") or ""))
    data["input_tokens"] = data.get("input_tokens_actual")
    if data["input_tokens"] is None:
        data["input_tokens"] = data.get("input_tokens_estimated")
    data["output_tokens"] = data.get("output_tokens_actual")
    if data["output_tokens"] is None:
        data["output_tokens"] = data.get("output_tokens_estimated")
    return data


def _tokens_saved_for_baseline(rows: list[sqlite3.Row], baseline_name: str) -> int:
    for row in rows:
        if str(row["baseline_name"] or "") == baseline_name:
            return int(row["tokens_saved"] or 0)
    return 0


def _empty_summary(path: Path, *, unavailable: bool = False) -> dict[str, Any]:
    return {
        "object": "agent_hub.usage_ledger",
        "path": str(path),
        "schema_version": LEDGER_SCHEMA_VERSION,
        "request_count": 0,
        "measurement_sources": {},
        "success_count": 0,
        "failure_count": 0,
        "tests_passed_count": 0,
        "tests_failed_count": 0,
        "files_changed_count": 0,
        "user_accepted_count": 0,
        "confidence": {
            "level": "none",
            "actual_usage_pct": 0.0,
            "mixed_usage_pct": 0.0,
            "estimated_usage_pct": 0.0,
            "actual_usage_requests": 0,
            "mixed_usage_requests": 0,
            "estimated_usage_requests": 0,
        },
        "total_actual_cost_usd": 0.0,
        "total_estimated_cost_usd": 0.0,
        "baseline_savings": [],
        "recent_requests": [],
        "unavailable": unavailable,
    }


__all__ = [
    "BaselineComparison",
    "EvaluationResult",
    "ModelPrice",
    "UsageEvent",
    "UsageLedger",
    "configured_model_prices",
    "estimate_cost_for_agent",
    "estimate_named_baselines",
    "model_price_for_agent",
    "record_completed_request",
    "usage_ledger_path",
    "usage_ledger_summary",
]
