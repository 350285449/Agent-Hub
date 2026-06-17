# Measurement Audit

Scope: cloud rows only, 1091 rows aligned from Evidence Access and Actionability datasets. Existing formulas and predictions were not modified.

## Primitive Definitions And Lineage

| variable | intended target | current measurement | lineage | audit verdict |
| --- | --- | --- | --- | --- |
| K | model capability | leave-one-out model historical effective score | `success`, `validation_score`, model ID | useful but outcome-derived; proxy for realized performance |
| rho | specialization | leave-one-out model-task excess score | `success`, `validation_score`, model ID, task/category | outcome-derived and partly circular with K |
| A | accessibility | current Evidence Access A in this pass; older primitive A was context volume | retrieval fields, benchmark labels, output-reference fields in some components | improved but mixed timing; A4/A5 are post-generation |

Current primitive R2 on this aligned corpus: `0.485879`. Observed feature R2 with existing measured variables: `0.49653`.

## Dependency Audit

| measurement | proxy? | derived? | leakage risk | circularity risk | post-run contamination |
| --- | --- | --- | --- | --- | --- |
| K | yes | yes | medium | medium | low direct, because leave-one-out excludes current row |
| rho | yes | yes | medium-high | high, shares outcome substrate with K | low direct |
| A old context-volume | yes | yes | low | low | none |
| Evidence Access A | partly | yes | mixed | low | E6/E9 use output-side behavior |
| Route Friction | yes | yes | medium | medium | uses route prior outcomes |
| Retrieval Selectivity | yes | yes | low-medium | low | depends on A implementation |
| Compatibility v2 | yes | yes | medium | medium | time-aware priors reduce direct leakage |
| Actionability A1-A10 | yes | yes | low for clean components | low | killed as weak |
| E9 | no as primitive | yes | high | high | yes, generated-output diagnostic |

## Main Failure Modes

- K and rho are not independent instruments; both are historical outcome summaries.
- rho is under-resolved: task category is too coarse and misses repository affinity, tool-use affinity, and long-context affinity.
- A mixes clean retrieval/benchmark measurements with post-generation evidence-use measurements unless decomposed by timing.
- Route Friction and Compatibility v2 contain success-derived reliability priors; they are useful diagnostics but weak primitive evidence.
- E9 is excluded from primitive claims because it observes model output.

Conclusion: the residual is currently more consistent with measurement contamination and under-resolution than with a demonstrated fourth primitive.
