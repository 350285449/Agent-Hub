from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ObservabilityBackend = Literal["opentelemetry", "prometheus", "grafana", "jaeger"]


@dataclass(frozen=True, slots=True)
class ObservabilityIntegration:
    id: ObservabilityBackend
    protocol: str
    default_enabled: bool
    description: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "protocol": self.protocol,
            "default_enabled": self.default_enabled,
            "description": self.description,
        }


def observability_integrations() -> list[ObservabilityIntegration]:
    return [
        ObservabilityIntegration("opentelemetry", "otlp-json", False, "Trace export for API, router, provider, tool, plugin, and workflow events."),
        ObservabilityIntegration("prometheus", "text", False, "Scrapeable counters for provider health, cost, latency, failures, and token savings."),
        ObservabilityIntegration("grafana", "dashboard-json", False, "Dashboard definitions for operational views."),
        ObservabilityIntegration("jaeger", "otlp", False, "Trace visualization through OTLP-compatible collectors."),
    ]


def to_otlp_span(event: dict[str, Any]) -> dict[str, Any]:
    trace_id = str(event.get("trace_id") or event.get("request_id") or "")
    span_id = str(event.get("span_id") or event.get("request_id") or "")
    return {
        "traceId": trace_id,
        "spanId": span_id,
        "name": str(event.get("name") or event.get("type") or "agent_hub.event"),
        "attributes": [
            {"key": key, "value": {"stringValue": str(value)}}
            for key, value in sorted(event.items())
            if key not in {"messages", "raw"}
        ],
    }


def prometheus_lines(snapshot: dict[str, Any]) -> list[str]:
    counters = snapshot.get("counters") if isinstance(snapshot.get("counters"), dict) else {}
    lines = ["# HELP agent_hub_counter Agent-Hub local runtime counters", "# TYPE agent_hub_counter counter"]
    for key, value in sorted(counters.items()):
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        lines.append(f'agent_hub_counter{{name="{key}"}} {number}')
    return lines
