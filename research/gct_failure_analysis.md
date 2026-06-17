# GCT Failure Analysis

## False Positives

Cases where GCT predicts success but failure occurs.

| task | family | grounding | commitment | keyword hits |
| --- | --- | --- | --- | --- |
| none |  |  |  |  |

## False Negatives

Cases where GCT predicts failure but success occurs.

| task | family | grounding | commitment | keyword hits |
| --- | --- | --- | --- | --- |
| gct-coding-002 | coding | 1 | 0.45 | 4/4 |
| gct-reasoning-003 | reasoning | 0.5625 | 0.15 | 3/4 |
| gct-agentic-004 | agentic | 1 | 0.45 | 4/4 |
| gct-research-002 | research | 0.55 | 0 | 4/4 |

## Failure Modes

False positives usually mean the measured answer contains branch/action language without enough task-specific keyword coverage. False negatives mean the answer can satisfy the task tersely without explicit commitment markers.
