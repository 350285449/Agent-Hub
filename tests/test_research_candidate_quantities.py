from __future__ import annotations

from agent_hub.research.candidate_quantities import candidate_quantities, evaluate_all_candidates


def test_candidate_quantities_cover_requested_ideas():
    quantities = candidate_quantities()

    assert len(quantities) == 10
    assert {quantity.name for quantity in quantities} == {
        "Context Complexity Index",
        "Failure Entropy",
        "Agent Difficulty Index",
        "Model Context Tolerance",
        "Model Specialization Index",
        "Repository Intelligence Index",
        "Routing Risk Score",
        "Model Distance Metric",
        "Information Density Index",
        "Expected Utility Score",
    }


def test_evaluate_all_candidates_returns_scored_results():
    rows = _fake_rows()

    results = evaluate_all_candidates(rows)

    assert len(results) == 10
    for row in results:
        assert 0.0 <= row["research_potential_score"] <= 1.0
        assert "falsification_evidence" in row
        assert "limitations" in row
        assert row["recommendation"] in {"continue", "kill or redesign"}
    risk = next(row for row in results if row["name"] == "Routing Risk Score")
    assert risk["usefulness_for_routing"] > 0.1


def _fake_rows():
    rows = []
    for index in range(24):
        hard = index % 4 in {2, 3}
        model = "m-good" if index % 2 == 0 else "m-weak"
        success = not hard and model == "m-good"
        score = 0.9 if success else (0.45 if model == "m-good" else 0.15)
        rows.append(
            {
                "task_id": f"task-{index % 6}",
                "task_type": "coding" if index % 3 else "docs",
                "model": model,
                "route": "fast" if model == "m-good" else "cheap",
                "repo": "repo-a" if index < 12 else "repo-b",
                "success": success,
                "validation_score": score,
                "context_tokens": 500 + index * 100,
                "context_percent": (index % 5) * 25,
                "file_count": index % 7,
                "latency_ms": 100 + index * 20,
                "cost_estimate": 0.001 * (index % 3),
                "retry_count": 0 if success else 1,
                "input_tokens": 100 + index,
                "output_tokens": 50,
                "error_count": 0 if success else 1,
            }
        )
    return rows
