# Dynamic Assimilation Theory

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Falsification stance: assume continuous updates add no value over the initial prior.

## Sequential Update Results

| update stage | feature count | holdout R2 | holdout Brier gain | prospective R2 | prospective Brier gain |
| --- | --- | --- | --- | --- | --- |
| initial prior | 5 | 0.416094 | 0.093047 | 0.006192 | 0.001126 |
| + evidence events | 8 | 0.550642 | 0.123134 | 0.048531 | 0.008822 |
| + tool events | 10 | 0.604789 | 0.135243 | 0.119365 | 0.021698 |
| + verification events | 12 | 0.619349 | 0.138499 | 0.119619 | 0.021744 |
| + recovery events | 16 | 0.611615 | 0.136769 | 0.117627 | 0.021382 |

## Determination

Dynamic prediction is possible in the diagnostic sense: probability estimates improve as evidence, tool, verification, and recovery events are observed. It is not yet validated as a live online forecaster because the prospective rows are reconstructed from prior artifacts rather than frozen during a fresh run.

Verdict: strongest execution-dynamics survivor, with the caveat that the next validation must instrument events live.
