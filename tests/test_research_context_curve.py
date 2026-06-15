from __future__ import annotations

import json

from agent_hub.research.ablation import ContextAblationRecord, append_context_ablation_result
from agent_hub.research.context_curve import compute_context_efficiency_curve, export_context_efficiency_curve
from agent_hub.research.dataset import export_dataset_csv
from agent_hub.research.telemetry import append_research_run


def test_context_efficiency_curve_combines_dataset_and_ablation(tmp_path):
    state = tmp_path / ".agent-hub" / "state"
    append_research_run(state, _run("r1", 1000, True, 0.5))
    append_research_run(state, _run("r2", 7000, True, 0.8))
    export_dataset_csv(state)
    append_context_ablation_result(
        state,
        ContextAblationRecord(
            task_id="a1",
            context_percent=25,
            success=False,
            validation_score=0.2,
            tokens_used=3000,
            latency_ms=100,
            cost=0.01,
        ),
    )

    curve = compute_context_efficiency_curve(state)
    paths = export_context_efficiency_curve(state)
    saved = json.loads((tmp_path / ".agent-hub" / "research" / "context_efficiency_curve.json").read_text(encoding="utf-8"))

    assert any(row["context_bucket"] == "1-2k" and row["runs"] == 1 for row in curve)
    assert any(row["context_bucket"] == "2k-5k" and row["runs"] == 1 for row in curve)
    assert saved["object"] == "agent_hub.research.context_efficiency_curve"
    assert "Context Efficiency Curve" in open(paths["markdown"], encoding="utf-8").read()


def _run(task_id, context, success, score):
    return {
        "task_id": task_id,
        "task_type": "coding",
        "selected_model": "m1",
        "context_files": ["a.py"],
        "context_token_count": context,
        "latency_ms": 100,
        "cost_estimate": 0.01,
        "validation_score": score,
        "success": success,
        "retry_count": 0,
    }
