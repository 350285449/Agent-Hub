from __future__ import annotations

import csv
import json

from agent_hub.research.fundamental_lab import (
    load_research_observations,
    run_fundamental_research_lab,
    summarize_fundamental_lab,
)


def test_load_research_observations_reads_mixed_sources(tmp_path):
    state = tmp_path / ".agent-hub"
    research = state / "research"
    research.mkdir(parents=True)
    _write_jsonl(research / "runs.jsonl", [_row("r1", "m1", True, 0.9)])
    _write_jsonl(research / "real_model_validation_results.jsonl", [_row("r2", "m2", False, 0.2)])
    (research / "multi_model_context_scaling.json").write_text(
        json.dumps({"runs": [_row("r3", "m1", True, 0.8)]}),
        encoding="utf-8",
    )
    with (research / "dataset.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["task_type", "model", "context_tokens", "validation_score", "success"])
        writer.writeheader()
        writer.writerow({"task_type": "coding", "model": "m3", "context_tokens": "1200", "validation_score": "0.1", "success": "False"})

    rows = load_research_observations(state)

    assert len(rows) == 4
    assert {row["model"] for row in rows} == {"m1", "m2", "m3"}
    assert all(row["success"] in {True, False} for row in rows)


def test_run_fundamental_research_lab_exports_reports(tmp_path):
    state = tmp_path / ".agent-hub"
    research = state / "research"
    research.mkdir(parents=True)
    _write_jsonl(research / "runs.jsonl", [_row(f"good-{index}", "m-good", True, 0.9) for index in range(8)])
    _write_jsonl(research / "experiments.jsonl", [_row(f"bad-{index}", "m-weak", False, 0.2) for index in range(8)])

    result = run_fundamental_research_lab(state)
    summary = summarize_fundamental_lab(result)

    assert result["observation_count"] == 16
    assert len(result["quantities"]) == 10
    assert (research / "fundamental_quantities.json").exists()
    assert (research / "fundamental_quantities.md").exists()
    assert (research / "research_portfolio_rankings.json").exists()
    assert (research / "research_portfolio_rankings.md").exists()
    assert summary["top_ranked_quantity"]
    assert summary["weakest_quantity"]
    markdown = (research / "research_portfolio_rankings.md").read_text(encoding="utf-8")
    assert "Tier" in markdown
    assert "Should we continue or kill this direction?" in markdown


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def _row(task_id: str, model: str, success: bool, score: float):
    return {
        "task_id": task_id,
        "task_type": "coding",
        "selected_model": model,
        "candidate_models": [model],
        "context_files": ["a.py", "b.py"] if success else [],
        "context_token_count": 2000 if success else 100,
        "context_percent": 75 if success else 0,
        "input_tokens": 2100 if success else 100,
        "output_tokens": 50,
        "latency_ms": 100 if success else 500,
        "cost_estimate": 0.01 if success else 0.02,
        "retry_count": 0 if success else 1,
        "errors": [] if success else ["failed"],
        "route": "primary" if success else "fallback",
        "repo_id": "repo-a",
        "success": success,
        "validation_score": score,
    }
