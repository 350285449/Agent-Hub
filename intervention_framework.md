# Intervention Framework

Status: implemented.

The intervention gate is implemented in `apply_pre_commit_intervention()` and validated by `validate_pre_commit_interventions()`.

## Timing Constraint

Interventions are allowed only before the first `commitment_event`.

If an intervention is attempted after commitment onset, execution raises:

```text
GCT intervention attempted after commitment onset
```

The frozen-panel executor applies treatment interventions between the pre-commit trace phase and the commitment phase.

## Implemented Intervention

Default treatment intervention:

```text
Before committing, cite the evidence event supporting the selected branch and name one alternative.
```

Execution-mode intervention:

```text
Select only after linking the selected branch to discovered and interpreted evidence.
```

## Validation Output

Each row stores intervention validation with:

- `valid`
- `first_commit_seq`
- `intervention_count`
- `invalid_intervention_event_ids`

