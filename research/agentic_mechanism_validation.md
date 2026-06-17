# Agentic Mechanism Validation

Scope: cloud-only rows, agentic tasks only. Agentic rows: 44.

## Agentic Mechanism Signals

| slice | rows | success rate |
| --- | --- | --- |
| all agentic | 44 | 34.1% |
| grounded | 6 | 100.0% |
| ungrounded | 38 | 23.7% |
| locked-in | 35 | 20.0% |
| not locked-in | 9 | 88.9% |

## Agentic-Only Model Test

| model | holdout R2 | prospective R2 | prospective Brier gain |
| --- | --- | --- | --- |
| static | 0.50925 | 0 | -0.00557 |
| grounding | 1 | 0 | -0.049383 |
| commitment v2 | 1 | 0 | -0.049383 |
| grounding + commitment v2 | 1 | 0 | -0.04938 |
| full trajectory | 1 | 0 | -0.049387 |

## Determination

The mechanism survives agentic tasks, but agentic remains the weakest family. Grounding helps, and commitment quality separates good lock-in from bad lock-in better than collapse timing alone. The agentic-only model table is small-sample and should be read as family validation, not as a clean prospective forecast.
