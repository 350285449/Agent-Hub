from __future__ import annotations

import time
from typing import Any

from .benchmark_report import write_benchmark_report


def run_benchmark(config: Any, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    agents = [
        {
            "agent": name,
            "provider": agent.provider,
            "model": agent.model,
            "pricing_configured": agent.free or (
                agent.cost_per_million_input is not None and agent.cost_per_million_output is not None
            ),
        }
        for name, agent in sorted(config.agents.items())
        if getattr(agent, "enabled", True)
    ]
    report = {
        "object": "agent_hub.benchmark_report",
        "created_at": time.time(),
        "mode": str(payload.get("mode") or "baseline_snapshot"),
        "results": agents,
        "summary": {
            "agent_count": len(agents),
            "measured": False,
            "note": "Baseline snapshot created without provider calls.",
        },
    }
    path = write_benchmark_report(config, report)
    return {**report, "path": str(path), "accepted": True}
