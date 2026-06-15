from __future__ import annotations

import json
from typing import Any

from .config import HubConfig
from .core.router import AgentRouter
from .observability import metrics_snapshot, recent_events
from .observability_export import observability_integrations, prometheus_lines, to_otlp_span


def _observability_export_command(
    config: HubConfig,
    *,
    output_format: str = "all",
    as_json: bool = False,
) -> int:
    body = observability_export_report(config)
    output_format = str(output_format or "all").strip().lower()
    if output_format == "catalog":
        payload: Any = {"object": "agent_hub.observability_catalog", "integrations": body["integrations"]}
    elif output_format == "otlp":
        payload = body["otlp"]
    elif output_format == "prometheus":
        payload = body["prometheus"]
    else:
        payload = body

    if output_format == "prometheus" and not as_json:
        print(payload["text"], end="")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def observability_export_report(config: HubConfig) -> dict[str, Any]:
    health = AgentRouter(config).health_snapshot(include_history=True)
    metrics = metrics_snapshot(config.state_dir, health)
    otlp = _otlp_export(config)
    prometheus = _prometheus_export(metrics)
    return {
        "object": "agent_hub.observability_export",
        "integrations": [item.to_dict() for item in observability_integrations()],
        "otlp": otlp,
        "prometheus": prometheus,
    }


def _otlp_export(config: HubConfig) -> dict[str, Any]:
    events = [
        *recent_events(config.state_dir, "requests", limit=50),
        *recent_events(config.state_dir, "routing", limit=50),
        *recent_events(config.state_dir, "events", limit=50),
        *recent_events(config.state_dir, "tools", limit=50),
        *recent_events(config.state_dir, "workflows", limit=50),
    ]
    events.sort(key=lambda item: float(item.get("time") or 0.0))
    spans = [to_otlp_span(event) for event in events[-100:]]
    return {
        "object": "agent_hub.otlp_export",
        "resource": {"service.name": "agent-hub"},
        "span_count": len(spans),
        "spans": spans,
    }


def _prometheus_export(metrics: dict[str, Any]) -> dict[str, Any]:
    lines = prometheus_lines(metrics)
    return {
        "object": "agent_hub.prometheus_export",
        "content_type": "text/plain; version=0.0.4",
        "line_count": len(lines),
        "lines": lines,
        "text": "\n".join(lines) + "\n",
    }


__all__ = ["_observability_export_command", "observability_export_report"]
