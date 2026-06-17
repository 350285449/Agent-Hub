# GCT Falsification Data Audit

Dataset: `research/gct_prospective_dataset.jsonl`.

## Scope

This audit treats the previous verdict, "A. GCT falsified", as provisional. It checks whether the 16-row prospective cloud-only panel is valid evidence for a real falsification, focusing only on data quality, measurement validity, and sample validity.

## Summary Findings

| area | finding | severity |
| --- | --- | --- |
| sample size | deletion and label perturbation preserve some anti-GCT signs but destabilize model ranking | high |
| task difficulty | control success is saturated at 100% | high |
| model/provider validity | all rows use `ollama-nemotron-cloud` | high |
| intervention validity | treatment is post-draft, not clean pre-commitment | high |
| measurement validity | no true GAR; commitment and success are post hoc text heuristics | critical |
| leakage/instrumentation | prompts are fresh in code; no direct benchmark prompt reuse found; provider fields missing | moderate |

## What Holds Up

Several observed facts are robust inside this panel:

| fact | audit result |
| --- | --- |
| treatment did not improve success | robust to one- and two-row deletion and one- and two-label perturbation |
| poor-commitment successes exist | robust to one- and two-row deletion |
| no low-grounding successes under this scoring rule | baseline fact, but label perturbation can create low-grounding successes |
| prompts are not direct benchmark/replay rows | supported by prompt search and source status |

These facts justify skepticism toward GCT on this panel.

## What Does Not Hold Up

The panel does not support a decisive falsification:

| problem | consequence |
| --- | --- |
| 16 rows, 5-row holdout | model-comparison R2 is unstable |
| one model/provider route | no cross-model or cross-provider generalization |
| control saturation | intervention success lift is ceiling-limited |
| post hoc text scoring | measurement can reward prompt style rather than mechanism |
| intervention after draft | not a clean test of pre-commitment grounding/commitment |
| provider null in rows | cloud-only status is not independently auditable from row metadata |

## Leakage and Instrumentation

The 16 prompts appear only in the GCT script and GCT dataset, not in benchmark JSONL files or prior replay rows. Task IDs are unique, frozen order is 0 through 15, and assignment alternates control/treatment by order. This is reproducible but not truly random at the row level after frozen ordering.

Treatment/control contamination is possible because treatment rows include the initial draft and use the same selected agent for final response. That design controls model identity but introduces draft anchoring.

## Determination

The 16-row result should not be accepted as a real GCT falsification. It is best classified as a failed, underpowered prospective probe that motivates a redesigned prospective test.
