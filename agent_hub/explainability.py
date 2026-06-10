from __future__ import annotations

from typing import Any

from .config import HubConfig
from .core.router import AgentRouter
from .models import HubRequest
from .proof_artifacts import replay_route_body


def explain_route_body(
    config: HubConfig,
    *,
    route: str,
    prompt: str,
    output_tokens: int = 1024,
    prefer: str = "balanced",
    needs_tools: bool = False,
) -> dict[str, Any]:
    router = AgentRouter(config)
    request = HubRequest(
        session_id="explain-route",
        route=route,
        messages=[{"role": "user", "content": prompt or "Explain route."}],
        max_tokens=max(1, int(output_tokens or 1024)),
        record_session=False,
        raw={
            "routing_mode": None if prefer == "balanced" else prefer,
            "needs_tools": bool(needs_tools),
        },
    )
    decision = router.decide(request)
    payload = decision.to_dict()
    explanation = payload.get("explanation") if isinstance(payload.get("explanation"), dict) else {}
    selected = explanation.get("selected") if isinstance(explanation.get("selected"), dict) else {}
    return {
        "object": "agent_hub.route_explanation",
        "route": route,
        "selected": selected,
        "selected_agent": payload.get("selected_agent"),
        "selected_provider": payload.get("selected_provider"),
        "selected_model": payload.get("selected_model"),
        "routing_mode": payload.get("routing_mode"),
        "task_type": payload.get("task_type"),
        "candidates": _candidate_rows(payload.get("candidate_scores")),
        "reasons": explanation.get("reasons", []),
        "rejected": explanation.get("rejected", []),
        "cost_savings": explanation.get("cost_savings", {}),
        "context_optimization": explanation.get("context_optimization", {}),
        "raw_decision": payload,
    }


def format_route_explanation(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for row in report.get("candidates", []):
        if not isinstance(row, dict):
            continue
        label = _label(row)
        score = row.get("score")
        lines.append(label)
        lines.append(f"Score: {_score(score)}")
        lines.append("")
    selected = report.get("selected") if isinstance(report.get("selected"), dict) else {}
    lines.append("Selected:")
    lines.append(_label(selected) or str(report.get("selected_model") or "none"))
    lines.append("")
    lines.append("Reasons:")
    reasons = report.get("reasons") if isinstance(report.get("reasons"), list) else []
    if reasons:
        for row in reasons[:8]:
            detail = row.get("detail") if isinstance(row, dict) else row
            lines.append(f"[ok] {detail}")
    else:
        lines.append("[ok] Highest ranked compatible candidate")
    rejected = report.get("rejected") if isinstance(report.get("rejected"), list) else []
    if rejected:
        lines.append("")
        lines.append("Rejected Candidates:")
        for row in rejected[:8]:
            if not isinstance(row, dict):
                continue
            lines.append(f"Rejected {_label(row) or row.get('agent')}")
            lines.append(f"Reason: {row.get('reason') or 'Ranked behind selected model.'}")
    return "\n".join(lines).strip() + "\n"


def explain_recorded_route_body(config: HubConfig, request_id: str) -> dict[str, Any]:
    replay = replay_route_body(config, request_id)
    selected = replay.get("selected") if isinstance(replay.get("selected"), dict) else {}
    alternatives = replay.get("alternatives") if isinstance(replay.get("alternatives"), list) else []
    return {
        "object": "agent_hub.recorded_route_explanation",
        "request_id": request_id,
        "found": bool(replay.get("found")),
        "selected": selected,
        "selected_agent": selected.get("agent"),
        "selected_provider": selected.get("provider"),
        "selected_model": selected.get("model"),
        "reasons": _recorded_reasons(replay, selected),
        "rejected": [
            {
                "agent": item.get("agent"),
                "provider": item.get("provider"),
                "model": item.get("model"),
                "reason": item.get("reason") or "Ranked behind selected model.",
            }
            for item in alternatives
            if isinstance(item, dict)
        ],
        "replay": replay,
    }


def format_recorded_route_explanation(report: dict[str, Any]) -> str:
    if not report.get("found"):
        return f"No route decision found for request id {report.get('request_id')!s}.\n"
    selected = report.get("selected") if isinstance(report.get("selected"), dict) else {}
    lines = [
        f"Selected: {_label(selected) or report.get('selected_model') or 'none'}",
        "",
        "Reasons:",
    ]
    reasons = report.get("reasons") if isinstance(report.get("reasons"), list) else []
    for reason in reasons[:8]:
        lines.append(f"+ {reason}")
    if not reasons:
        lines.append("+ Highest-ranked compatible candidate")
    rejected = report.get("rejected") if isinstance(report.get("rejected"), list) else []
    if rejected:
        lines.extend(["", "Rejected:"])
        for item in rejected[:8]:
            if not isinstance(item, dict):
                continue
            lines.append(_label(item) or str(item.get("agent") or "unknown"))
            lines.append(f"  - {item.get('reason') or 'Ranked behind selected model.'}")
    return "\n".join(lines).strip() + "\n"


def _candidate_rows(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result: list[dict[str, Any]] = []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        health = row.get("health") if isinstance(row.get("health"), dict) else {}
        adaptive = row.get("adaptive") if isinstance(row.get("adaptive"), dict) else {}
        result.append(
            {
                "rank": row.get("rank"),
                "agent": row.get("agent"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "score": row.get("final_routing_score", row.get("routing_score")),
                "estimated_cost_usd": row.get("estimated_cost_usd"),
                "success_rate": _success_rate(health),
                "historical_success": _success_rate(health),
                "adaptive_bonus": adaptive.get("adaptive_bonus", 0.0),
                "why": row.get("why"),
            }
        )
    return result


def _label(row: dict[str, Any]) -> str:
    provider = str(row.get("provider") or "").strip()
    model = str(row.get("model") or "").strip()
    if provider and model:
        return f"{provider} {model}"
    return model or provider or str(row.get("agent") or "")


def _recorded_reasons(replay: dict[str, Any], selected: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    reason = str(replay.get("reason") or "").strip()
    if reason:
        reasons.append(reason)
    if selected.get("estimated_cost_usd") is not None:
        reasons.append("Lowest eligible estimated cost among recorded candidates")
    if selected.get("score") is not None:
        reasons.append("Strong routing score for the task")
    if not reasons:
        reasons.append("Healthy provider and compatible context fit")
    return reasons


def _score(value: Any) -> str:
    try:
        return str(round(float(value), 2))
    except (TypeError, ValueError):
        return "--"


def _success_rate(health: dict[str, Any]) -> float | None:
    successes = _int(health.get("success_count"))
    failures = _int(health.get("failure_count"))
    total = successes + failures
    if total <= 0:
        reliability = health.get("reliability_score")
        try:
            return round(float(reliability), 4)
        except (TypeError, ValueError):
            return None
    return round(successes / total, 4)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "explain_recorded_route_body",
    "explain_route_body",
    "format_recorded_route_explanation",
    "format_route_explanation",
]
