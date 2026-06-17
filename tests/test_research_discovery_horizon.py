from __future__ import annotations

import json

from agent_hub.research.discovery_horizon import (
    compute_horizon_features,
    fit_candidate_laws,
    mediation_analysis,
    run_discovery_horizon_research,
)


def _row(row_id: str, *, success: float, dataset: str = "historical", rank_shift: int = 0) -> dict:
    selected = [
        f"noise_{rank_shift}.py",
        f"more_noise_{rank_shift}.py",
        f"target_{rank_shift}.py",
    ]
    return {
        "row_id": row_id,
        "dataset": dataset,
        "model": "gemma4:31b-cloud",
        "provider": "ollama-cloud",
        "route": "ollama-gemma-cloud",
        "repository": "Agent-Hub",
        "category": "bug_fix" if success else "architecture",
        "context_budget": 25,
        "selected_files": selected,
        "relevant_files": [f"target_{rank_shift}.py"],
        "compatibility_v1_score": 0.7 if success else 0.3,
        "compatibility_v2_score": 0.8 if success else 0.2,
        "eac_score": 0.75 if success else 0.25,
        "route_reliability": 0.9 if success else 0.4,
        "evidence_accessibility": 0.8 if success else 0.25,
        "verification_accessibility": 0.9 if success else 0.3,
        "success": success,
        "failure_type": "post_run_field_should_not_be_used",
    }


def test_horizon_computation_ignores_post_run_fields() -> None:
    success_row = _row("same", success=1.0)
    failure_row = {**success_row, "success": 0.0, "actual_outcome": "failure", "error": "boom"}

    success_h = compute_horizon_features(success_row)
    failure_h = compute_horizon_features(failure_row)

    assert success_h["H1_first_relevant_file_rank"] == 3
    assert success_h["H2_files_before_first_relevant"] == 2
    assert success_h["leakage_check"]["passed"] is True
    horizon_keys = [key for key in success_h if key.startswith("H")]
    assert {key: success_h[key] for key in horizon_keys} == {key: failure_h[key] for key in horizon_keys}


def test_dataset_and_reports_generate(tmp_path) -> None:
    research = tmp_path / ".agent-hub" / "research"
    research.mkdir(parents=True)
    payload = {
        "rows": [
            _row("h1", success=1.0, dataset="historical", rank_shift=1),
            _row("h2", success=0.0, dataset="historical", rank_shift=2),
            _row("p1", success=1.0, dataset="prospective", rank_shift=3),
            _row("d1", success=0.0, dataset="deconfounded_phase1", rank_shift=4),
            _row("d2", success=1.0, dataset="deconfounded_phase2", rank_shift=5),
            {**_row("local", success=1.0, rank_shift=6), "model": "local-test"},
        ]
    }
    (research / "eac_compatibility_disagreements.json").write_text(json.dumps(payload), encoding="utf-8")

    paths = run_discovery_horizon_research(tmp_path / ".agent-hub")
    dataset = json.loads(paths["dataset"].read_text(encoding="utf-8"))

    assert dataset["row_count"] == 5
    assert all(row["non_leaky"] for row in dataset["rows"])
    assert paths["definition"].exists()
    assert paths["verdict"].exists()
    assert "Discovery Horizon" in paths["vs_theories"].read_text(encoding="utf-8")


def test_mediation_calculations_return_expected_fields() -> None:
    rows = [
        {
            "compatibility_v2": 0.9,
            "route_friction": 0.8,
            "retrieval_selectivity": 0.8,
            "discovery_horizon": 0.1,
            "outcome": 1.0,
        },
        {
            "compatibility_v2": 0.7,
            "route_friction": 0.7,
            "retrieval_selectivity": 0.7,
            "discovery_horizon": 0.3,
            "outcome": 1.0,
        },
        {
            "compatibility_v2": 0.2,
            "route_friction": 0.2,
            "retrieval_selectivity": 0.2,
            "discovery_horizon": 0.8,
            "outcome": 0.0,
        },
    ]

    result = mediation_analysis(rows)

    assert "Compatibility -> Discovery Horizon -> Success" in result
    assert result["Retrieval Selectivity -> Discovery Horizon -> Success"]["x_to_horizon"] < 0
    assert "method_note" in result["Route Friction -> Discovery Horizon -> Success"]


def test_law_fits_are_scored_against_binary_outcomes() -> None:
    rows = [
        {"discovery_horizon": 0.1, "outcome": 1.0},
        {"discovery_horizon": 0.2, "outcome": 1.0},
        {"discovery_horizon": 0.8, "outcome": 0.0},
        {"discovery_horizon": 0.9, "outcome": 0.0},
    ]

    result = fit_candidate_laws(rows)

    assert result["laws"]["exponential"]["log_loss"] >= 0
    assert result["laws"]["power"]["metrics"]["brier"] <= 1
