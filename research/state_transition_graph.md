# State Transition Graph

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Edges are observed transitions between the sampled execution windows 10%, 25%, 50%, and 75%.

## Ranked Transitions

| rank | transition | rows | success if present | success if absent | holdout R2 gain | prospective R2 gain | contribution |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | stuck -> exploring | 80 | 0.9125 | 0.548926 | 0.055416 | -0.006192 | 0.026365 |
| 2 | grounded -> converging | 231 | 0.887446 | 0.477438 | 0.00683 | 0.002454 | 0.00466 |
| 3 | stuck -> converging | 5 | 1.0 | 0.578313 | 0.002908 | 0.002221 | 0.002417 |
| 4 | exploring -> grounded | 38 | 0.789474 | 0.571591 | 0.00365 | 0.000711 | 0.002269 |
| 5 | stuck -> recovered | 11 | 1.0 | 0.575524 | 0.001119 | 0.000186 | 0.000684 |
| 6 | exploring -> converging | 21 | 1.0 | 0.570792 | 0.001325 | -0.000557 | 0.000524 |
| 7 | grounded -> recovered | 2 | 1.0 | 0.579694 | -0.000113 | 0.000105 | -2.4e-05 |
| 8 | exploring -> stuck | 14 | 0.642857 | 0.579646 | 0.000448 | -0.006192 | -0.002094 |

## Requested Transition Tests

| transition / endpoint | rows | target rate if present | target rate if absent | holdout R2 gain | prospective R2 gain |
| --- | --- | --- | --- | --- | --- |
| exploring -> grounded | 38 | 0.789474 | 0.571591 | 0.00365 | 0.000711 |
| grounded -> converging | 231 | 0.887446 | 0.477438 | 0.00683 | 0.002454 |
| converging -> success | 257 | 0.898833 | 0.456884 | 0.012624 | 0.002178 |
| stuck -> failure | 184 | 0.728261 | 0.341962 | 0.086626 | -0.006192 |
| recovered -> success | 13 | 1.0 | 0.574586 | 0.002056 | 0.000397 |

## Graph Reading

The beneficial path is exploration into grounding, then grounding into convergence, then convergence into success. The damaging path is persistence in stuck states. Recovery is rarer and does not dominate the predictive model, but when observed it identifies a distinct late repair mechanism.
