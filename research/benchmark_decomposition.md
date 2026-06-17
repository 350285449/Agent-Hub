# Benchmark Decomposition

Scope: 144 frozen cloud-only rows from `fresh_invariant_tournament_runs.jsonl`. No local/self-hosted rows, primitive search, intervention study, or new Grounding Integrity metric is used. Property scores are ordinal benchmark-structure annotations on a 1-5 scale, where 1 is low and 5 is high.

## Benchmark Measures

| benchmark | family | archetype | ambiguity | evidence density | retrieval burden | planning depth | verification burden | branching factor | tool dependence | novelty | mean GAR | GAR gap | success rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| route-repair | agentic | state repair | 3 | 4 | 3 | 4 | 4 | 4 | 5 | 3 | 0.568808 | 0.025056 | 0.833333 |
| tool-sequence | agentic | ordered tool execution | 2 | 4 | 3 | 5 | 4 | 4 | 5 | 3 | 0.566335 | 0.136079 | 0.75 |
| workflow-recovery | agentic | recovery and rerouting | 4 | 3 | 4 | 5 | 4 | 5 | 5 | 4 | 0.546059 | 0.010251 | 0.666667 |
| api-compat | coding | deterministic interface conformance | 1 | 5 | 1 | 2 | 3 | 2 | 3 | 1 | 0.675211 | 0 | 1 |
| patch-defect | coding | localized repair | 2 | 4 | 2 | 3 | 4 | 3 | 4 | 2 | 0.659667 | 0.061351 | 0.833333 |
| test-generation | coding | deterministic artifact construction | 2 | 5 | 1 | 3 | 4 | 3 | 4 | 2 | 0.6708 | 0 | 1 |
| constraint-planning | reasoning | constraint satisfaction | 2 | 4 | 2 | 5 | 4 | 4 | 2 | 3 | 0.591522 | 0.079695 | 0.833333 |
| counterexample | reasoning | adversarial search | 3 | 3 | 2 | 4 | 4 | 5 | 1 | 4 | 0.562371 | 0.028347 | 0.75 |
| proof-check | reasoning | formal verification | 1 | 4 | 1 | 4 | 5 | 2 | 1 | 2 | 0.641404 | 0.009869 | 0.916667 |
| claim-audit | research | claim verification | 4 | 3 | 4 | 3 | 5 | 4 | 3 | 4 | 0.527166 | 0.072508 | 0.333333 |
| evidence-synthesis | research | multi-source synthesis | 4 | 3 | 4 | 4 | 4 | 4 | 3 | 4 | 0.529895 | 0.051616 | 0.416667 |
| source-triangulation | research | evidence discovery | 5 | 2 | 5 | 4 | 5 | 5 | 4 | 5 | 0.495953 | 0.010272 | 0.5 |

## Readout

The strongest invariant candidate weakens at the benchmark layer because benchmark structure changes the opportunity for grounded action. Deterministic coding tasks are evidence-dense and low ambiguity, so GAR is high but sometimes uninformative because every run succeeds. Research and recovery tasks expose sparse, distributed, or late-arriving evidence; GAR remains directionally useful but its gap narrows or depends on trajectory timing.
