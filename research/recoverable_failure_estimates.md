# Recoverable Failure Estimates

Scope: cloud models only. Estimates are bounded by observed warning coverage and the existing counterfactual repair analysis.

## Recovery Ceilings

| ceiling | failures | share of all failures | interpretation |
| --- | ---: | ---: | --- |
| theoretical warning ceiling | 226 | 58.7% | all failures with a measurable warning after grounding begins |
| high counterfactual repair ceiling | 193.6 | 50.3% | optimistic repair of interpretation or action-linkage failures |
| realistic central recovery ceiling | 106.6 | 27.7% | central estimate for corrected interpretation or action linkage |
| conservative recovery floor | 75.6 | 19.6% | low estimate for the same dominant repair union |

## Recoverability By Failure Class

| failure class | failed rows | recoverability | reason |
| --- | ---: | --- | --- |
| evidence found, misinterpreted, wrong/no action | 209 | high | evidence exists and contradiction appears early |
| accepted/understood evidence disconnected from action | 204 | high | evidence exists but linkage must be repaired |
| mixed/other misgrounding | 145 | medium | warning may exist, but repair target is less specific |
| evidence not found/no grounding | 24 | low | intervention would require retrieval, outside this intervention-only scope |
| no usable grounding | 21 | very low | no grounded material exists to repair |

## Maximum Recoverable Failures

The theoretical maximum is 226 of 385 failures, or 58.7%, because those failures show a measurable warning after grounding begins. This is not a realistic operational promise; it assumes perfect detection, perfect repair selection, and no repair-induced regressions.

The realistic central ceiling is 106.6 of 385 failures, or 27.7%. This is the best current estimate for failures preventable by repairing interpretation or action linkage once grounding has begun to deteriorate.

## Direct Answers

How many failures are recoverable: central estimate 106.6 of 385 failures.

What is the theoretical recovery ceiling: 226 of 385 failures, or 58.7%.

What is the realistic recovery ceiling: about 27.7% centrally, with a plausible bounded range of 19.6%-50.3% depending on repair effectiveness.
