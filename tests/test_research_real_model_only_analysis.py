from __future__ import annotations

import json
from pathlib import Path

from agent_hub.research.real_model_only_analysis import run_real_model_only_analysis


def test_real_model_only_analysis_exports_artifacts(tmp_path):
    state = tmp_path / ".agent-hub" / "state"
    research = state.parent / "research"
    research.mkdir(parents=True)
    path = research / "real_model_validation_results.jsonl"
    for row in [
        _row(0, 0, False, 0.25, ""),
        _row(25, 1200, True, 0.75, ""),
        _row(50, 2600, True, 0.8, ""),
        _row(75, 6000, False, 0.0, "timed out"),
    ]:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    result = run_real_model_only_analysis(state)

    assert Path(result["real_model_only_dataset"]).exists()
    assert Path(result["real_model_curve_fit"]).exists()
    assert Path(result["real_model_only_summary"]).read_text(encoding="utf-8").startswith("# Real Model Only Summary")


def _row(percent, tokens, success, score, error):
    return {
        "model": "qwen2.5-coder:7b",
        "repo_id": "repo",
        "context_percent": percent,
        "context_token_count": tokens,
        "validation_score": score,
        "success": success,
        "latency_ms": 10,
        "error": error,
    }
