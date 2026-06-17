# GCT Sample Sensitivity Audit

Dataset: `research/gct_prospective_dataset.jsonl`.

## Baseline

| measure | value |
| --- | --- |
| rows | 16 |
| control rows | 8 |
| treatment rows | 8 |
| control success | 100.0% |
| treatment success | 62.5% |
| treatment lift | -37.5 percentage points |
| poor-commitment successes | 4 |
| low-grounding successes | 0 |
| capability model A holdout R2 | 0.815753 |
| GCT model D holdout R2 | 0.314541 |

The main anti-GCT signs are not all equally stable. The negative intervention result and poor-commitment counterexamples are stable under deletion. The model-comparison result is not stable enough to carry a falsification by itself.

## One-Row Removal

| check | result |
| --- | --- |
| treatment lift range | -42.9 to -28.6 percentage points |
| poor-commitment success range | 3 to 4 |
| low-grounding success range | 0 |
| capability model A R2 range | 0.000000 to 0.871391 |
| GCT model D R2 range | 0.000000 to 0.637939 |
| cases where D beats A | 1 of 16 |

Removing `gct-research-001` makes Model A collapse to zero R2 while Model D remains positive. That does not rescue GCT, because the intervention still has negative lift and poor-commitment successes remain. It does show that the holdout model ranking is highly sample-sensitive.

## Two-Row Removal

| check | result |
| --- | --- |
| treatment lift range | -50.0 to -16.7 percentage points |
| poor-commitment success range | 2 to 4 |
| low-grounding success range | 0 |
| capability model A R2 range | 0.000000 to 0.900226 |
| GCT model D R2 range | 0.000000 to 0.784767 |
| cases where D beats A | 13 of 120 |

Two-row removal never makes treatment beneficial and never removes poor-commitment successes. It can, however, change the model-ranking conclusion. The panel is too small for the fitted holdout model comparison to be treated as robust.

## Treatment/Control Split

The actual assignment alternates by frozen order: even rows control, odd rows treatment. With the observed success labels fixed, all possible 8/8 treatment-control splits have treatment lift from -37.5 to +37.5 percentage points. Exactly half are positive and half are negative.

This means the intervention conclusion depends heavily on which rows were assigned to treatment, even though the observed assignment produced a clear negative effect. Family balance also differs by arm: agentic treatment rows all succeeded, while reasoning treatment rows did not.

## Success-Label Perturbation

| perturbation | D beats A | treatment lift range | poor-commitment success range | low-grounding success range |
| --- | ---: | --- | --- | --- |
| one success label flipped | 4 of 16 | -50.0 to -25.0 points | 3 to 5 | 0 to 1 |
| two success labels flipped | 30 of 120 | -62.5 to -12.5 points | 2 to 5 | 0 to 2 |

The negative treatment effect survives one- and two-label perturbations. The model ranking does not. A single label flip can make Model D beat Model A in 4 of 16 cases.

## Determination

Sample sensitivity does not rescue GCT, but it weakens the falsification claim. The direct evidence against GCT is robust for intervention failure and poor-commitment successes, but the fitted model-comparison evidence is underpowered and unstable.
