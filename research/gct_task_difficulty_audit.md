# GCT Task Difficulty Audit

Dataset: `research/gct_prospective_dataset.jsonl`.

## Difficulty Summary

| measure | value |
| --- | --- |
| rows | 16 |
| difficulty range | 0.28 to 0.62 |
| mean difficulty | 0.49 |
| overall success | 81.25% |
| control success | 100.0% |
| treatment success | 62.5% |

The panel is too easy for a decisive falsification. Controls are saturated: every control row succeeded. That prevents the trial from showing that treatment improves outcomes and makes negative treatment lift hard to interpret, because success had no upward room in the control arm.

## Family Difficulty

| family | rows | mean difficulty | success | control success | treatment success |
| --- | ---: | ---: | ---: | ---: | ---: |
| agentic | 4 | 0.5325 | 100.0% | 100.0% | 100.0% |
| coding | 4 | 0.4775 | 75.0% | 100.0% | 50.0% |
| reasoning | 4 | 0.3950 | 75.0% | 100.0% | 0.0% |
| research | 4 | 0.5550 | 75.0% | 100.0% | 50.0% |

The panel is balanced by family count but not by realized difficulty or arm outcome. Reasoning is easiest by assigned difficulty but contains a treatment failure caused by a malformed response. Agentic has no failures and is uninformative for success separation.

## Trivial-Success Rows

Likely trivial or near-trivial rows:

| task | reason |
| --- | --- |
| `gct-reasoning-004` | priority rule directly states the answer; difficulty 0.28 |
| `gct-reasoning-003` | direct contrapositive; difficulty 0.34 |
| `gct-reasoning-002` | exception rule directly resolves branch; difficulty 0.41 |
| `gct-coding-003` | common 400 retry guard; difficulty 0.43 |

These rows mostly test whether the answer repeats expected keywords, not whether GCT mechanisms are necessary for success.

## Ceiling Effects

Control success saturation is severe. The control arm has no failures, so the intervention cannot show positive success lift even if it improves grounding or commitment. Treatment did raise mean commitment quality relative to control (0.6625 vs 0.49375) but lowered mean grounding quality and success.

## Determination

Task difficulty is a validity problem. The panel can identify some counterexamples to commitment necessity, but it is too ceiling-limited to support a strong causal falsification.
