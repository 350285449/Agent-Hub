# Universality Boundary

## Where Invariants Hold

GAR holds directionally across task families and cloud model families. Inside benchmark classes, it is most reliable under these conditions:

1. Evidence is explicit or locally recoverable.
2. Retrieval burden is low to medium.
3. Ambiguity is low enough that evidence maps to a small action set.
4. Verification arrives before or near the commitment point.

## Where Invariants Break

GAR breaks or becomes weak under these conditions:

1. All-success ceiling benchmarks: `api-compat` and `test-generation` have high GAR but no estimable success/failure gap.
2. Sparse-evidence research benchmarks: `source-triangulation` and parts of `evidence-synthesis` reduce GAR and compress success/failure separation.
3. Recovery-heavy agentic benchmarks: `workflow-recovery` and `route-repair` shift commitment later and make trajectory shape dominate the scalar GAR readout.
4. High-branch search tasks: `counterexample` weakens because multiple plausible branches can remain evidence-compatible until late.

## Boundary Conditions

The universality boundary is not model family and not task family. It is benchmark structure: evidence availability, retrieval burden, and branch pressure. GAR is a weak invariant of execution when evidence is available early enough to govern action. It is not universal when benchmark design separates evidence discovery from action selection.
