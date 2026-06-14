from __future__ import annotations

from typing import Any


def visual_proof_dashboard_body(
    *,
    usage: dict[str, Any] | None = None,
    benchmarks: dict[str, Any] | None = None,
    routing_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    usage = usage or {}
    benchmarks = benchmarks or {}
    routing_memory = routing_memory or {}
    summary = benchmarks.get("summary") if isinstance(benchmarks.get("summary"), dict) else {}
    latest = _latest_report_summary(benchmarks)
    comparison = latest.get("comparison") if isinstance(latest.get("comparison"), dict) else {}
    outcomes = latest.get("outcome_metrics") if isinstance(latest.get("outcome_metrics"), dict) else {}
    fallback = routing_memory.get("fallback_frequency") if isinstance(routing_memory.get("fallback_frequency"), dict) else {}
    cards = [
        _card("Tokens Saved", _percent(comparison.get("token_reduction")), "tokens_saved"),
        _card("Cost Saved", _money(outcomes.get("cost_saved_usd")), "cost_saved"),
        _card("Requests Optimized", usage.get("request_count") or summary.get("total_result_count") or 0, "requests_optimized"),
        _card("Models Avoided", outcomes.get("models_avoided") or _models_avoided(benchmarks), "models_avoided"),
        _card("Failures Prevented", fallback.get("fallbacks") or outcomes.get("failures_prevented") or 0, "failures_prevented"),
        _card("Success Rate", _percent_value(outcomes.get("success_rate") or latest.get("success_rate")), "success_rate"),
    ]
    return {
        "object": "agent_hub.visual_proof_dashboard",
        "cards": cards,
        "trend_graphs": _trend_graphs(benchmarks),
        "summary": {card["id"]: card["value"] for card in cards},
    }


def _latest_report_summary(benchmarks: dict[str, Any]) -> dict[str, Any]:
    reports = benchmarks.get("reports") if isinstance(benchmarks.get("reports"), list) else []
    if reports and isinstance(reports[0], dict):
        summary = reports[0].get("summary")
        return summary if isinstance(summary, dict) else reports[0]
    return {}


def _trend_graphs(benchmarks: dict[str, Any]) -> list[dict[str, Any]]:
    reports = benchmarks.get("reports") if isinstance(benchmarks.get("reports"), list) else []
    points = []
    for report in reversed(reports[-12:]):
        if not isinstance(report, dict):
            continue
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        comparison = summary.get("comparison") if isinstance(summary.get("comparison"), dict) else {}
        points.append({
            "time": report.get("updated_at"),
            "token_reduction": comparison.get("token_reduction"),
            "cost_reduction": comparison.get("cost_reduction"),
            "success_delta": comparison.get("success_delta"),
        })
    return [{"id": "benchmark_trend", "points": points}]


def _models_avoided(benchmarks: dict[str, Any]) -> int:
    snapshot = benchmarks.get("coverage_snapshot") if isinstance(benchmarks.get("coverage_snapshot"), dict) else {}
    rows = snapshot.get("results") if isinstance(snapshot.get("results"), list) else []
    return sum(1 for row in rows if isinstance(row, dict) and str(row.get("status") or "").lower() != "ready")


def _card(label: str, value: Any, key: str) -> dict[str, Any]:
    return {"id": key, "label": label, "value": value}


def _percent(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "--"


def _percent_value(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if number <= 1:
        number *= 100
    return f"{number:.1f}%"


def _money(value: Any) -> str:
    try:
        return f"${float(value):.4f}"
    except (TypeError, ValueError):
        return "--"
