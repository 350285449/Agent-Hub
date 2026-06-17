# Intervention Robustness

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Recovery estimates were recomputed under pessimistic, realistic, optimistic, and ceiling assumptions. Candidate failures are restricted to grounding-begun weak-integrity failures; pessimistic/realistic scenarios further require warning detectability.

| scenario | candidate failed rows | intervention reach | target success after repair | prevented rows | share of all failures |
| --- | --- | --- | --- | --- | --- |
| pessimistic | 216 | 0.4 | 0.55 | 47.5 | 0.123429 |
| realistic | 216 | 0.65 | 0.896296 | 125.8 | 0.326857 |
| optimistic | 216 | 0.85 | 0.946296 | 173.7 | 0.451273 |
| ceiling | 216 | 1.0 | 0.98 | 211.7 | 0.549818 |

## Determination

The recovery estimate is robust if the realistic row remains near the prior central estimate and the pessimistic row remains nontrivial. The ceiling row is not a deployment forecast; it is the maximum implied by the current corpus under perfect repair assumptions.
