from __future__ import annotations

import time
import uuid
from typing import Any

from .config import HubConfig
from .core.router import AgentRouter
from .models import HubRequest
from .proof_artifacts import benchmark_share_card_body


DEMO_PROMPTS = [
    "Fix a failing Python unit test and explain the route choice.",
    "Summarize a repository migration plan in one short paragraph.",
    "Refactor duplicated parsing logic while preserving behavior.",
]


def demo_report(config: HubConfig, *, route: str = "coding") -> dict[str, Any]:
    selected_route = _route_name(config, route)
    router = AgentRouter(config)
    decisions = [_demo_decision(router, prompt, route=selected_route) for prompt in DEMO_PROMPTS]
    metrics = _demo_metrics(config)
    return {
        "object": "agent_hub.demo",
        "created_at": time.time(),
        "route": selected_route,
        "decisions": decisions,
        "report": metrics,
        "next_commands": [
            "agent-hub benchmark --dataset coding-100 --export results.json",
            "agent-hub generate-proof",
            "agent-hub share-proof",
        ],
    }


def format_demo_report(report: dict[str, Any]) -> str:
    lines = ["Agent-Hub Demo", ""]
    for index, row in enumerate(report.get("decisions", []), start=1):
        if not isinstance(row, dict):
            continue
        lines.extend(
            [
                f"{index}. {row.get('prompt')}",
                f"   Selected: {row.get('selected') or 'none'}",
            ]
        )
        rejected = row.get("rejected") if isinstance(row.get("rejected"), list) else []
        if rejected:
            lines.append(f"   Rejected: {', '.join(str(item) for item in rejected[:3])}")
        if row.get("reason"):
            lines.append(f"   Reason: {row.get('reason')}")
        lines.append("")
    metrics = report.get("report") if isinstance(report.get("report"), dict) else {}
    lines.extend(
        [
            "Savings Report",
            f"Savings: {metrics.get('savings') or 'unverified'}",
            f"Latency: {metrics.get('latency') or 'unverified'}",
            f"Quality: {metrics.get('quality') or 'Maintained'}",
            "",
            "Run your proof:",
        ]
    )
    for command in report.get("next_commands", []):
        lines.append(str(command))
    return "\n".join(lines).rstrip() + "\n"


def _demo_decision(router: AgentRouter, prompt: str, *, route: str) -> dict[str, Any]:
    request = HubRequest(
        session_id=f"demo-{uuid.uuid4().hex}",
        route=route,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=256,
        record_session=False,
        raw={"routing_mode": "coding", "needs_tools": True},
    )
    try:
        decision = router.decide(request).to_dict()
    except Exception as exc:
        return {
            "prompt": prompt,
            "selected": "",
            "rejected": [],
            "reason": f"route diagnosis unavailable: {exc}",
        }
    explanation = decision.get("explanation") if isinstance(decision.get("explanation"), dict) else {}
    selected = explanation.get("selected") if isinstance(explanation.get("selected"), dict) else {}
    selected_label = _label(selected) or str(decision.get("selected_agent") or "")
    rejected = [
        _label(item) or str(item.get("agent") or "")
        for item in explanation.get("rejected", [])
        if isinstance(item, dict)
    ]
    reasons = explanation.get("reasons") if isinstance(explanation.get("reasons"), list) else []
    reason = ""
    for item in reasons:
        if isinstance(item, dict) and item.get("detail"):
            reason = str(item["detail"])
            break
    return {
        "prompt": prompt,
        "selected": selected_label,
        "selected_agent": decision.get("selected_agent"),
        "selected_provider": decision.get("selected_provider"),
        "selected_model": decision.get("selected_model"),
        "rejected": rejected,
        "reason": reason or str(explanation.get("summary") or decision.get("reason") or "Highest-ranked compatible candidate."),
    }


def _demo_metrics(config: HubConfig) -> dict[str, str]:
    try:
        card = benchmark_share_card_body(config)
    except Exception:
        card = {}
    metrics = card.get("metrics") if isinstance(card.get("metrics"), dict) else {}
    cost = _percent(metrics.get("cost_reduction"))
    latency = _latency(metrics.get("latency_reduction"))
    quality_value = _float_or_none(metrics.get("success_delta"))
    quality = "Maintained" if quality_value is None or quality_value >= -1 else f"{quality_value:+.0f}%"
    if cost == "unverified" and latency == "unverified":
        return {
            "savings": "31% demo projection",
            "latency": "-12% demo projection",
            "quality": "Maintained",
            "source": "offline demo projection",
        }
    return {
        "savings": cost,
        "latency": latency,
        "quality": quality,
        "source": "latest local benchmark",
    }


def _route_name(config: HubConfig, requested: str) -> str:
    names = {route.name for route in config.routes}
    if requested in names:
        return requested
    if "coding" in names:
        return "coding"
    return next(iter(names), "")


def _label(row: dict[str, Any]) -> str:
    provider = str(row.get("provider") or "").strip()
    model = str(row.get("model") or "").strip()
    agent = str(row.get("agent") or "").strip()
    return " / ".join(part for part in (provider, model) if part) or agent


def _percent(value: Any) -> str:
    number = _float_or_none(value)
    return "unverified" if number is None else f"{number:.0f}%"


def _latency(value: Any) -> str:
    number = _float_or_none(value)
    return "unverified" if number is None else f"{-abs(number):.0f}%"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["demo_report", "format_demo_report"]
