# Mechanism Intervention Causality

Scope: delivered cloud-only intervention evidence from the newly executed 20-row cloud-only run in `research/live_trial_execution_log.jsonl`. The causal table uses the 19 analyzable completed cloud-only rows; no historical assignment-only rows are counted as delivered intervention evidence.

## Control vs Treatment

| arm | runs | successes | failures | success rate | delivered interventions | recovered | regressed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| control | 7 | 5 | 2 | 71.4% | 0 | 0 | 0 |
| treatment | 12 | 10 | 2 | 83.3% | 2 | 0 | 1 |

Absolute treatment-control success difference: 11.9% with approximate 95% CI [-27.6%, 51.5%].

## Delivered Intervention Accounting

| delivered treatment rows | draft failures recovered | draft successes regressed | net recovered minus regressed |
| --- | --- | --- | --- |
| 2 | 0 | 1 | -1 |

## Determination

Delivered intervention causality is now testable, but it is not positive enough to promote the mechanism to an execution law. Assignment-level treatment success is directionally higher in the small sample, but delivered repair has more observed regressions than recoveries. The intervention must be tightened before causality can support law status.
