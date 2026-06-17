from __future__ import annotations

from scripts import grounding_integrity_randomized_trial as trial


def test_frozen_randomized_trial_assignment_is_reproducible():
    first = trial.assign(trial.frozen_rows())
    second = trial.assign(trial.frozen_rows())

    assert len(first) == 918
    assert [row["assigned_arm"] for row in first] == [row["assigned_arm"] for row in second]
    assert {row["assigned_arm"] for row in first} == {"control", "treatment"}
    assert all(row["assignment_seed"] == trial.SEED for row in first)
    assert all(row["intervention_delivered"] is False for row in first)
    assert any(row["trigger_eligible"] for row in first)


def test_randomized_trial_effect_is_assignment_contrast_without_delivery():
    rows = trial.assign(trial.frozen_rows())
    control = trial.arm_stats(rows, "control")
    treatment = trial.arm_stats(rows, "treatment")

    assert control["delivered"] == 0
    assert treatment["delivered"] == 0
    assert control["n"] + treatment["n"] == len(rows)
    assert control["successes"] + treatment["successes"] == 533
    assert control["failures"] + treatment["failures"] == 385
