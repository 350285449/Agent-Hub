from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .bayesian_router import BayesianSuccessRouter
from .metrics import load_research_runs, summarize_runs
from .pareto import ModelObjective, pareto_frontier
from .telemetry import research_dir


def generate_research_report(state_dir: str | Path) -> dict[str, str]:
    rows = load_research_runs(state_dir)
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    frontier = _frontier(rows)
    success_rows = _success_rates(rows)
    context_rows = _context_efficiency(rows)
    bayes = _bayesian(rows)

    pareto_path = directory / "pareto_frontier.csv"
    context_path = directory / "context_efficiency.csv"
    success_path = directory / "model_success_rates.csv"
    report_path = directory / "report.md"

    _write_csv(pareto_path, [asdict(item) for item in frontier], ["model", "quality", "cost", "latency", "task_type"])
    _write_csv(context_path, context_rows, ["context_token_count", "runs", "success_rate", "average_validation_score"])
    _write_csv(success_path, success_rows, ["model", "task_type", "runs", "success_rate", "average_validation_score"])
    report_path.write_text(_markdown(rows, frontier, success_rows, context_rows, bayes), encoding="utf-8")

    return {
        "report": str(report_path),
        "pareto_frontier": str(pareto_path),
        "context_efficiency": str(context_path),
        "model_success_rates": str(success_path),
    }


def _frontier(rows: list[dict[str, Any]]) -> list[ModelObjective]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("success") is None:
            continue
        grouped[(str(row.get("selected_model") or ""), str(row.get("task_type") or ""))].append(row)
    points: list[ModelObjective] = []
    for (model, task_type), items in grouped.items():
        if not model:
            continue
        quality = sum(float(row.get("validation_score") or 0.0) for row in items) / len(items)
        cost = sum(float(row.get("cost_estimate") or 0.0) for row in items) / len(items)
        latency = sum(float(row.get("latency_ms") or 0.0) for row in items) / len(items)
        points.append(ModelObjective(model=model, task_type=task_type, quality=quality, cost=cost, latency=latency))
    return pareto_frontier(points)


def _success_rates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("success") is not None:
            grouped[(str(row.get("selected_model") or ""), str(row.get("task_type") or ""))].append(row)
    output: list[dict[str, Any]] = []
    for (model, task_type), items in sorted(grouped.items()):
        if not model:
            continue
        output.append(
            {
                "model": model,
                "task_type": task_type,
                "runs": len(items),
                "success_rate": round(sum(1 for row in items if row.get("success") is True) / len(items), 4),
                "average_validation_score": round(sum(float(row.get("validation_score") or 0.0) for row in items) / len(items), 4),
            }
        )
    return output


def _context_efficiency(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("success") is None:
            continue
        bucket = int(float(row.get("context_token_count") or 0.0) // 1000) * 1000
        buckets[bucket].append(row)
    output: list[dict[str, Any]] = []
    for bucket, items in sorted(buckets.items()):
        output.append(
            {
                "context_token_count": bucket,
                "runs": len(items),
                "success_rate": round(sum(1 for row in items if row.get("success") is True) / len(items), 4),
                "average_validation_score": round(sum(float(row.get("validation_score") or 0.0) for row in items) / len(items), 4),
            }
        )
    return output


def _bayesian(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    router = BayesianSuccessRouter()
    for row in rows:
        if row.get("success") is None:
            continue
        context_level = _context_level(int(row.get("context_token_count") or 0))
        router.record(
            str(row.get("selected_model") or ""),
            str(row.get("task_type") or ""),
            context_level,
            success=bool(row.get("success")),
        )
    return router.to_rows()


def _context_level(tokens: int) -> str:
    if tokens <= 0:
        return "0%"
    if tokens < 2000:
        return "25%"
    if tokens < 6000:
        return "50%"
    if tokens < 12000:
        return "75%"
    return "100%"


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _markdown(
    rows: list[dict[str, Any]],
    frontier: list[ModelObjective],
    success_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    bayes: list[dict[str, Any]],
) -> str:
    summary = summarize_runs(rows)
    return "\n".join(
        [
            "# Agent-Hub Research Report",
            "",
            f"Runs: {summary.total_runs}",
            f"Outcomes: {summary.outcomes}",
            f"Success rate: {summary.success_rate:.2%}",
            "",
            "## 1. Best Models By Task Type",
            *_table(success_rows[:20], ["model", "task_type", "runs", "success_rate", "average_validation_score"]),
            "",
            "## 2. Pareto Frontier",
            *_table([asdict(item) for item in frontier[:20]], ["model", "task_type", "quality", "cost", "latency"]),
            "",
            "## 3. Token Efficiency Curve",
            *_table(context_rows, ["context_token_count", "runs", "success_rate", "average_validation_score"]),
            "",
            "## 4. Context vs Success Graph",
            "See `context_efficiency.csv` for the context bucket curve.",
            "",
            "## 5. Bayesian Success Estimates",
            *_table(bayes[:20], ["model", "task_type", "context_level", "expected_success"]),
            "",
            "## 6. Routing Policy Comparison",
            "Compare reports generated before and after policy changes using the CSV artifacts.",
            "",
        ]
    )


def _table(rows: list[dict[str, Any]], fields: list[str]) -> list[str]:
    if not rows:
        return ["No data yet."]
    lines = ["| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(field, "")) for field in fields) + " |")
    return lines


__all__ = ["generate_research_report"]
