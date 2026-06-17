# Minimal Signal Subset

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Target: recover most of the Dynamic Assimilation execution gain over `K+rho+A1-A3` using the smallest execution-event feature groups.

## Greedy Subset Recovery

| step | added group | features | incremental contribution | cumulative contribution | share of full dynamic gain | holdout R2 | prospective R2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | grounding | first_grounding_event, grounding_latency, grounded_action_ratio, evidence_to_action_latency | 0.143195 | 0.143195 | 1.100047 | 0.612539 | 0.101662 |

## Selected Minimal Model

Smallest selected group set: `grounding`.

Full dynamic event model holdout/prospective R2: 0.604526/0.07826. Full blended execution gain target: 0.130171.

## Determination

The minimal execution model is the grounding group: decisive-evidence timing, grounding latency, evidence-to-action conversion, and grounded-action ratio. Tool, verification, recovery, branch-collapse, and explicit state features can still be useful diagnostics, but they are not required to recover most of the surviving Dynamic Assimilation signal in this pass.
