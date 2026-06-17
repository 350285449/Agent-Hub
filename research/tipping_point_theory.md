# Tipping Point Theory

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Falsification stance: assume success probability changes smoothly and no trigger creates abrupt jumps.

## Event Trigger Tests

| trigger | triggered rows | success if triggered | success if absent | probability jump | holdout R2 gain | prospective R2 gain |
| --- | --- | --- | --- | --- | --- | --- |
| first_recovery_event | 13 | 1.0 | 0.574586 | 0.425414 | 0.002056 | 0.000397 |
| state_recovered | 13 | 1.0 | 0.574586 | 0.425414 | 0.002056 | 0.000397 |
| state_grounded | 249 | 0.88755 | 0.466368 | 0.421182 | 0.006688 | 0.004051 |
| first_decisive_evidence | 611 | 0.620295 | 0.501629 | 0.118666 | 0.010726 | 0.030434 |

## Threshold Scan

| signal | best threshold | rows above | success above | success below | jump |
| --- | --- | --- | --- | --- | --- |
| grounded_action_ratio | 0.15 | 526 | 0.855513 | 0.211735 | 0.643779 |
| dyn_signal_75 | 0.15 | 433 | 0.879908 | 0.313402 | 0.566506 |
| dyn_signal_50 | 0.25 | 609 | 0.743842 | 0.2589 | 0.484943 |
| correction_speed | 0.15 | 13 | 1.0 | 0.574586 | 0.425414 |
| dyn_signal_25 | 0.25 | 657 | 0.608828 | 0.509579 | 0.099249 |

## Determination

Tipping behavior is visible when decisive evidence, grounded action, verification, or recovery events cross thresholds. The prospective reconstruction is too weak to promote a universal phase-transition law.

Verdict: survives as bounded diagnostic phenomenon; fails as universal predictive law.
