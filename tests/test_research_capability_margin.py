from __future__ import annotations

import json

from agent_hub.research.capability_margin import (
    compare_alternative_laws,
    execution_budget_score,
    phase_transition_summary,
    run_capability_margin_validation,
    task_demand,
)


def test_fixed_feature_scores_are_bounded() -> None:
    assert execution_budget_score(0) == 0.10
    assert execution_budget_score(25) == 0.45
    assert execution_budget_score(100) == 1.0
    assert 0.001 <= task_demand("architecture", 0) <= 0.999
    assert task_demand("architecture", 0) > task_demand("architecture", 30)


def test_phase_transition_summary_uses_requested_bins() -> None:
    rows = [
        _margin_row("a", -3.0, 0.0),
        _margin_row("b", -1.5, 0.0),
        _margin_row("c", -0.5, 1.0),
        _margin_row("d", 0.5, 1.0),
        _margin_row("e", 1.5, 1.0),
        _margin_row("f", 2.5, 1.0),
    ]

    result = phase_transition_summary(rows)

    assert [row["bin"] for row in result["bins"]] == [
        "M < -2",
        "-2 <= M < -1",
        "-1 <= M < 0",
        "0 <= M < 1",
        "1 <= M < 2",
        "M >= 2",
    ]
    assert sum(row["rows"] for row in result["bins"]) == 6


def test_alternative_laws_report_margin_and_additive() -> None:
    rows = [
        _full_row("a", 0.9, 0.8, 0.8, 0.9, 0.8, 0.4, 1.0),
        _full_row("b", 0.8, 0.7, 0.7, 0.8, 0.7, 0.5, 1.0),
        _full_row("c", 0.3, 0.2, 0.4, 0.5, 0.4, 0.8, 0.0),
        _full_row("d", 0.2, 0.2, 0.3, 0.4, 0.4, 0.9, 0.0),
    ]

    result = compare_alternative_laws(rows)

    assert "M_log_product_minus_demand" in result["metrics"]
    assert "M1_additive" in result["metrics"]
    assert result["best_by_brier"] in result["metrics"]


def test_capability_margin_artifacts_generate_from_minimal_cloud_state(tmp_path) -> None:
    research = tmp_path / ".agent-hub" / "research"
    research.mkdir(parents=True)
    live_rows = [
        _live_row("h1", success=True, timestamp="2026-01-01T00:00:00+00:00"),
        _live_row("h2", success=False, model="gemma4:31b-cloud", category="architecture", timestamp="2026-01-02T00:00:00+00:00"),
    ]
    (research / "live_matrix.jsonl").write_text("\n".join(json.dumps(row) for row in live_rows), encoding="utf-8")
    (research / "prospective_predictions.jsonl").write_text("", encoding="utf-8")

    paths = run_capability_margin_validation(tmp_path / ".agent-hub")
    dataset = json.loads(paths["dataset"].read_text(encoding="utf-8"))

    assert dataset["row_count"] == 2
    assert all(row["non_leaky"] for row in dataset["rows"])
    assert paths["report"].exists()
    assert "Capability Margin" in paths["verdict"].read_text(encoding="utf-8")


def _margin_row(row_id: str, margin: float, outcome: float) -> dict:
    probability = 1.0 / (1.0 + pow(2.718281828, -margin))
    return {"row_id": row_id, "M": margin, "outcome": outcome, "capability_margin_probability": probability}


def _full_row(row_id: str, k: float, rho: float, a: float, v: float, b: float, d: float, outcome: float) -> dict:
    numerator = k * rho * a * v * b
    margin = __import__("math").log((numerator + 1e-6) / (d + 1e-6))
    row = _margin_row(row_id, margin, outcome)
    row.update({"K": k, "rho": rho, "A": a, "V": v, "B": b, "D": d, "numerator": numerator})
    return row


def _live_row(
    row_id: str,
    *,
    success: bool,
    model: str = "gpt-5.5",
    category: str = "testing",
    timestamp: str,
) -> dict:
    return {
        "row_id": row_id,
        "live": True,
        "model": model,
        "provider": "openai",
        "provider_type": "openai-compatible",
        "route": "openai-cloud",
        "repository": "Agent-Hub",
        "category": category,
        "context_budget": 25,
        "compatibility_score": 0.7 if success else 0.3,
        "success": success,
        "timestamp": timestamp,
    }
