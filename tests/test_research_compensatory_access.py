from __future__ import annotations

import json

from agent_hub.research.compensatory_access import (
    additive_surplus,
    compare_laws,
    pairwise_compensation,
    run_compensatory_access_validation,
    surplus_threshold_summary,
)


def test_compensatory_laws_include_requested_comparisons() -> None:
    rows = [
        _row("a", 0.9, 0.8, 0.8, 0.9, 0.8, 0.4, 1.0),
        _row("b", 0.8, 0.7, 0.7, 0.8, 0.7, 0.5, 1.0),
        _row("c", 0.3, 0.2, 0.4, 0.5, 0.4, 0.8, 0.0),
        _row("d", 0.2, 0.2, 0.3, 0.4, 0.4, 0.9, 0.0),
    ]

    result = compare_laws(rows)

    assert "A_multiplicative_margin" in result["metrics"]
    assert "B_additive_surplus" in result["metrics"]
    assert "C_minimum_bottleneck" in result["metrics"]
    assert "D_max_rescue" in result["metrics"]
    assert "E_pairwise_compensation" in result["metrics"]
    assert result["best_by_brier"] in result["metrics"]


def test_surplus_threshold_summary_reports_candidate_breakpoint() -> None:
    rows = [_row(str(index), 0.9, 0.9, 0.9, 0.9, 0.9, 0.4, 1.0) for index in range(8)]
    rows.extend(_row(f"f{index}", 0.2, 0.2, 0.2, 0.2, 0.2, 0.9, 0.0) for index in range(8))

    result = surplus_threshold_summary(rows)

    assert result["best_threshold"] is not None
    assert result["max_success_jump"] > 0.0
    assert sum(bucket["rows"] for bucket in result["bins"]) == len(rows)


def test_compensatory_access_artifacts_generate_from_minimal_cloud_state(tmp_path) -> None:
    research = tmp_path / ".agent-hub" / "research"
    research.mkdir(parents=True)
    live_rows = [
        _live_row("h1", success=True, timestamp="2026-01-01T00:00:00+00:00"),
        _live_row("h2", success=False, model="gemma4:31b-cloud", category="architecture", timestamp="2026-01-02T00:00:00+00:00"),
        _live_row("h3", success=True, model="gpt-5.5", category="testing", timestamp="2026-01-03T00:00:00+00:00"),
        _live_row("h4", success=False, model="gemma4:31b-cloud", category="security", timestamp="2026-01-04T00:00:00+00:00"),
    ]
    (research / "live_matrix.jsonl").write_text("\n".join(json.dumps(row) for row in live_rows), encoding="utf-8")
    (research / "prospective_predictions.jsonl").write_text("", encoding="utf-8")

    paths = run_compensatory_access_validation(tmp_path / ".agent-hub")
    dataset = json.loads(paths["dataset"].read_text(encoding="utf-8"))
    results = json.loads(paths["results"].read_text(encoding="utf-8"))

    assert dataset["row_count"] == 4
    assert all(row["non_leaky"] for row in dataset["rows"])
    assert "combined" in results["laws"]
    assert paths["compensation_matrix"].exists()
    assert "Compensatory Access" in paths["verdict"].read_text(encoding="utf-8")


def _row(row_id: str, k: float, rho: float, a: float, v: float, b: float, d: float, outcome: float) -> dict:
    product_margin = __import__("math").log(((k * rho * a * v * b) + 1e-6) / (d + 1e-6))
    minimum = min(k, rho, a, v, b) - d
    maximum = max(k, rho, a, v, b) - d
    pairwise = pairwise_compensation(k, rho, a, v, b, d)
    surplus = additive_surplus(k, rho, a, v, b, d)
    sigmoid = lambda value: 1.0 / (1.0 + pow(2.718281828, -value))
    return {
        "row_id": row_id,
        "dataset": "historical",
        "K": k,
        "rho": rho,
        "A": a,
        "V": v,
        "B": b,
        "D": d,
        "S": surplus,
        "additive_surplus_probability": sigmoid(surplus - 2.0),
        "multiplicative_margin_probability": sigmoid(product_margin),
        "minimum_bottleneck_probability": sigmoid(4.0 * minimum),
        "max_rescue_probability": sigmoid(4.0 * maximum),
        "pairwise_compensation_probability": sigmoid(pairwise - 1.0),
        "compatibility_v2": sigmoid(surplus - 2.0),
        "outcome": outcome,
    }


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
