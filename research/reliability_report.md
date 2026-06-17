# Reliability Report

Reliability combines split stability by model/repository, bootstrap correlation stability, and sensitivity across dataset/model splits. It is an audit heuristic, not a fitted theory.

| variable | rows | corr | 95% bootstrap corr CI | AUC | single-var R2 | reliability | reliability-adjusted importance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| K | 1091 | 0.671252 | [0.63, 0.71] | 0.757126 | 0.450579 | 0.751 | 0.504 |
| Route Friction | 1039 | 0.671519 | [0.629, 0.705] | 0.792919 | 0.450938 | 0.732 | 0.492 |
| Compatibility v2 | 1039 | 0.65819 | [0.623, 0.691] | 0.870389 | 0.433214 | 0.725 | 0.477 |
| rho | 1091 | 0.650075 | [0.608, 0.688] | 0.854113 | 0.422598 | 0.69 | 0.449 |
| A | 1091 | 0.249122 | [0.19, 0.303] | 0.677463 | 0.062062 | 0.582 | 0.145 |
| Retrieval Selectivity | 1039 | 0.127864 | [0.074, 0.186] | 0.579889 | 0.016349 | 0.587 | 0.075 |
| Hidden Curriculum | 0 | not measured | n/a | not measured | not measured | 0.0 | 0.0 |
| Search Landscape | 0 | not measured | n/a | not measured | not measured | 0.0 | 0.0 |

Findings:

- K remains the strongest primitive-like variable, but its reliability is limited by outcome-derived measurement.
- rho survives as useful signal but is the least clean primitive because it aliases K and uses coarse task categories.
- A is cleaner than K/rho in timing for E1-E5, but weaker because evidence use is not fully pre-run observable.
- Hidden Curriculum and Search Landscape have no stable operational measurement in the current corpus; they should not be ranked as surviving variables.
