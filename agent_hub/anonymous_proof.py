from __future__ import annotations

import json
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

from .config import HubConfig
from .evaluation.datasets import load_benchmark_report, state_path
from .observability import STREAM_FILES
from .version import backend_version


DEFAULT_SHARE_TARGETS = ("github_discussion", "reddit", "x")


def generate_anonymous_proof(config: HubConfig, *, report_path: str | Path | None = None) -> dict[str, Any]:
    routing_events = _routing_events(config)
    report, path = load_benchmark_report(config, report_path)
    comparison = report.get("comparison") if isinstance(report.get("comparison"), dict) else {}
    providers = {
        str(event.get("provider") or event.get("agent") or event.get("model") or "").strip()
        for event in routing_events
        if str(event.get("provider") or event.get("agent") or event.get("model") or "").strip()
    }
    proof = {
        "object": "agent_hub.anonymous_proof",
        "generated_at": time.time(),
        "version": backend_version(),
        "routes": len(routing_events),
        "estimated_savings": _float_or_zero(comparison.get("cost_reduction")),
        "providers_used": len(providers),
        "benchmark": {
            "report_path": str(path) if path else "",
            "dataset": _dataset_name(report),
            "tasks": int(report.get("task_count") or 0),
            "cost_reduction": _float_or_none(comparison.get("cost_reduction")),
            "latency_reduction": _float_or_none(comparison.get("latency_reduction")),
            "quality_change": _float_or_none(comparison.get("success_delta")),
            "fingerprint": _dataset_fingerprint(report),
        },
    }
    proof["share_text"] = proof_share_text(proof)
    return proof


def share_proof(
    config: HubConfig,
    *,
    report_path: str | Path | None = None,
    targets: list[str] | tuple[str, ...] | None = None,
    open_links: bool = True,
) -> dict[str, Any]:
    proof = generate_anonymous_proof(config, report_path=report_path)
    selected_targets = _normalize_targets(targets)
    urls = proof_share_urls(proof)
    opened: list[str] = []
    if open_links:
        for target in selected_targets:
            url = urls.get(target)
            if not url:
                continue
            if webbrowser.open(url):
                opened.append(target)
    return {
        "object": "agent_hub.share_proof",
        "proof": proof,
        "targets": selected_targets,
        "opened": opened,
        "urls": {target: urls[target] for target in selected_targets if target in urls},
    }


def proof_share_text(proof: dict[str, Any]) -> str:
    benchmark = proof.get("benchmark") if isinstance(proof.get("benchmark"), dict) else {}
    cost = _percent(benchmark.get("cost_reduction"))
    latency = _percent(benchmark.get("latency_reduction"))
    quality = _signed_points(benchmark.get("quality_change"))
    tasks = int(benchmark.get("tasks") or 0)
    dataset = benchmark.get("dataset") or "local benchmark"
    return "\n".join(
        [
            "# Agent-Hub Benchmark",
            "",
            f"Dataset: {dataset}",
            f"Tasks: {tasks}",
            f"Cost Reduction: {cost}",
            f"Latency Reduction: {latency}",
            f"Quality Change: {quality}",
            "",
            f"Routes Observed: {int(proof.get('routes') or 0):,}",
            f"Providers Used: {int(proof.get('providers_used') or 0)}",
            "",
            "Verified Replay:",
            "agent-hub replay-route <request-id>",
            "",
            "Reproduce:",
            f"agent-hub benchmark --dataset {dataset} --export results.json",
        ]
    )


def proof_share_urls(proof: dict[str, Any]) -> dict[str, str]:
    text = proof_share_text(proof)
    title = "Agent-Hub Benchmark Proof"
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return {
        "github_discussion": (
            "https://github.com/350285449/Agent-Hub/discussions/new?"
            + urllib.parse.urlencode({"title": title, "body": text})
        ),
        "reddit": (
            "https://www.reddit.com/submit?"
            + urllib.parse.urlencode({"title": title, "text": text})
        ),
        "x": "https://twitter.com/intent/tweet?" + urllib.parse.urlencode({"text": compact[:280]}),
    }


def format_anonymous_proof(proof: dict[str, Any]) -> str:
    return json.dumps(
        {
            "version": proof.get("version"),
            "routes": proof.get("routes"),
            "estimated_savings": proof.get("estimated_savings"),
            "providers_used": proof.get("providers_used"),
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"


def format_share_proof(report: dict[str, Any]) -> str:
    proof = report.get("proof") if isinstance(report.get("proof"), dict) else {}
    lines = [proof_share_text(proof), "", "Share Links:"]
    urls = report.get("urls") if isinstance(report.get("urls"), dict) else {}
    for target, url in urls.items():
        lines.append(f"- {target}: {url}")
    return "\n".join(lines).rstrip() + "\n"


def _routing_events(config: HubConfig) -> list[dict[str, Any]]:
    filename = STREAM_FILES.get("routing", "routing.jsonl")
    path = state_path(config, filename)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _normalize_targets(targets: list[str] | tuple[str, ...] | None) -> list[str]:
    raw = [str(item or "").strip() for item in (targets or DEFAULT_SHARE_TARGETS)]
    if not raw or "all" in raw:
        return list(DEFAULT_SHARE_TARGETS)
    aliases = {"github": "github_discussion", "twitter": "x"}
    result = []
    for item in raw:
        target = aliases.get(item, item)
        if target in DEFAULT_SHARE_TARGETS and target not in result:
            result.append(target)
    return result or list(DEFAULT_SHARE_TARGETS)


def _dataset_name(report: dict[str, Any]) -> str:
    dataset = report.get("dataset") if isinstance(report.get("dataset"), dict) else {}
    return str(dataset.get("name") or report.get("dataset_name") or "local benchmark")


def _dataset_fingerprint(report: dict[str, Any]) -> str:
    dataset = report.get("dataset") if isinstance(report.get("dataset"), dict) else {}
    return str(dataset.get("fingerprint") or report.get("dataset_fingerprint") or "")


def _percent(value: Any) -> str:
    number = _float_or_none(value)
    return "unverified" if number is None else f"{number:.0f}%"


def _signed_points(value: Any) -> str:
    number = _float_or_none(value)
    return "unverified" if number is None else f"{number:+.0f}%"


def _float_or_zero(value: Any) -> float:
    number = _float_or_none(value)
    return round(number, 2) if number is not None else 0.0


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "format_anonymous_proof",
    "format_share_proof",
    "generate_anonymous_proof",
    "proof_share_text",
    "proof_share_urls",
    "share_proof",
]
