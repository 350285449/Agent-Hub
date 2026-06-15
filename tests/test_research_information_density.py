from __future__ import annotations

import json

from agent_hub.research.file_stats import update_file_stats
from agent_hub.research.information_density import compute_information_density, export_information_density_json
from agent_hub.research.telemetry import append_research_run


def test_information_density_uses_file_stats_and_context_tokens(tmp_path):
    state = tmp_path / ".agent-hub" / "state"
    good = _run("good", ["a.py"], 1000, True, 0.9)
    bad = _run("bad", ["a.py", "b.py"], 3000, False, 0.1)
    for row in [good, bad]:
        append_research_run(state, row)
        update_file_stats(state, row)

    payload = compute_information_density(state)
    output = export_information_density_json(state)
    saved = json.loads(output.read_text(encoding="utf-8"))

    assert payload["files"]["a.py"]["times_selected"] == 2
    assert payload["files"]["a.py"]["successful_inclusions"] == 1
    assert payload["files"]["a.py"]["average_context_tokens_when_selected"] == 2000
    assert payload["files"]["a.py"]["information_density"] > 0
    assert saved["object"] == "agent_hub.research.information_density"


def _run(task_id, files, context, success, score):
    return {
        "task_id": task_id,
        "task_type": "coding",
        "selected_model": "m1",
        "context_files": files,
        "context_token_count": context,
        "latency_ms": 100,
        "cost_estimate": 0.01,
        "validation_score": score,
        "success": success,
        "retry_count": 0,
    }
