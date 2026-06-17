# Instrumentation Validator

## Current State

Instrumentation is implemented in `agent_hub.research.gct_instrumentation` and used by `scripts/frozen_panel_executor.py`.

Validated event families:

- GAR events: evidence discovery, recognition, interpretation, justification, branch creation, branch selection, branch switching, commitment.
- Commitment events: branch selection, branch switching, commitment event, lock-in, commitment strength.
- Intervention events: pre-commit intervention events and ordering checks.

## GAR Validation

`calculate_gar()` computes:

- `action_event_count`
- `grounded_action_event_count`
- `pre_commit_gar`
- `post_commit_gar`
- `overall_gar`
- `first_commit_seq`
- `invalid_reason`

Current gate: a run is invalid when there are no groundable action events.

Remaining execution blocker: GAR validity checks prove event structure, not that model-emitted evidence refs correspond to external truth. The frozen panel requires independent outcome scoring to avoid measuring instrumentation alone.

## Commitment Validation

`measure_commitment()` computes:

- first branch choice
- first branch choice sequence
- commitment onset sequence
- commitment strength
- branch reversals
- lock-in
- invalid reason

Current gate: valid only when both branch selection and commitment event exist.

Remaining execution blocker: commitment strength can be supplied by the model. It should be treated as observed metadata unless corroborated by branch behavior.

## Intervention Validation

`validate_pre_commit_interventions()` verifies:

- intervention count
- first commitment sequence
- no intervention event occurs at or after first commitment

`apply_pre_commit_intervention()` blocks interventions after commitment onset.

Remaining execution blocker: intervention delivery is recorded, but treatment/control assignment and prompt injection delivery should be included in the row manifest and provider attempt ledger.

## Structured Output Validation

`agent_hub.research.gct_readiness.validate_structured_output()` verifies:

- JSON object parse
- nonempty `events` array
- event types allowed by phase
- no `commitment_event` during pre-commit
- required phase events present
- numeric fields are within `0..1`
- `evidence_refs` is a list
- `payload` is an object

Malformed outputs are quarantined by `quarantine_malformed_output()`.

## Fix Applied

`scripts/frozen_panel_executor.py` now correctly parses model-declared numeric event fields through `optional_float()`. Previously, non-null values returned `None` before parsing.

## Validator Certification

| Area | Status | Blocker |
| --- | --- | --- |
| GAR events | Ready for structural validation | Needs external truth/outcome linkage for scientific evidence |
| Commitment events | Ready for structural validation | Model-supplied strength needs behavioral corroboration |
| Intervention events | Ready for ordering validation | Delivery metadata should be included in immutable manifests |
| Structured output | Partially ready | Provider layer lacks first-class schema enforcement |

## Required Next Step

Extract the GCT validation logic into a reusable command:

```powershell
python scripts/gct_readiness_audit.py --panel .agent-hub/research/gct_frozen_panel_runs --strict
```

The command should fail nonzero if any row has invalid GAR, missing commitment, invalid intervention timing, accepted malformed output, replay/synthetic input, or non-cloud provider selection.

