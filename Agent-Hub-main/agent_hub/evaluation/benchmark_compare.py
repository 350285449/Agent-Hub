from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..config import HubConfig
from .datasets import load_benchmark_report, verify_benchmark_report
from .proof_benchmark import BenchmarkProofRunner


def benchmark_compare_body(
    config: HubConfig,
    *,
    route: str = "cloud-agent",
    baseline: str = "",
    limit: int = 0,
    dataset: str = "",
    corpus: str = "",
    output_dir: str = "",
    report_path: str = "",
) -> dict[str, Any]:
    """Build a shareable Agent-Hub-vs-baseline comparison from a run or report."""

    if report_path:
        report, path = load_benchmark_report(config, report_path)
        if not report:
            raise ValueError(f"Benchmark report was not found: {report_path}")
        source = "report"
    else:
        report = BenchmarkProofRunner(config).run(
            route=route,
            baseline=baseline,
            limit=limit,
            dataset=dataset,
            corpus_dir=corpus or None,
            output_dir=output_dir or None,
        )
        path = _report_json_path(report)
        source = "run"

    dataset_name = dataset or _dataset_name(report)
    verification = verify_benchmark_report(
        config,
        report_path=path,
        dataset=dataset_name,
        corpus_dir=corpus or None,
    )
    comparison = report.get("comparison") if isinstance(report.get("comparison"), dict) else {}
    baseline_info = report.get("baseline") if isinstance(report.get("baseline"), dict) else {}
    dataset_info = report.get("dataset") if isinstance(report.get("dataset"), dict) else {}
    report_verification = report.get("verification") if isinstance(report.get("verification"), dict) else {}
    task_count = int(report.get("task_count") or len(report.get("results", [])) or 0)
    verified = bool(verification.get("ok"))
    verified_tasks = _verified_task_count(verification) if verified else 0
    commands = {
        "rerun": report_verification.get("rerun_command") or verification.get("rerun_command") or "",
        "verify": _verify_command(verification),
    }

    return {
        "object": "agent_hub.benchmark_comparison",
        "source": source,
        "route": report.get("route") or route,
        "baseline": baseline_info,
        "baseline_label": _baseline_label(baseline_info, fallback=baseline),
        "task_count": task_count,
        "verified": verified,
        "verified_tasks": verified_tasks,
        "dataset": dataset_info,
        "dataset_name": dataset_name or dataset_info.get("name") or report.get("dataset_name") or "",
        "dataset_fingerprint": dataset_info.get("fingerprint") or report.get("dataset_fingerprint") or "",
        "report_path": str(path) if path else "",
        "comparison": comparison,
        "summary": _comparison_summary(comparison),
        "verification": verification,
        "commands": commands,
    }


def format_benchmark_comparison(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    verification = report.get("verification") if isinstance(report.get("verification"), dict) else {}
    commands = report.get("commands") if isinstance(report.get("commands"), dict) else {}
    dataset = report.get("dataset") if isinstance(report.get("dataset"), dict) else {}
    dataset_name = report.get("dataset_name") or dataset.get("name") or "local benchmark"
    baseline = report.get("baseline_label") or "Baseline"
    lines = [
        f"Agent-Hub vs {baseline}",
        "",
        f"Dataset: {dataset_name}",
    ]
    if report.get("verified"):
        lines.append(f"Verified Tasks: {int(report.get('verified_tasks') or 0)}")
    else:
        lines.append(f"Tasks: {int(report.get('task_count') or 0)}")
        lines.append("Verification: failed")
    fingerprint = report.get("dataset_fingerprint")
    if fingerprint:
        lines.append(f"Fingerprint: {fingerprint}")
    lines.extend(
        [
            "",
            f"Tokens: {_signed_percent(summary.get('tokens_pct'), empty='unavailable')}",
            f"Cost: {_signed_percent(summary.get('cost_pct'), empty='unpriced')}",
            f"Latency: {_signed_percent(summary.get('latency_pct'), empty='unavailable')}",
            f"Quality: {_signed_percent(summary.get('quality_pct'), empty='unavailable')}",
        ]
    )
    report_path = report.get("report_path")
    if report_path:
        lines.extend(["", f"Report: {report_path}"])
    rerun_command = commands.get("rerun") or verification.get("rerun_command")
    if rerun_command:
        lines.append(f"Rerun: {rerun_command}")
    verify_command = commands.get("verify") or _verify_command(verification)
    if verify_command:
        lines.append(f"Verify: {verify_command}")
    return "\n".join(lines) + "\n"


def _comparison_summary(comparison: dict[str, Any]) -> dict[str, Any]:
    cost_reduction = _float_or_none(comparison.get("cost_reduction"))
    latency_reduction = _float_or_none(comparison.get("latency_reduction"))
    token_reduction = _float_or_none(comparison.get("token_reduction"))
    quality_delta = _float_or_none(comparison.get("success_delta"))
    return {
        "tokens_pct": -token_reduction if token_reduction is not None else None,
        "cost_pct": -cost_reduction if cost_reduction is not None else None,
        "latency_pct": -latency_reduction if latency_reduction is not None else None,
        "quality_pct": quality_delta,
        "average_score_delta": _float_or_none(comparison.get("average_score_delta")),
        "failure_delta": comparison.get("failure_delta"),
        "total_cost_delta_usd": comparison.get("total_cost_delta_usd"),
        "average_latency_delta_ms": comparison.get("average_latency_delta_ms"),
    }


def _report_json_path(report: dict[str, Any]) -> Path | None:
    paths = report.get("report_paths") if isinstance(report.get("report_paths"), dict) else {}
    json_path = paths.get("json")
    return Path(json_path) if json_path else None


def _dataset_name(report: dict[str, Any]) -> str:
    dataset = report.get("dataset") if isinstance(report.get("dataset"), dict) else {}
    return str(dataset.get("name") or report.get("dataset_name") or "")


def _verified_task_count(verification: dict[str, Any]) -> int:
    dataset = verification.get("dataset") if isinstance(verification.get("dataset"), dict) else {}
    try:
        return int(dataset.get("task_count") or 0)
    except (TypeError, ValueError):
        return 0


def _baseline_label(baseline: dict[str, Any], *, fallback: str = "") -> str:
    raw = str(baseline.get("model") or baseline.get("agent") or fallback or "Baseline")
    return _pretty_name(raw)


def _pretty_name(value: str) -> str:
    words = [word for word in re.split(r"[-_\s:/]+", value.strip()) if word]
    replacements = {
        "ai": "AI",
        "api": "API",
        "codex": "Codex",
        "claude": "Claude",
        "deepseek": "DeepSeek",
        "gpt": "GPT",
        "gemini": "Gemini",
        "hub": "Hub",
        "local": "Local",
        "openai": "OpenAI",
        "qwen": "Qwen",
        "sonnet": "Sonnet",
    }
    pretty = [replacements.get(word.lower(), word[:1].upper() + word[1:]) for word in words]
    return " ".join(pretty) or "Baseline"


def _signed_percent(value: Any, *, empty: str) -> str:
    number = _float_or_none(value)
    if number is None:
        return empty
    if abs(number) < 0.005:
        number = 0.0
    formatted = f"{number:+.2f}".rstrip("0").rstrip(".")
    return f"{formatted}%"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _verify_command(verification: dict[str, Any]) -> str:
    report_path = verification.get("report_path")
    dataset = verification.get("dataset") if isinstance(verification.get("dataset"), dict) else {}
    dataset_name = dataset.get("name")
    if not report_path or not dataset_name:
        return ""
    return f"agent-hub benchmark verify {report_path} --dataset {dataset_name}"


__all__ = [
    "benchmark_compare_body",
    "format_benchmark_comparison",
]
