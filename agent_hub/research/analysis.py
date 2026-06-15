from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .metrics import load_research_runs
from .telemetry import research_dir


CONTEXT_BUCKETS = (
    ("0 tokens", 0, 0),
    ("1-2k", 1, 2_000),
    ("2k-5k", 2_000, 5_000),
    ("5k-10k", 5_000, 10_000),
    ("10k-25k", 10_000, 25_000),
    ("25k+", 25_000, None),
)


def context_bucket(tokens: int | float | None) -> str:
    value = max(0, int(tokens or 0))
    if value == 0:
        return "0 tokens"
    for label, lower, upper in CONTEXT_BUCKETS:
        if upper is None and value >= lower:
            return label
        if upper is not None and lower <= value < upper:
            return label
    return "25k+"


def analyze_runs(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [_normalize_run(row) for row in runs if row.get("success") is not None]
    total = len(rows)
    successes = sum(1 for row in rows if row["success"])
    total_cost = sum(row["cost_estimate"] for row in rows)
    total_context = sum(row["context_token_count"] for row in rows)
    analysis = {
        "object": "agent_hub.research.analysis",
        "total_runs": total,
        "success_rate": _rate(successes, total),
        "average_validation_score": _average(row["validation_score"] for row in rows),
        "average_latency": _average(row["latency_ms"] for row in rows),
        "average_cost": _average(row["cost_estimate"] for row in rows),
        "average_context_tokens": _average(row["context_token_count"] for row in rows),
        "success_rate_by_model": _success_by(rows, "selected_model"),
        "success_rate_by_task_type": _success_by(rows, "task_type"),
        "success_rate_by_context_bucket": _success_by_context_bucket(rows),
        "validation_score_by_context_bucket": _validation_by_context_bucket(rows),
        "success_per_1k_context_tokens": round(successes / max(1.0, total_context / 1000.0), 6),
        "cost_per_successful_run": round(total_cost / max(1, successes), 8),
        "retry_rate": _rate(sum(1 for row in rows if row["retry_count"] > 0), total),
        "model_efficiency_score": _model_efficiency(rows),
    }
    return analysis


def analyze_research_dir(state_dir: str | Path) -> dict[str, Any]:
    return analyze_runs(load_research_runs(state_dir))


def export_analysis_json(state_dir: str | Path, output: str | Path | None = None) -> Path:
    path = Path(output) if output is not None else research_dir(state_dir) / "analysis.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(analyze_research_dir(state_dir), indent=2, sort_keys=True), encoding="utf-8")
    return path


def compute_pareto_frontier(runs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [_normalize_run(row) for row in runs if row.get("success") is not None]
    frontier = [
        row
        for row in rows
        if not any(_dominates(other, row) for other in rows if other is not row)
    ]
    frontier.sort(
        key=lambda row: (
            -row["validation_score"],
            row["cost_estimate"],
            row["latency_ms"],
            row["context_token_count"],
            row["task_id"],
        )
    )
    return frontier


def export_pareto_frontier_json(state_dir: str | Path, output: str | Path | None = None) -> Path:
    path = Path(output) if output is not None else research_dir(state_dir) / "pareto_frontier.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "object": "agent_hub.research.pareto_frontier",
        "runs": compute_pareto_frontier(load_research_runs(state_dir)),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _dominates(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (
        a["validation_score"] >= b["validation_score"]
        and a["cost_estimate"] <= b["cost_estimate"]
        and a["latency_ms"] <= b["latency_ms"]
        and a["context_token_count"] <= b["context_token_count"]
        and (
            a["validation_score"] > b["validation_score"]
            or a["cost_estimate"] < b["cost_estimate"]
            or a["latency_ms"] < b["latency_ms"]
            or a["context_token_count"] < b["context_token_count"]
        )
    )


def _normalize_run(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(row.get("task_id") or ""),
        "task_type": str(row.get("task_type") or ""),
        "selected_model": str(row.get("selected_model") or row.get("model") or ""),
        "candidate_models": list(row.get("candidate_models") or []),
        "input_tokens": _int(row.get("input_tokens")),
        "output_tokens": _int(row.get("output_tokens")),
        "context_files": list(row.get("context_files") or []),
        "context_token_count": _int(row.get("context_token_count")),
        "latency_ms": _float(row.get("latency_ms")),
        "cost_estimate": _float(row.get("cost_estimate")),
        "validation_score": _float(row.get("validation_score")),
        "success": bool(row.get("success")),
        "retry_count": _int(row.get("retry_count")),
    }


def _success_by(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    return {
        name: {"runs": len(items), "success_rate": _rate(sum(1 for item in items if item["success"]), len(items))}
        for name, items in sorted(grouped.items())
    }


def _success_by_context_bucket(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped = _group_by_context_bucket(rows)
    return {
        label: {"runs": len(items), "success_rate": _rate(sum(1 for item in items if item["success"]), len(items))}
        for label, items in grouped.items()
    }


def _validation_by_context_bucket(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped = _group_by_context_bucket(rows)
    return {
        label: {"runs": len(items), "average_validation_score": _average(item["validation_score"] for item in items)}
        for label, items in grouped.items()
    }


def _group_by_context_bucket(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = {label: [] for label, _lower, _upper in CONTEXT_BUCKETS}
    for row in rows:
        grouped[context_bucket(row["context_token_count"])].append(row)
    return grouped


def _model_efficiency(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["selected_model"] or "unknown"].append(row)
    scores: dict[str, dict[str, Any]] = {}
    for model, items in sorted(grouped.items()):
        success_rate = _rate(sum(1 for item in items if item["success"]), len(items))
        validation = _average(item["validation_score"] for item in items)
        cost = _average(item["cost_estimate"] for item in items)
        latency = _average(item["latency_ms"] for item in items)
        context = _average(item["context_token_count"] for item in items)
        penalty = 1.0 + cost + latency / 10_000.0 + context / 100_000.0
        scores[model] = {
            "runs": len(items),
            "success_rate": success_rate,
            "average_validation_score": validation,
            "average_latency": latency,
            "average_cost": cost,
            "average_context_tokens": context,
            "efficiency_score": round((success_rate * max(0.0, validation)) / penalty, 6),
        }
    return scores


def _average(values: Iterable[float]) -> float:
    rows = [float(value) for value in values]
    return round(sum(rows) / len(rows), 6) if rows else 0.0


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "CONTEXT_BUCKETS",
    "analyze_research_dir",
    "analyze_runs",
    "compute_pareto_frontier",
    "context_bucket",
    "export_analysis_json",
    "export_pareto_frontier_json",
]
