from __future__ import annotations

import json

from agent_hub.research.analysis import analyze_research_dir, context_bucket, export_analysis_json
from agent_hub.research.telemetry import append_research_run


def test_research_analysis_computes_dataset_metrics(tmp_path):
    state = tmp_path / ".agent-hub" / "state"
    _write_runs(state)

    analysis = analyze_research_dir(state)
    output = export_analysis_json(state)

    assert analysis["total_runs"] == 3
    assert analysis["success_rate"] == 2 / 3
    assert analysis["average_validation_score"] == 0.6
    assert analysis["success_rate_by_model"]["m1"]["success_rate"] == 0.5
    assert analysis["success_rate_by_task_type"]["coding"]["runs"] == 3
    assert analysis["success_rate_by_context_bucket"]["1-2k"]["runs"] == 1
    assert analysis["success_per_1k_context_tokens"] > 0
    assert analysis["cost_per_successful_run"] > 0
    assert analysis["retry_rate"] == 1 / 3
    assert analysis["model_efficiency_score"]["m2"]["efficiency_score"] > 0
    assert json.loads(output.read_text(encoding="utf-8"))["object"] == "agent_hub.research.analysis"


def test_context_bucket_boundaries():
    assert context_bucket(0) == "0 tokens"
    assert context_bucket(1) == "1-2k"
    assert context_bucket(2500) == "2k-5k"
    assert context_bucket(7000) == "5k-10k"
    assert context_bucket(12000) == "10k-25k"
    assert context_bucket(30000) == "25k+"


def _write_runs(state):
    for row in [
        _run("r1", "m1", 1000, True, 0.9, 100, 0.01, 0),
        _run("r2", "m1", 3000, False, 0.2, 200, 0.02, 1),
        _run("r3", "m2", 8000, True, 0.7, 120, 0.005, 0),
    ]:
        append_research_run(state, row)


def _run(task_id, model, context, success, score, latency, cost, retries):
    return {
        "task_id": task_id,
        "task_type": "coding",
        "selected_model": model,
        "candidate_models": ["m1", "m2"],
        "input_tokens": 100,
        "output_tokens": 20,
        "context_files": ["a.py"],
        "context_token_count": context,
        "latency_ms": latency,
        "cost_estimate": cost,
        "validation_score": score,
        "success": success,
        "retry_count": retries,
    }
