# GCT Measurement Protocol v2

Trial id: `gct-prospective-cloud-2026-06-17-v2`.

## Rejected Proxies

Keyword hits, final-answer style markers, post hoc commitment language, output-only evidence mentions, and success labels coupled to grounding are not valid v2 measurements.

## Event Ledger

Every completed run must emit append-only events with `run_id`, `row_id`, `timestamp`, `model_family`, `arm`, `event_type`, `payload_hash`, and `observer`. Required event types:

- `evidence_available`: task-side evidence unit exists before generation.
- `evidence_recognized`: model explicitly identifies an evidence unit before action.
- `evidence_interpreted`: model states the operational implication of the evidence before action.
- `action_proposed`: model names an intended action or branch.
- `action_taken`: model executes or finalizes an action.
- `branch_compared`: model compares at least two viable branches.
- `commitment_opened`: first irreversible choice or final answer path begins.
- `commitment_finalized`: final branch/action is locked.
- `uncertainty_state`: uncertainty/options declared before and after commitment.
- `outcome_scored`: independent rubric outcome after execution.

## Measurements

Evidence availability: count of required task-side evidence units present in the frozen row. This is measured before execution from `evidence_units_required`.

Evidence recognition: recognized evidence units divided by available evidence units. Recognition requires a pre-action ledger event naming the unit.

Evidence interpretation: correctly interpreted recognized evidence units divided by recognized units. Interpretation requires a pre-action implication linked to the unit.

GAR: grounded-action ratio = actions with a prior recognized-and-interpreted evidence link divided by all substantive proposed or taken actions. The denominator is the action ledger, not final answer text.

Commitment timing: timestamp of first `commitment_opened` event relative to first recognition, first interpretation, and first action.

Commitment strength: proportion of post-commit actions consistent with the selected branch, adjusted for reversals caused by new evidence.

Commitment quality: commitment is high quality only when it follows recognized/interpreted evidence, compares alternatives, names a verifier or outcome condition, and does not conflict with available evidence.

Uncertainty collapse: reduction in explicit viable branches or uncertainty statements from pre-commit to post-commit. Pathological collapse is flagged when uncertainty collapses before evidence interpretation.

## Independence

Outcome scoring cannot use GAR, commitment timing, commitment quality, or uncertainty collapse as input features. Outcome judges see the prompt, final artifact/answer, and frozen rubric only.
