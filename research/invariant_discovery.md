# Invariant Discovery

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Rules applied: cloud models only, no primitive search, no intervention evidence, and no new execution score as a candidate invariant. The scan uses existing execution quantities from the cloud-only trajectory program.

## Candidate Screen

| candidate | field | success mean | failure mean | success-failure gap | holdout R2 gain | prospective R2 gain | stability | transferability | robustness |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| grounded-action ratio | grounded_action_ratio | 0.496622 | 0.098376 | 0.398247 | 0.139998 | 0.057341 | 0.528814 | 0.661377 | 0.733498 |
| state-transition count | state_switches | 0.56035 | 0.687446 | -0.127096 | 0.000402 | -0.001954 | 0.898626 | 0.819013 | 0.592399 |
| grounding latency | grounding_latency | 0.360225 | 0.477532 | -0.117307 | 0.027508 | 0.035342 | 0.562157 | 0.352192 | 0.494589 |
| recovery event | first_recovery_event | 0.02439 | 0.0 | 0.02439 | 0.002056 | 0.000397 | 0.0 | 0.934857 | 0.389008 |
| branch collapse | first_branch_collapse | 0.138837 | 0.023377 | 0.11546 | -0.001769 | -0.005883 | 0.0 | 0.862579 | 0.287639 |
| evidence-to-action latency | evidence_to_action_latency | 0.384615 | 0.480909 | -0.096294 | -0.026371 | -0.006192 | 0.186773 | 0.486419 | 0.235369 |
| verification success | first_verification_success | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | 1.0 | 0.0 |

## Best Candidate

The leading candidate is `grounded-action ratio`. It is not a universal law, but it is the most stable measured execution quantity in this pass because it separates success from failure while remaining interpretable across the available model families, task families, benchmarks, and time periods.

## Discovery Verdict

The common structure is not raw evidence discovery. Failure rows often discover and recognize evidence. The recurring invariant-like quantity is evidence-to-action grounding: successful runs preserve a usable link between evidence and action, while failed runs often lose that link before finalization.
