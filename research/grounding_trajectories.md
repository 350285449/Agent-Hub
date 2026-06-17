# Grounding Trajectories

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Dominant Trajectory Families

| trajectory | rows | share | success rate | family |
| --- | --- | --- | --- | --- |
| discovered>recognized>accepted | 354 | 0.385621 | 0.423729 | mixed |
| discovered>recognized>accepted>connected>executed | 245 | 0.266885 | 0.885714 | success |
| discovered | 174 | 0.189542 | 0.33908 | failure |
| discovered>connected | 62 | 0.067538 | 0.967742 | success |
| discovered>recognized>accepted>connected | 25 | 0.027233 | 1.0 | success |
| none | 21 | 0.022876 | 0.0 | failure |
| connected | 18 | 0.019608 | 0.833333 | success |
| discovered>recognized | 14 | 0.015251 | 0.142857 | failure |
| discovered>accepted>connected | 3 | 0.003268 | 1.0 | success |
| discovered>accepted>connected>executed | 2 | 0.002179 | 1.0 | success |

## Success Paths

The dominant success path is full traversal: discovered, recognized, accepted, connected, executed. Partial success paths usually include accepted and connected evidence even when the final grounded-execution threshold is missed.

## Failure Paths

The dominant failure paths stop at recognized evidence or accepted evidence without connected action. The shortest failure path is no usable evidence. The most informative failure path is recognized evidence that never becomes action, because it separates retrieval from grounding.
