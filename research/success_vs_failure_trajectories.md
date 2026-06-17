# Success vs Failure Trajectories

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Core Trajectory Metrics

| outcome | rows | decisive evidence timing | grounding latency | grounded-action ratio | evidence-to-action latency | grounded execution rate | grounding score |
| --- | --- | --- | --- | --- | --- | --- | --- |
| success | 533 | 0.360225 | 0.360225 | 0.496622 | 0.384615 | 0.410882 | 0.526595 |
| failure | 385 | 0.477532 | 0.477532 | 0.098376 | 0.480909 | 0.072727 | 0.31625 |

## Dominant Trajectory Families

| trajectory | rows | success rate | decisive evidence timing | grounded-action ratio | evidence-to-action latency |
| --- | --- | --- | --- | --- | --- |
| discovered>recognized>accepted | 354 | 0.423729 | 0.136864 | 0.092332 | 0.815113 |
| discovered>recognized>accepted>connected>executed | 245 | 0.885714 | 0.123265 | 0.702573 | 0.380816 |
| discovered | 174 | 0.33908 | 1.0 | 0.118102 | 0.0 |
| discovered>connected | 62 | 0.967742 | 0.991935 | 0.525874 | 0.0 |
| discovered>recognized>accepted>connected | 25 | 1.0 | 0.308 | 0.850188 | 0.312 |
| none | 21 | 0.0 | 1.0 | 0.0 | 0.0 |
| connected | 18 | 0.833333 | 0.916667 | 0.931217 | 0.0 |
| discovered>recognized | 14 | 0.142857 | 1.0 | 0.153513 | 0.0 |
| discovered>accepted>connected | 3 | 1.0 | 0.5 | 0.986014 | 0.0 |
| discovered>accepted>connected>executed | 2 | 1.0 | 0.5 | 0.740385 | 0.25 |

## Measurement

Successful trajectories find decisive evidence earlier, ground earlier, keep a higher grounded-action ratio, and convert evidence to action faster. Failure trajectories often reach `discovered>recognized>accepted`, but do not reach `connected>executed`.
