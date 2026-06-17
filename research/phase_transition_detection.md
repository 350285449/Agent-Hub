# Phase Transition Detection

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Abrupt Event Jumps

| transition / event | rows after transition | success probability before | success probability after | probability jump | holdout R2 gain | prospective R2 gain |
| --- | --- | --- | --- | --- | --- | --- |
| grounded action ratio >= 0.45 | 313 | 0.41157 | 0.907348 | 0.495778 | 0.139998 | 0.057341 |
| final converging state | 257 | 0.456884 | 0.898833 | 0.441949 | 0.012624 | 0.002178 |
| recovery event | 13 | 0.574586 | 1.0 | 0.425414 | 0.002056 | 0.000397 |
| final stuck state | 184 | 0.658038 | 0.271739 | -0.386299 | 0.086626 | -0.006192 |
| branch collapse | 83 | 0.549701 | 0.891566 | 0.341866 | -0.001769 | -0.005883 |
| retrieval appears | 513 | 0.525926 | 0.623782 | 0.097856 | -0.001354 | 0.001313 |

## Threshold Scan

| signal | threshold | rows below | rows above | success below | success above | jump |
| --- | --- | --- | --- | --- | --- | --- |
| grounded_action_ratio | 0.15 | 392 | 526 | 0.211735 | 0.855513 | 0.643779 |
| dyn_signal_75 | 0.15 | 485 | 433 | 0.313402 | 0.879908 | 0.566506 |
| dyn_signal_50 | 0.25 | 309 | 609 | 0.2589 | 0.743842 | 0.484943 |
| correction_speed | 0.25 | 905 | 13 | 0.574586 | 1.0 | 0.425414 |
| dyn_signal_10 | 0.35 | 39 | 879 | 0.384615 | 0.589306 | 0.204691 |
| dyn_signal_25 | 0.25 | 261 | 657 | 0.509579 | 0.608828 | 0.099249 |

## Determination

Phase-transition behavior exists diagnostically. Runs become sharply more likely to succeed after converging/grounded-action transitions and sharply more likely to fail after final stuck states. The clearest commitment point is branch collapse or final convergence; the clearest failure point is persistence in stuck execution.
