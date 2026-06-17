# GAR Implementation

Status: implemented.

GAR is calculated in `calculate_gar()` in `agent_hub/research/gct_instrumentation.py`.

## Stored Metrics

The implementation stores:

- `local_grounding`
- `pre_commit_gar`
- `post_commit_gar`
- `overall_gar`
- action event count
- grounded action event count
- first commitment sequence
- invalid reason, if any

## True Event-Level GAR

GAR is not calculated from final answers or post-hoc keyword proxies.

Grounding is computed from event-time evidence links:

- Evidence events establish evidence IDs.
- Groundable actions must reference prior evidence event IDs through `evidence_refs`.
- If an action has no valid prior evidence reference, it is ungrounded or capped.
- Explicit `local_grounding` can lower an event score but cannot rescue an action that lacks valid prior evidence linkage.

Groundable action event types:

- evidence recognition
- evidence interpretation
- justification
- branch creation
- branch selection
- branch switching
- commitment

`pre_commit_gar` is calculated only over groundable actions before the first `commitment_event`. `post_commit_gar` is calculated from the first commitment event onward.

