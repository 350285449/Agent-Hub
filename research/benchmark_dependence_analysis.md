# Benchmark Dependence Analysis

## Property Effects

Correlations are computed across the 12 benchmark means. Trajectory shape uses the existing trajectory-compatible readout `grounding density - evidence-to-action latency`; it is not a new invariant metric.

| rank | property | effect on grounding | effect on commitment | effect on trajectory shape | effect on GAR gap | rank score |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | retrieval_burden | -0.918991 | 0.496819 | -0.842107 | 0.205111 | 2.463028 |
| 2 | novelty | -0.957844 | 0.377022 | -0.938807 | 0.135661 | 2.409334 |
| 3 | branching_factor | -0.844996 | 0.463295 | -0.787064 | 0.186101 | 2.281456 |
| 4 | evidence_density | 0.892792 | -0.309593 | 0.91254 | -0.053635 | 2.168559 |
| 5 | ambiguity | -0.885062 | 0.288289 | -0.83875 | -0.035415 | 2.047516 |
| 6 | planning_depth | -0.525273 | 0.652358 | -0.410672 | 0.407044 | 1.995347 |
| 7 | verification_burden | -0.47123 | 0.043569 | -0.48502 | 0.045109 | 1.044928 |
| 8 | tool_dependence | -0.160659 | 0.529298 | 0.05714 | 0.1484 | 0.895497 |

## Contributor Ranking

1. Retrieval burden and ambiguity are the main suppressors: they lower mean grounding and delay evidence-action linkage.
2. Evidence density is the main stabilizer: dense evidence raises GAR, lowers latency, and makes action grounding easier to preserve.
3. Tool dependence and branching factor reshape commitment: they push commitment later and make trajectories path-dependent even when GAR is adequate.
4. Planning depth matters most when paired with branching; by itself it does not destroy the invariant, as shown by constraint-planning and proof-check.

## Dependence Mechanism

Benchmark dependence appears when the benchmark changes when decisive evidence becomes available and how many plausible actions remain live after evidence appears. GAR is strongest when evidence is early, local, and checkable. It weakens when evidence is sparse, distributed, or only becomes meaningful after a retrieval or recovery sequence.
