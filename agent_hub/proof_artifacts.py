from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from .config import HubConfig
from .observability import STREAM_FILES


SECONDS_PER_MONTH = 30 * 24 * 60 * 60


def replay_route_body(config: HubConfig, request_id: str) -> dict[str, Any]:
    aliases = _request_id_aliases(request_id)
    events = [
        event
        for event in _all_events(config.state_dir, "routing")
        if str(event.get("request_id") or "") in aliases
    ]
    event = _latest_decision(events)
    decision = _dict(event.get("routing_decision"))
    explanation = _dict(decision.get("explanation"))
    selected_agent = str(decision.get("selected_agent") or event.get("agent") or "")
    candidates = [
        row
        for row in decision.get("candidate_scores", [])
        if isinstance(row, dict)
    ]
    selected = _selected_candidate(candidates, selected_agent, decision, event)
    alternatives = [
        _alternative_row(row, selected=selected, explanation=explanation)
        for row in candidates
        if row.get("agent") != selected.get("agent")
    ][:8]
    return {
        "object": "agent_hub.route_replay",
        "request_id": request_id,
        "request_id_aliases": sorted(aliases),
        "found": bool(event),
        "request": _request_summary(event, decision),
        "selected": _selected_row(selected, decision, event),
        "alternatives": alternatives,
        "reason": _replay_reason(decision, explanation, selected),
        "event": event,
        "routing_decision": decision,
    }


def format_route_replay(report: dict[str, Any]) -> str:
    if not report.get("found"):
        return f"No route decision found for request id {report.get('request_id')!s}.\n"
    request = _dict(report.get("request"))
    selected = _dict(report.get("selected"))
    lines = [
        "Request:",
        str(request.get("text") or request.get("task_type") or "Unknown request"),
        "",
        "Selected:",
        _display_label(selected),
        "",
        "Alternatives:",
        "",
    ]
    alternatives = report.get("alternatives") if isinstance(report.get("alternatives"), list) else []
    if alternatives:
        for row in alternatives:
            if not isinstance(row, dict):
                continue
            lines.extend(
                [
                    _display_label(row),
                    f"Expected Quality: {row.get('expected_quality') or 'unknown'}",
                    f"Cost: {row.get('cost') or 'unpriced'}",
                    "",
                ]
            )
    else:
        lines.extend(["No scored alternatives were recorded.", ""])
    lines.extend(["Reason:", str(report.get("reason") or "Highest-ranked compatible candidate.")])
    return "\n".join(lines).rstrip() + "\n"


def benchmark_share_card_body(config: HubConfig, report_path: str | Path | None = None) -> dict[str, Any]:
    report, path = _load_benchmark_report(config, report_path)
    comparison = _comparison(report)
    baseline = _dict(report.get("baseline"))
    task_count = int(report.get("task_count") or len(report.get("results", [])) or 0)
    baseline_label = _baseline_label(baseline)
    metrics = {
        "token_reduction": comparison.get("token_reduction"),
        "cost_reduction": comparison.get("cost_reduction"),
        "latency_reduction": comparison.get("latency_reduction"),
        "success_delta": comparison.get("success_delta"),
        "prompt_loops_avoided": comparison.get("prompt_loops_avoided"),
    }
    variants = _share_variants(baseline_label=baseline_label, task_count=task_count, metrics=metrics)
    return {
        "object": "agent_hub.benchmark_share_card",
        "report_path": str(path) if path else "",
        "baseline": baseline_label,
        "tasks": task_count,
        "metrics": metrics,
        "variants": variants,
    }


def format_benchmark_card(report: dict[str, Any], *, variant: str = "markdown") -> str:
    variants = _dict(report.get("variants"))
    text = variants.get(variant) or variants.get("markdown") or ""
    return str(text).rstrip() + "\n"


def case_study_body(config: HubConfig) -> dict[str, Any]:
    report, path = _load_benchmark_report(config, None)
    comparison = _comparison(report)
    routing_events = _all_events(config.state_dir, "routing")
    repo = _repo_size(config)
    return {
        "object": "agent_hub.case_study",
        "generated_at": time.time(),
        "repository": repo,
        "routes": len(routing_events),
        "benchmark_report": str(path) if path else "",
        "benchmark": {
            "baseline": _baseline_label(_dict(report.get("baseline"))),
            "tasks": int(report.get("task_count") or len(report.get("results", [])) or 0),
            "cost_reduction": comparison.get("cost_reduction"),
            "latency_reduction": comparison.get("latency_reduction"),
            "success_delta": comparison.get("success_delta"),
        },
        "routing_evolution": benchmark_evolution_body(config, months=3),
    }


def format_case_study_markdown(report: dict[str, Any]) -> str:
    repository = _dict(report.get("repository"))
    benchmark = _dict(report.get("benchmark"))
    evolution = _dict(report.get("routing_evolution"))
    lines = [
        "# Agent-Hub Case Study",
        "",
        f"Repository Size: {_format_loc(repository.get('loc'))}",
        f"Files Scanned: {int(repository.get('files') or 0)}",
        f"Routes: {int(report.get('routes') or 0):,}",
        "",
        "## Benchmark",
        "",
        f"Baseline: {benchmark.get('baseline') or 'User default'}",
        f"Tasks: {int(benchmark.get('tasks') or 0)}",
        f"Cost: {_percent(benchmark.get('cost_reduction'))}",
        f"Latency: {_percent(benchmark.get('latency_reduction'))}",
        f"Success: {_signed_points(benchmark.get('success_delta'))}",
        "",
        "## Routing Evolution",
        "",
    ]
    for row in evolution.get("months", []):
        if not isinstance(row, dict):
            continue
        lines.append(str(row.get("month") or "Month"))
        distribution = row.get("distribution") if isinstance(row.get("distribution"), dict) else {}
        if not distribution:
            lines.append("- No routes recorded")
        else:
            for name, item in sorted(distribution.items(), key=lambda item: -_float(_dict(item[1]).get("percentage"))):
                lines.append(f"- {name}: {_dict(item).get('percentage')}%")
        lines.append("")
    lines.extend(
        [
            "## Notes",
            "",
            "Agent-Hub ships the benchmark corpus and writes proof reports locally, so these numbers can be reproduced from the repository and provider configuration.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def benchmark_evolution_body(config: HubConfig, *, months: int = 3) -> dict[str, Any]:
    window = max(1, min(12, int(months or 3)))
    now = time.time()
    bucket_counts: dict[int, dict[str, int]] = {index: {} for index in range(window)}
    totals: dict[int, int] = {index: 0 for index in range(window)}
    for event in _all_events(config.state_dir, "routing"):
        timestamp = _float(event.get("time") or event.get("timestamp")) or now
        age_months = int(max(0.0, now - timestamp) // SECONDS_PER_MONTH)
        if age_months >= window:
            continue
        bucket = window - age_months - 1
        decision = _dict(event.get("routing_decision"))
        label = str(event.get("agent") or decision.get("selected_agent") or event.get("model") or "unknown")
        bucket_counts[bucket][label] = bucket_counts[bucket].get(label, 0) + 1
        totals[bucket] += 1
    month_rows = []
    for index in range(window):
        total = totals[index]
        distribution = {
            name: {
                "count": count,
                "percentage": round((count / max(1, total)) * 100, 2),
            }
            for name, count in sorted(bucket_counts[index].items())
        }
        month_rows.append(
            {
                "month": f"Month {index + 1}",
                "route_count": total,
                "distribution": distribution,
            }
        )
    return {
        "object": "agent_hub.benchmark_evolution",
        "window_months": window,
        "total_routes": sum(totals.values()),
        "months": month_rows,
        "routing_improvement": _routing_improvement(month_rows),
    }


def format_benchmark_evolution(report: dict[str, Any]) -> str:
    lines = ["Routing Improvement", ""]
    for row in report.get("routing_improvement", []):
        if not isinstance(row, dict):
            continue
        lines.append(f"{row.get('agent')}: {row.get('from')}% -> {row.get('to')}%")
    if len(lines) == 2:
        lines.append("No routing changes recorded yet.")
    lines.append("")
    for month in report.get("months", []):
        if not isinstance(month, dict):
            continue
        lines.append(str(month.get("month") or "Month"))
        distribution = month.get("distribution") if isinstance(month.get("distribution"), dict) else {}
        if not distribution:
            lines.append("No routes")
        else:
            for name, item in sorted(distribution.items(), key=lambda item: -_float(_dict(item[1]).get("percentage"))):
                lines.append(f"{name}: {_dict(item).get('percentage')}%")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _all_events(state_dir: str | Path, stream: str) -> list[dict[str, Any]]:
    filename = STREAM_FILES.get(stream, f"{stream}.jsonl")
    path = Path(state_dir) / filename
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _request_id_aliases(value: str) -> set[str]:
    text = str(value or "").strip()
    aliases = {text} if text else set()
    for prefix in ("chatcmpl-", "resp_", "msg_"):
        if text.startswith(prefix):
            aliases.add(text[len(prefix) :])
    return aliases


def _latest_decision(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if isinstance(event.get("routing_decision"), dict):
            return dict(event)
    return dict(events[-1]) if events else {}


def _selected_candidate(
    candidates: list[dict[str, Any]],
    selected_agent: str,
    decision: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    for row in candidates:
        if row.get("agent") == selected_agent:
            return dict(row)
    if candidates:
        return dict(candidates[0])
    return {
        "agent": selected_agent or decision.get("selected_agent") or event.get("agent"),
        "provider": decision.get("selected_provider") or event.get("provider"),
        "model": decision.get("selected_model") or event.get("model"),
    }


def _selected_row(selected: dict[str, Any], decision: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent": selected.get("agent") or decision.get("selected_agent") or event.get("agent"),
        "provider": selected.get("provider") or decision.get("selected_provider") or event.get("provider"),
        "model": selected.get("model") or decision.get("selected_model") or event.get("model"),
        "score": _candidate_score(selected),
        "estimated_cost_usd": selected.get("estimated_cost_usd"),
    }


def _alternative_row(row: dict[str, Any], *, selected: dict[str, Any], explanation: dict[str, Any]) -> dict[str, Any]:
    selected_score = _candidate_score(selected)
    score = _candidate_score(row)
    selected_cost = _float_or_none(selected.get("estimated_cost_usd"))
    cost = _float_or_none(row.get("estimated_cost_usd"))
    return {
        "agent": row.get("agent"),
        "provider": row.get("provider"),
        "model": row.get("model"),
        "score": score,
        "estimated_cost_usd": row.get("estimated_cost_usd"),
        "expected_quality": _quality_delta(score, selected_score),
        "cost": _cost_delta(cost, selected_cost),
        "reason": _rejected_reason(row, explanation),
    }


def _replay_reason(decision: dict[str, Any], explanation: dict[str, Any], selected: dict[str, Any]) -> str:
    summary = str(explanation.get("summary") or "").strip()
    if summary:
        return summary
    reason = str(decision.get("reason") or "").strip()
    if reason:
        return reason
    label = _display_label(selected)
    return f"{label} provided the best cost/performance score."


def _request_summary(event: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    preview = str(event.get("request_preview") or "").strip()
    classification = _dict(decision.get("task_classification"))
    return {
        "text": preview or str(classification.get("summary") or decision.get("task_type") or "Request text was not logged."),
        "route": event.get("route"),
        "source": event.get("source"),
        "task_type": decision.get("task_type"),
    }


def _rejected_reason(row: dict[str, Any], explanation: dict[str, Any]) -> str:
    agent = str(row.get("agent") or "")
    rejected = explanation.get("rejected") if isinstance(explanation.get("rejected"), list) else []
    for item in rejected:
        if isinstance(item, dict) and str(item.get("agent") or "") == agent:
            return str(item.get("reason") or "Ranked behind selected model.")
    return str(row.get("why") or "Ranked behind selected model.")


def _candidate_score(row: dict[str, Any]) -> float | None:
    return _float_or_none(row.get("final_routing_score", row.get("routing_score", row.get("score"))))


def _quality_delta(score: float | None, selected_score: float | None) -> str:
    if score is None or selected_score is None:
        return "unknown"
    if selected_score == 0:
        return "+0%" if score == 0 else "+inf"
    return _signed_percent(((score - selected_score) / abs(selected_score)) * 100)


def _cost_delta(cost: float | None, selected_cost: float | None) -> str:
    if cost is None or selected_cost is None:
        return "unpriced"
    if selected_cost == 0:
        return "+0%" if cost == 0 else "+inf"
    return _signed_percent(((cost - selected_cost) / abs(selected_cost)) * 100)


def _signed_percent(value: float) -> str:
    if not math.isfinite(value):
        return "+inf"
    return f"{value:+.0f}%"


def _load_benchmark_report(config: HubConfig, report_path: str | Path | None) -> tuple[dict[str, Any], Path | None]:
    candidates: list[Path] = []
    if report_path:
        candidates.append(Path(report_path))
    reports_dir = _state_path(config, "benchmark_reports")
    if reports_dir.exists():
        candidates.extend(sorted(reports_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True))
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload, path
    return {}, None


def _comparison(report: dict[str, Any]) -> dict[str, Any]:
    comparison = report.get("comparison")
    if isinstance(comparison, dict):
        return comparison
    summary = _dict(report.get("summary"))
    nested = summary.get("comparison")
    return nested if isinstance(nested, dict) else {}


def _share_variants(*, baseline_label: str, task_count: int, metrics: dict[str, Any]) -> dict[str, str]:
    tokens = _negative_percent(metrics.get("token_reduction"), empty="unavailable")
    cost = _negative_percent(metrics.get("cost_reduction"), empty="unpriced")
    success = _signed_points(metrics.get("success_delta"))
    retries = _retry_metric(metrics.get("prompt_loops_avoided"))
    markdown = "\n".join(
        [
            "# My Agent-Hub Benchmark",
            "",
            f"Baseline: {baseline_label}",
            f"Tasks: {task_count}",
            "",
            f"Tokens Used: {tokens}",
            f"Task Success: {success}",
            f"Retries: {retries}",
            f"Cost: {cost}",
            "",
            "Agent-Hub ships the benchmark corpus so I can verify tokens, cost, retries, and success locally.",
        ]
    )
    reddit = "\n".join(
        [
            "I ran Agent-Hub's local benchmark corpus.",
            "",
            f"Baseline: {baseline_label}",
            f"Tasks: {task_count}",
            f"Tokens Used: {tokens}",
            f"Task Success: {success}",
            f"Retries: {retries}",
            f"Cost: {cost}",
            "",
            "The useful part: the benchmark corpus and reports are local/reproducible, not just vendor claims.",
        ]
    )
    x = (
        f"I ran Agent-Hub's local benchmark corpus vs {baseline_label}: "
        f"{tokens} tokens, {success} success, {retries} retries, {cost} cost across {task_count} tasks. "
        "Reproducible proof reports ship with the tool."
    )
    github = "\n".join(
        [
            "## Agent-Hub Benchmark Result",
            "",
            f"- Baseline: {baseline_label}",
            f"- Tasks: {task_count}",
            f"- Tokens Used: {tokens}",
            f"- Task Success: {success}",
            f"- Retries: {retries}",
            f"- Cost: {cost}",
            "",
            "The report was generated locally from the bundled benchmark corpus.",
        ]
    )
    return {
        "markdown": markdown,
        "reddit": reddit,
        "x": x[:280],
        "github_discussion": github,
    }


def _repo_size(config: HubConfig) -> dict[str, Any]:
    root = Path(config.workspace_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    excluded = {".git", ".agent-hub", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    extensions = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".cs", ".cpp", ".c", ".h", ".md", ".json", ".yaml", ".yml"}
    loc = 0
    files = 0
    try:
        iterator = root.rglob("*")
        for path in iterator:
            if any(part in excluded for part in path.parts):
                continue
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            try:
                stat = path.stat()
                if stat.st_size > 1_000_000:
                    continue
                loc += len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
                files += 1
            except OSError:
                continue
    except OSError:
        pass
    return {"root": str(root), "loc": loc, "files": files}


def _routing_improvement(month_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(month_rows) < 2:
        return []
    first = _dict(month_rows[0].get("distribution"))
    last = _dict(month_rows[-1].get("distribution"))
    names = sorted(set(first) | set(last))
    rows = []
    for name in names:
        start = _float(_dict(first.get(name)).get("percentage"))
        end = _float(_dict(last.get(name)).get("percentage"))
        if abs(end - start) < 0.01:
            continue
        rows.append(
            {
                "agent": name,
                "from": round(start, 2),
                "to": round(end, 2),
                "delta": round(end - start, 2),
                "direction": "up" if end > start else "down",
            }
        )
    return sorted(rows, key=lambda row: abs(float(row["delta"])), reverse=True)


def _state_path(config: HubConfig, name: str) -> Path:
    root = Path(config.state_dir)
    if not root.is_absolute():
        workspace = Path(config.workspace_dir)
        if not workspace.is_absolute():
            workspace = Path.cwd() / workspace
        root = workspace / root
    return root / name


def _baseline_label(row: dict[str, Any]) -> str:
    return str(row.get("model") or row.get("agent") or row.get("provider") or "User default")


def _display_label(row: dict[str, Any]) -> str:
    provider = str(row.get("provider") or "").strip()
    model = str(row.get("model") or "").strip()
    agent = str(row.get("agent") or "").strip()
    return " ".join(part for part in (provider, model) if part) or agent or "unknown"


def _format_loc(value: Any) -> str:
    loc = int(_float(value))
    if loc >= 1000:
        return f"{loc / 1000:.1f}k LOC"
    return f"{loc} LOC"


def _percent(value: Any) -> str:
    number = _float_or_none(value)
    return "unpriced" if number is None else f"{number:.0f}%"


def _negative_percent(value: Any, *, empty: str) -> str:
    number = _float_or_none(value)
    return empty if number is None else f"-{abs(number):.0f}%"


def _signed_points(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "unknown"
    return f"{number:+.0f} pp"


def _retry_metric(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "unknown"
    if number < 0:
        return f"{number:.0f}"
    return f"-{number:.0f}"


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


__all__ = [
    "benchmark_evolution_body",
    "benchmark_share_card_body",
    "case_study_body",
    "format_benchmark_card",
    "format_benchmark_evolution",
    "format_case_study_markdown",
    "format_route_replay",
    "replay_route_body",
]
