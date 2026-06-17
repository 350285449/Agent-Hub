# Intervention Validation

The intervention engine uses `apply_pre_commit_intervention`, which raises if a commitment event already exists for the run. `validate_pre_commit_interventions` rejects intervention events at or after first commitment sequence.

Measured sequence:

- trigger timing: treatment assignment before execution
- intervention timing: `intervention_event` in pre-commit phase
- commitment timing: first `commitment_event`

200-row dry-run timing/instrumentation failures: 0.
