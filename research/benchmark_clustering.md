# Benchmark Clustering

## Benchmark Families

| family | benchmarks | structural signature |
| --- | --- | --- |
| deterministic conformance/build | api-compat, test-generation, patch-defect | dense explicit evidence; low ambiguity; strong verification |
| formal/constraint reasoning | proof-check, constraint-planning, counterexample | internal evidence; high planning or search pressure |
| open research evidence | claim-audit, evidence-synthesis, source-triangulation | high ambiguity and retrieval burden; sparse decisive evidence |
| agentic workflow control | tool-sequence, route-repair, workflow-recovery | high tool dependence; branch and recovery dynamics dominate |

## Benchmark Archetypes

| benchmark | archetype |
| --- | --- |
| api-compat | deterministic interface conformance |
| claim-audit | claim verification |
| constraint-planning | constraint satisfaction |
| counterexample | adversarial search |
| evidence-synthesis | multi-source synthesis |
| patch-defect | localized repair |
| proof-check | formal verification |
| route-repair | state repair |
| source-triangulation | evidence discovery |
| test-generation | deterministic artifact construction |
| tool-sequence | ordered tool execution |
| workflow-recovery | recovery and rerouting |

## Similarity Graph

Edges below connect each benchmark to its two nearest neighbors in the eight-property structure space.

| benchmark | nearest | distance | second nearest | distance |
| --- | --- | --- | --- | --- |
| api-compat | test-generation | 2.44949 | patch-defect | 2.828427 |
| claim-audit | evidence-synthesis | 1.414214 | source-triangulation | 2.645751 |
| constraint-planning | counterexample | 2.44949 | patch-defect | 3.162278 |
| counterexample | constraint-planning | 2.44949 | evidence-synthesis | 3.162278 |
| evidence-synthesis | claim-audit | 1.414214 | workflow-recovery | 2.44949 |
| patch-defect | test-generation | 1.414214 | route-repair | 2.44949 |
| proof-check | constraint-planning | 3.162278 | api-compat | 3.741657 |
| route-repair | tool-sequence | 1.414214 | patch-defect | 2.44949 |
| source-triangulation | claim-audit | 2.645751 | evidence-synthesis | 2.645751 |
| test-generation | patch-defect | 1.414214 | api-compat | 2.44949 |
| tool-sequence | route-repair | 1.414214 | patch-defect | 2.828427 |
| workflow-recovery | evidence-synthesis | 2.44949 | route-repair | 2.44949 |

## Interpretation

The graph separates into four useful benchmark classes rather than four simple task families. `source-triangulation` and `workflow-recovery` sit near the break boundary because both combine ambiguity, retrieval pressure, and branching, even though one is research and the other is agentic. That cross-family structural similarity is the main reason task-family transfer can pass while benchmark transfer still fails.
