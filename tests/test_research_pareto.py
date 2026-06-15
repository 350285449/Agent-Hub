from __future__ import annotations

import json

from agent_hub.research.analysis import compute_pareto_frontier, export_pareto_frontier_json
from agent_hub.research.telemetry import append_research_run


def test_compute_pareto_frontier_uses_quality_cost_latency_and_context(tmp_path):
    state = tmp_path / ".agent-hub" / "state"
    runs = [
        _run("best", 0.9, 0.01, 100, 1000),
        _run("dominated", 0.8, 0.02, 120, 2000),
        _run("cheap", 0.7, 0.001, 90, 500),
    ]
    for row in runs:
        append_research_run(state, row)

    frontier = compute_pareto_frontier(runs)
    output = export_pareto_frontier_json(state)
    saved = json.loads(output.read_text(encoding="utf-8"))

    assert {row["task_id"] for row in frontier} == {"best", "cheap"}
    assert saved["object"] == "agent_hub.research.pareto_frontier"
    assert {row["task_id"] for row in saved["runs"]} == {"best", "cheap"}


def _run(task_id, score, cost, latency, context):
    return {
        "task_id": task_id,
        "task_type": "coding",
        "selected_model": task_id,
        "context_token_count": context,
        "latency_ms": latency,
        "cost_estimate": cost,
        "validation_score": score,
        "success": True,
        "retry_count": 0,
    }
