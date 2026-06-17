from __future__ import annotations

import json
from datetime import datetime, timezone

from agent_hub.research.compatibility_v2 import (
    CompatibilityV2Row,
    compatibility_v2_report_path,
    compatibility_v2_results_path,
    compute_non_leaky_features,
    evaluate_compatibility_v2,
    run_compatibility_v2_evaluation,
)


def _row(row_id: str, *, success: float, timestamp: str, model: str = "m1") -> CompatibilityV2Row:
    return CompatibilityV2Row(
        row_id=row_id,
        dataset="unit",
        model=model,
        provider="cloud-provider",
        provider_type="cloud-provider",
        route="cloud-route",
        repository="repo",
        category="testing",
        context_budget=0,
        compatibility_v1_score=0.5,
        success=success,
        timestamp=datetime.fromisoformat(timestamp).replace(tzinfo=timezone.utc),
    )


def test_leave_one_out_priors_exclude_current_row() -> None:
    rows = [
        _row("current", success=1.0, timestamp="2026-01-01T00:00:00"),
        _row("past-failure", success=0.0, timestamp="2026-01-01T00:01:00"),
        _row("past-success", success=1.0, timestamp="2026-01-01T00:02:00"),
    ]

    features = compute_non_leaky_features(rows, mode="leave_one_out")
    current = next(row for row in features if row["row_id"] == "current")

    assert current["prior_excludes_current_row"] is True
    assert current["model_reliability_prior"] == 0.5
    assert current["model_route_reliability_prior_count"] == 2


def test_time_aware_priors_exclude_future_rows() -> None:
    rows = [
        _row("first", success=0.0, timestamp="2026-01-01T00:01:00"),
        _row("future", success=1.0, timestamp="2026-01-01T00:02:00"),
    ]

    features = compute_non_leaky_features(rows, mode="time_aware")
    first = next(row for row in features if row["row_id"] == "first")
    future = next(row for row in features if row["row_id"] == "future")

    assert first["future_rows_excluded"] is True
    assert first["model_route_reliability_prior_count"] == 0
    assert future["future_rows_excluded"] is True
    assert future["model_route_reliability_prior_count"] == 1


def test_v1_artifacts_remain_preserved_and_reports_generate(tmp_path) -> None:
    state = tmp_path / ".agent-hub"
    research = state / "research"
    research.mkdir(parents=True)
    for name in (
        "compatibility_metrics.json",
        "compatibility_prediction.json",
        "compatibility_v1_postmortem.md",
        "prospective_results.json",
    ):
        payload = {"matches": [], "freeze_time_utc": "2026-01-01T00:00:00+00:00"} if name == "prospective_results.json" else {}
        (research / name).write_text(json.dumps(payload), encoding="utf-8")
    (research / "prospective_predictions.jsonl").write_text("", encoding="utf-8")
    (research / "live_matrix.jsonl").write_text("", encoding="utf-8")

    result = evaluate_compatibility_v2(state)
    paths = run_compatibility_v2_evaluation(state)

    assert all(result["v1_artifacts_preserved"].values())
    assert paths["results_json"] == compatibility_v2_results_path(state)
    assert paths["report"] == compatibility_v2_report_path(state)
    assert paths["results_json"].exists()
    assert paths["report"].exists()
