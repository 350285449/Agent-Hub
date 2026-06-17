# Control Policy Tournament

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. Policies are compared by outcome change, intervention cost, and robustness.

Baseline: 918 aligned cloud rows, 385 failures, 533 successes.

## Tournament Policies

| policy | description |
| --- | --- |
| Policy A: No intervention | observe execution without repair |
| Policy B: Grounding confirmation | run full evidence-interpretation-action confirmation at severe warning or pre-final gate |
| Policy C: Contradiction detection | detect and resolve decision-relevant contradictions once evidence appears |
| Policy D: Action consistency | require planned action to preserve accepted evidence |
| Policy E: Combined policy | staged contradiction, verification, action consistency, and confirmation gates |

## Outcome Comparison

| rank | policy | prevented failures | simulated failure rate | simulated success rate | intervention cost | robustness |
| ---: | --- | ---: | ---: | ---: | --- | --- |
| 1 | Policy E: Combined policy | 106.6 central, 193.6 optimistic practical | 30.3% central | 69.7% central | medium-high | highest |
| 2 | Policy B: Grounding confirmation | 96.3-107.8 | 30.2%-31.5% | 68.5%-69.8% | high | high |
| 3 | Policy C: Contradiction detection | 88.6-104.0 | 30.6%-32.3% | 67.7%-69.4% | moderate | high |
| 4 | Policy D: Action consistency | 84.7-96.3 | 31.5%-32.7% | 67.3%-68.5% | moderate | high |
| 5 | Policy A: No intervention | 0.0 | 41.9% | 58.1% | none | low |

## Cost-Normalized Reading

| policy | outcome strength | cost profile | when it should run |
| --- | --- | --- | --- |
| No intervention | none | zero | never as the primary Agent-Hub policy |
| Grounding confirmation | strongest single intervention | highest cost | severe warning and pre-final gate |
| Contradiction detection | best early return | moderate | every evidence update after first recognition |
| Action consistency | best action-link repair | moderate | every material action change |
| Combined policy | best total robustness | medium-high when staged | always, but with escalating gates |

## Winning Policy

Policy E wins because it applies cheaper interventions first and reserves full grounding confirmation for severe warnings and the pre-final gate. It gets the same central recovery target as the best union estimate while reducing unnecessary confirmation passes.

## Determination

The winning control policy is a staged combined policy:

1. Detect contradiction as soon as evidence appears.
2. Recheck or verify evidence when support is weak.
3. Check action consistency whenever action changes.
4. Run grounding confirmation when integrity is fragile, collapsed, or pre-final.

This is the best available policy for changing outcomes rather than merely predicting failures.
