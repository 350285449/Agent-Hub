from __future__ import annotations

from agent_hub.research.analyze import run_research_analysis
from agent_hub.research.file_stats import update_file_stats
from agent_hub.research.math_summary import generate_math_research_summary
from agent_hub.research.telemetry import append_research_run


def test_math_summary_includes_research_findings(tmp_path):
    state = tmp_path / ".agent-hub" / "state"
    for row in [
        _run("r1", "m1", ["a.py"], 1000, True, 0.9, 100, 0.01),
        _run("r2", "m2", ["b.py"], 7000, True, 0.8, 80, 0.02),
        _run("r3", "m1", ["a.py"], 12000, False, 0.2, 200, 0.03),
    ]:
        append_research_run(state, row)
        update_file_stats(state, row)

    paths = run_research_analysis(state)
    summary = generate_math_research_summary(state)
    text = summary.read_text(encoding="utf-8")

    assert "Main Dataset Statistics" in text
    assert "Best model by success rate" in text
    assert "Best model by efficiency" in text
    assert "Context bucket with best success per token" in text
    assert "Pareto-Optimal Runs" in text
    assert "Limitations And Missing Data" in text
    assert paths["analysis"].endswith("analysis.json")
    assert paths["math_research_summary"].endswith("math_research_summary.md")


def _run(task_id, model, files, context, success, score, latency, cost):
    return {
        "task_id": task_id,
        "task_type": "coding",
        "selected_model": model,
        "context_files": files,
        "context_token_count": context,
        "latency_ms": latency,
        "cost_estimate": cost,
        "validation_score": score,
        "success": success,
        "retry_count": 0,
    }
