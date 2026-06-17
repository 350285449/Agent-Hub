# Information Event Analysis

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Ranked Information Events

| event | event type | triggered rows | success-probability jump | holdout R2 gain | prospective R2 gain | impact score |
| --- | --- | --- | --- | --- | --- | --- |
| first_grounding_event | grounding event | 249 | 0.421182 | 0.006688 | 0.004051 | 0.088664 |
| first_recovery_event | reasoning/recovery event | 13 | 0.425414 | 0.002056 | 0.000397 | 0.086147 |
| first_branch_collapse | reasoning commitment event | 83 | 0.341866 | -0.001769 | -0.005883 | 0.065518 |
| first_decisive_evidence | evidence event | 611 | 0.118666 | 0.010726 | 0.030434 | 0.039212 |
| first_retrieval_event | retrieval event | 513 | 0.097856 | -0.001354 | 0.001313 | 0.019421 |
| first_successful_tool_call | tool event | 0 | timing-only | 0.0 | 0.0 | 0.0 |
| first_verification_attempt | verification event | 0 | timing-only | 0.0 | 0.0 | 0.0 |
| first_verification_success | verification event | 0 | timing-only | 0.0 | 0.0 | 0.0 |

## Determination

The decisive events are not generic tool calls. The largest direction changes come from events that collapse the action branch: grounded evidence-to-action conversion, branch collapse, and verification/recovery when present. Retrieval alone is necessary but not sufficient.
