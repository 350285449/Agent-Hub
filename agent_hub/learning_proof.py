from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from .observability import recent_events


SECONDS_PER_WEEK = 7 * 24 * 60 * 60


def learning_dashboard_body(config: Any, router: Any) -> dict[str, Any]:
    optimization = router.adaptive_learning.optimization_summary()
    health = router.health_snapshot(include_history=True)
    model_rows = _model_learning_rows(optimization, health)
    changes = _routing_changes(optimization, model_rows)
    failures = sum(int(row.get("failures") or 0) for row in model_rows)
    successes = sum(int(row.get("successes") or 0) for row in model_rows)
    return {
        "object": "agent_hub.learning_dashboard",
        "window": "last_30_days",
        "summary": {
            "providers": len(model_rows),
            "successes": successes,
            "failures": failures,
            "routes": successes + failures,
            "routing_changes": len(changes),
            "adaptive_learning_enabled": bool(getattr(config, "adaptive_learning_enabled", True)),
            "adaptive_routing_enabled": bool(getattr(config, "adaptive_routing_enabled", True)),
        },
        "models": model_rows,
        "routing_changes": changes,
        "recent_decisions": optimization.get("recent_optimization_decisions", []),
        "route_history": route_history_body(config, weeks=4),
    }


def route_history_body(config: Any, *, weeks: int = 4) -> dict[str, Any]:
    events = recent_events(config.state_dir, "routing", limit=1000)
    now = time.time()
    bucket_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: dict[int, int] = defaultdict(int)
    for event in events:
        if not isinstance(event, dict) or event.get("type") not in {"routing_decision", "streaming_decision"}:
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            if data.get("type") not in {"routing_decision", "streaming_decision"}:
                continue
            event = {**data, **event}
        timestamp = _float(event.get("time") or event.get("timestamp")) or now
        age_weeks = int(max(0.0, now - timestamp) // SECONDS_PER_WEEK)
        if age_weeks >= max(1, weeks):
            continue
        decision = event.get("routing_decision") if isinstance(event.get("routing_decision"), dict) else {}
        label = str(event.get("agent") or decision.get("selected_agent") or event.get("model") or "unknown")
        bucket_counts[age_weeks][label] += 1
        totals[age_weeks] += 1
    rows = []
    for age in range(max(1, weeks) - 1, -1, -1):
        total = totals.get(age, 0)
        distribution = {
            name: {
                "count": count,
                "percentage": round((count / max(1, total)) * 100, 2),
            }
            for name, count in sorted(bucket_counts.get(age, {}).items())
        }
        rows.append(
            {
                "week": f"Week {max(1, weeks) - age}",
                "age_weeks": age,
                "route_count": total,
                "distribution": distribution,
            }
        )
    return {
        "object": "agent_hub.route_history",
        "window_weeks": max(1, weeks),
        "total_routes": sum(totals.values()),
        "weeks": rows,
    }


def format_route_history(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for week in report.get("weeks", []):
        if not isinstance(week, dict):
            continue
        lines.append(str(week.get("week") or "Week"))
        distribution = week.get("distribution") if isinstance(week.get("distribution"), dict) else {}
        if not distribution:
            lines.append("No routes")
            lines.append("")
            continue
        for name, row in sorted(distribution.items(), key=lambda item: -float(item[1].get("percentage") or 0.0)):
            lines.append(f"{name}: {row.get('percentage')}%")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _model_learning_rows(optimization: dict[str, Any], health: dict[str, Any]) -> list[dict[str, Any]]:
    scorecards = optimization.get("model_scorecards") if isinstance(optimization.get("model_scorecards"), list) else []
    by_agent = {str(row.get("agent") or ""): row for row in scorecards if isinstance(row, dict)}
    rows: list[dict[str, Any]] = []
    for agent, row in sorted(health.items()):
        if not isinstance(row, dict):
            continue
        successes = int(row.get("success_count") or 0)
        failures = int(row.get("failure_count") or 0)
        scorecard = by_agent.get(agent, {})
        nested = scorecard.get("scorecard") if isinstance(scorecard.get("scorecard"), dict) else {}
        if successes + failures <= 0 and nested:
            successes = int(nested.get("successes") or 0)
            failures = int(nested.get("failures") or 0)
        rows.append(
            {
                "agent": agent,
                "provider": row.get("provider"),
                "model": row.get("model"),
                "successes": successes,
                "failures": failures,
                "success_rate": round(successes / max(1, successes + failures), 4),
                "average_latency_ms": row.get("average_latency_ms", 0.0),
                "adaptive_bonus": scorecard.get("adaptive_bonus", 0.0),
                "quality_score": nested.get("quality_score"),
                "attempts": nested.get("attempts", successes + failures),
            }
        )
    seen = {str(row.get("agent") or "") for row in rows}
    for scorecard in scorecards:
        if not isinstance(scorecard, dict):
            continue
        agent = str(scorecard.get("agent") or "")
        if not agent or agent in seen:
            continue
        nested = scorecard.get("scorecard") if isinstance(scorecard.get("scorecard"), dict) else {}
        successes = int(nested.get("successes") or 0)
        failures = int(nested.get("failures") or 0)
        rows.append(
            {
                "agent": agent,
                "provider": scorecard.get("provider"),
                "model": scorecard.get("model"),
                "successes": successes,
                "failures": failures,
                "success_rate": round(float(nested.get("success_rate") or 0.0), 4),
                "average_latency_ms": nested.get("average_latency_ms", 0.0),
                "adaptive_bonus": scorecard.get("adaptive_bonus", 0.0),
                "quality_score": nested.get("quality_score"),
                "attempts": nested.get("attempts", successes + failures),
            }
        )
        seen.add(agent)
    return rows


def _routing_changes(optimization: dict[str, Any], model_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in model_rows:
        bonus = _float(row.get("adaptive_bonus"))
        if abs(bonus) < 0.001:
            continue
        rows.append(
            {
                "agent": row.get("agent"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "direction": "up" if bonus > 0 else "down",
                "adaptive_bonus": round(bonus, 4),
                "reason": "Adaptive learning adjusted routing weight from historical outcomes.",
            }
        )
    recent = optimization.get("recent_optimization_decisions")
    if isinstance(recent, list):
        for item in recent[-10:]:
            if not isinstance(item, dict):
                continue
            if item.get("agent") and item.get("decision"):
                rows.append(
                    {
                        "agent": item.get("agent"),
                        "direction": item.get("decision"),
                        "reason": item.get("reason", "Recent adaptive routing decision."),
                    }
                )
    return rows[:20]


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["format_route_history", "learning_dashboard_body", "route_history_body"]
