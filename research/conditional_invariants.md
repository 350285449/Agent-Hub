# Conditional Invariants

Conditioning tests use the requested benchmark properties only. A cell is stronger when the aggregate GAR success gap is positive and most benchmark members have positive benchmark-level gaps. All-success benchmark cells count as non-estimable, not as negative evidence.

| property | class | benchmarks | rows | mean GAR | GAR success gap | positive benchmark gaps | estimable cells |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ambiguity | low | api-compat, test-generation, patch-defect, proof-check, constraint-planning, tool-sequence | 72 | 0.634157 | 0.109795 | 4/6 | 4 |
| ambiguity | medium | counterexample, route-repair | 24 | 0.565589 | 0.027476 | 2/2 | 2 |
| ambiguity | high | claim-audit, evidence-synthesis, source-triangulation, workflow-recovery | 48 | 0.524768 | 0.036289 | 4/4 | 4 |
| planning_depth | low | api-compat | 12 | 0.675211 | 0 | 0/1 | 0 |
| planning_depth | medium | test-generation, patch-defect, claim-audit | 36 | 0.619211 | 0.131684 | 2/3 | 2 |
| planning_depth | high | proof-check, constraint-planning, counterexample, evidence-synthesis, source-triangulation, route-repair, tool-sequence, workflow-recovery | 96 | 0.562793 | 0.065703 | 8/8 | 8 |
| evidence_density | low | source-triangulation | 12 | 0.495953 | 0.010272 | 1/1 | 1 |
| evidence_density | medium | counterexample, claim-audit, evidence-synthesis, workflow-recovery | 48 | 0.541373 | 0.045925 | 4/4 | 4 |
| evidence_density | high | api-compat, test-generation, patch-defect, proof-check, constraint-planning, route-repair, tool-sequence | 84 | 0.624821 | 0.097606 | 5/7 | 5 |
| retrieval_burden | low | api-compat, test-generation, patch-defect, proof-check, constraint-planning, counterexample | 72 | 0.633496 | 0.076637 | 4/6 | 4 |
| retrieval_burden | medium | route-repair, tool-sequence | 24 | 0.567571 | 0.088212 | 2/2 | 2 |
| retrieval_burden | high | claim-audit, evidence-synthesis, source-triangulation, workflow-recovery | 48 | 0.524768 | 0.036289 | 4/4 | 4 |

## Determination

Conditional invariants are visible but not strong enough to upgrade the overall verdict. GAR is most stable in low-ambiguity, high-evidence-density, and low-retrieval classes. It becomes weaker in high ambiguity and high retrieval classes, where the same action can be grounded or ungrounded depending on whether the run found the right evidence before committing.

The important result is explanatory control, not universality: once benchmarks are grouped by evidence density and retrieval burden, the direction of GAR becomes more coherent. It still does not become a benchmark-independent law because some classes contain ceiling cells and others contain sparse-evidence cells with very small benchmark gaps.
