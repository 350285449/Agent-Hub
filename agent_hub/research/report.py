from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .bayesian_router import BayesianSuccessRouter
from .dataset import export_dataset_csv
from .file_stats import load_file_stats, most_useful_files, save_file_stats, update_file_stats
from .metrics import load_research_runs, summarize_runs, wilson_interval
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
    file_stats = _ensure_file_stats(state_dir, rows)

    pareto_path = directory / "pareto_frontier.csv"
    context_path = directory / "context_efficiency.csv"
    success_path = directory / "model_success_rates.csv"
    report_path = directory / "report.md"
    dataset_csv = export_dataset_csv(state_dir)

    _write_csv(pareto_path, [asdict(item) for item in frontier], ["model", "quality", "cost", "latency", "task_type"])
    _write_csv(context_path, context_rows, ["context_token_count", "runs", "success_rate", "average_validation_score"])
    _write_csv(
        success_path,
        success_rows,
        ["model", "task_type", "runs", "success_rate", "success_ci_low", "success_ci_high", "average_validation_score"],
    )
    report_path.write_text(
        _markdown(rows, frontier, success_rows, context_rows, bayes, file_stats),
        encoding="utf-8",
    )

    return {
        "report": str(report_path),
        "pareto_frontier": str(pareto_path),
        "context_efficiency": str(context_path),
        "dataset": str(dataset_csv),
        "file_stats": str(directory / "file_stats.json"),
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
                "success_ci_low": wilson_interval(sum(1 for row in items if row.get("success") is True), len(items))[0],
                "success_ci_high": wilson_interval(sum(1 for row in items if row.get("success") is True), len(items))[1],
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
    file_stats: dict[str, dict[str, Any]],
) -> str:
    summary = summarize_runs(rows)
    model_rows = _model_comparison(rows)
    useful_files = most_useful_files_from_stats(file_stats)
    return "\n".join(
        [
            "# Agent-Hub Research Report",
            "",
            f"Runs: {summary.total_runs}",
            f"Outcomes: {summary.outcomes}",
            f"Success rate: {summary.success_rate:.2%}",
            f"Average latency: {summary.average_latency_ms} ms",
            f"Average cost: {summary.total_cost_estimate / max(1, summary.outcomes):.8f}",
            "",
            "## Success Rates",
            *_table(success_rows[:20], ["model", "task_type", "runs", "success_rate", "success_ci_low", "success_ci_high"]),
            "",
            "## Model Comparison",
            *_table(model_rows[:20], ["model", "runs", "success_rate", "average_latency_ms", "average_cost"]),
            "",
            "## Context Statistics",
            *_context_stats(rows),
            "",
            "## Most Useful Files",
            *_table(useful_files[:20], ["path", "selections", "successful_inclusions", "failed_inclusions", "average_validation_score"]),
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
            *_context_chart(context_rows),
            "",
            "## 5. Bayesian Success Estimates",
            *_table(bayes[:20], ["model", "task_type", "context_level", "expected_success"]),
            "",
            "## 6. Routing Policy Comparison",
            "Compare reports generated before and after policy changes using the CSV artifacts.",
            "",
        ]
    )


def _ensure_file_stats(state_dir: str | Path, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats = load_file_stats(state_dir)
    if stats:
        return stats
    for row in rows:
        if row.get("success") is not None:
            stats = update_file_stats(state_dir, row)
    if not stats:
        save_file_stats(state_dir, {})
    return load_file_stats(state_dir)


def most_useful_files_from_stats(stats: dict[str, dict[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    rows = [{"path": path, **data} for path, data in stats.items()]
    rows.sort(
        key=lambda row: (
            -float(row.get("average_validation_score") or 0.0),
            -int(row.get("successful_inclusions") or 0),
            -int(row.get("selections") or 0),
            row.get("path", ""),
        )
    )
    return rows[:limit]


def _model_comparison(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("success") is not None:
            grouped[str(row.get("selected_model") or "")].append(row)
    output: list[dict[str, Any]] = []
    for model, items in sorted(grouped.items()):
        if not model:
            continue
        output.append(
            {
                "model": model,
                "runs": len(items),
                "success_rate": round(sum(1 for item in items if item.get("success") is True) / len(items), 4),
                "average_latency_ms": round(sum(float(item.get("latency_ms") or 0.0) for item in items) / len(items), 2),
                "average_cost": round(sum(float(item.get("cost_estimate") or 0.0) for item in items) / len(items), 8),
            }
        )
    output.sort(key=lambda row: (-float(row["success_rate"]), float(row["average_cost"]), float(row["average_latency_ms"])))
    return output


def _context_stats(rows: list[dict[str, Any]]) -> list[str]:
    outcomes = [row for row in rows if row.get("success") is not None]
    if not outcomes:
        return ["No context data yet."]
    context_tokens = [int(row.get("context_token_count") or 0) for row in outcomes]
    file_counts = [
        len(row.get("context_files"))
        if isinstance(row.get("context_files"), list)
        else 0
        for row in outcomes
    ]
    return [
        f"- Average context tokens: {sum(context_tokens) / max(1, len(context_tokens)):.1f}",
        f"- Max context tokens: {max(context_tokens)}",
        f"- Average file count: {sum(file_counts) / max(1, len(file_counts)):.1f}",
        f"- Max file count: {max(file_counts)}",
    ]


def _table(rows: list[dict[str, Any]], fields: list[str]) -> list[str]:
    if not rows:
        return ["No data yet."]
    lines = ["| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(field, "")) for field in fields) + " |")
    return lines


def _context_chart(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No context efficiency data yet."]
    lines = ["```text"]
    for row in rows:
        bucket = str(row.get("context_token_count", "0")).rjust(6)
        rate = float(row.get("success_rate") or 0.0)
        bar = "#" * int(round(rate * 20))
        lines.append(f"{bucket} tokens | {bar:<20} | {rate:.0%}")
    lines.append("```")
    lines.append("See `context_efficiency.csv` for machine-readable values.")
    return lines


__all__ = ["generate_research_report"]
