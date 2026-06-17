from __future__ import annotations

from scripts import live_grounding_intervention_trial as trial


def test_live_batch_freezing_and_assignment_are_reproducible():
    first = trial.assign_tasks(trial.load_source_tasks(8))
    second = trial.assign_tasks(trial.load_source_tasks(8))

    assert len(first) == 8
    assert [row["frozen_task_id"] for row in first] == [row["frozen_task_id"] for row in second]
    assert [row["assigned_arm"] for row in first] == [row["assigned_arm"] for row in second]
    assert {row["assigned_arm"] for row in first} == {"control", "treatment"}
    assert all(row["trial_id"] == trial.TRIAL_ID for row in first)


def test_trigger_detection_covers_required_treatment_events():
    info = trial.detect_triggers(
        "I cannot determine the patch. This contradicts the middleware behavior.",
        ["pytest", "403", "middleware", "regression"],
    )

    assert info["triggered"] is True
    assert info["triggers"]["contradictory_grounding"] is True
    assert info["triggers"]["evidence_action_mismatch"] is True
    assert info["triggers"]["grounding_collapse"] is True
    assert info["triggers"]["grounded_action_ratio_below_threshold"] is True


def test_keyword_evaluator_is_deterministic():
    result = trial.evaluate(
        "Add a pytest regression for the refund double-count bug.",
        ["pytest", "refund", "double-count", "regression"],
    )

    assert result["success"] == 1
    assert result["keyword_hits"] == 4


def test_verdict_requires_delivered_positive_recovery():
    summary = {
        "absolute_success_improvement": 0.25,
        "treatment": {
            "delivered": 1,
            "recovered": 1,
            "regressed": 0,
            "token_overhead": 400,
            "latency_overhead_ms": 2000,
        },
    }

    assert trial.verdict(summary) == "C. Effective intervention mechanism"

    summary["treatment"]["delivered"] = 0
    assert trial.verdict(summary) == "B. Useful warning signal"
