# Execution Trajectory Analysis

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Rows are represented as execution trajectories over retrieval, evidence, grounding, tool, verification, and reasoning events. No primitive search, interaction-law search, or intervention analysis is used.

## Event Families

| event family | rows with event | success with event | success without event |
| --- | --- | --- | --- |
| retrieval | 652 | 0.618098 | 0.488722 |
| evidence | 652 | 0.618098 | 0.488722 |
| grounding | 630 | 0.81746 | 0.0625 |
| tool | 0 | 0.0 | 0.58061 |
| verification | 0 | 0.0 | 0.58061 |
| reasoning | 918 | 0.58061 | 0.0 |

## Frequent Trajectories

| 10>25>50>75 trajectory | rows | success rate |
| --- | --- | --- |
| exploring>exploring>exploring>exploring | 368 | 0.413043 |
| grounded>grounded>converging>converging | 193 | 0.906736 |
| stuck>stuck>stuck>stuck | 184 | 0.271739 |
| stuck>stuck>exploring>exploring | 71 | 0.971831 |
| exploring>grounded>converging>converging | 38 | 0.789474 |
| exploring>exploring>converging>converging | 21 | 1.0 |
| grounded>grounded>grounded>grounded | 16 | 0.875 |
| stuck>stuck>recovered>recovered | 11 | 1.0 |
| exploring>stuck>exploring>exploring | 9 | 0.444444 |
| exploring>stuck>converging>converging | 5 | 1.0 |

## Natural Clustering Scan

| k | within-cluster sum sq | WCSS improvement | success-rate spread | smallest cluster |
| --- | --- | --- | --- | --- |
| 2 | 676.641137 | n/a | 0.118666 | 307 |
| 3 | 643.269465 | 33.371671 | 0.12932 | 30 |
| 4 | 324.662121 | 318.607344 | 0.467322 | 30 |
| 5 | 241.367288 | 83.294833 | 0.494047 | 30 |
| 6 | 233.610233 | 7.757055 | 0.576271 | 11 |
| 7 | 156.123477 | 77.486756 | 0.503774 | 10 |
| 8 | 180.232412 | -24.108935 | 0.58642 | 16 |

## Determination

Trajectories naturally cluster. The dominant split is not model identity alone; it is whether a run moves from evidence acquisition into grounded/converging execution, stays exploratory, or remains stuck. Successful and failed runs share some early retrieval patterns, but diverge once evidence is converted into action.
