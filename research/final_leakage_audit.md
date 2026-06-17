# Final Leakage Audit

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Contamination Map

| variable | role | timing class | lineage | leakage verdict |
| --- | --- | --- | --- | --- |
| success | target | post-run | outcome | never a predictor |
| K | predictor | pre-run if frozen from past rows | historical outcome prior | clean only with leave-future-out freezing; not structural |
| rho | predictor | pre-run if frozen from past rows | historical model/category excess prior | high circularity risk; unstable under new cells |
| A | predictor | mixed | aggregate evidence access | contaminated by E6/E9-style post-generation traces |
| old_A | predictor | pre-run | context volume/budget proxy | clean but weak and coarse |
| A1_exists | predictor | pre-run | benchmark/task label existence | clean if task labels are not inferred from output |
| A2_retrieved | predictor | during-run pre-generation | retrieved/selected evidence coverage | clean for post-retrieval forecast; unavailable for initial route |
| A3_surfaced | predictor | during-run pre-generation | context surfacing/token allocation | clean for post-retrieval forecast; unavailable for initial route |
| A4_understood | predictor | post-run | output referenced decisive evidence | contaminated; remove from predictive models |
| A5_linked_to_action | predictor | post-run | E9/output action link | contaminated; remove from predictive models |
| Actionability | predictor | mixed/post-run in current aligned data | A1-A10 actionability score | not admitted unless decomposed into pre-run components |
| E9 | predictor | post-run | generated-output evidence/action diagnostic | leaky for pre-run prediction |
| referenced_files | predictor | post-run | files named in generated output | leaky |
| edited_files | predictor | post-run | files changed by the run | leaky |
| tests_or_verifiers | predictor | post-run | tests/verifiers triggered | leaky |
| context_budget | predictor | pre-run | planned context budget | clean but weak alone |
| context_tokens | predictor | during-run pre-generation | assembled context size | clean only after context assembly |
| selected_file_count | predictor | during-run pre-generation | retrieved file count | clean only after retrieval |
| expected_files | predictor | pre-run | benchmark/task label | clean if label source is task-side |
| relevant_files | predictor | pre-run | benchmark/task label | clean if label source is task-side |
| Route Friction | predictor | pre-run if frozen | route prior/cost proxy | historical outcome prior; not a new primitive |
| Retrieval Selectivity | predictor | during-run pre-generation | access/retrieval proxy | depends on A implementation |
| Compatibility v2 | predictor | pre-run if frozen | historical compatibility score | success-prior contamination risk |
| EAC | predictor | mixed | evidence-access compatibility | depends on A timing |

## Leakage Graph

`task/benchmark labels -> A1/expected/relevant/context_budget -> clean pre-run prediction`

`retrieval/context assembly -> A2/A3/context_tokens/selected_file_count -> post-retrieval pre-generation prediction`

`generation/output/actions -> A4/A5/E9/referenced_files/edited_files/tests -> contaminated diagnostic prediction`

`past outcomes -> K/rho/Compatibility/Route Friction/model calibration -> frozen historical priors`

`same-run outcome -> success/validation/error fields -> target only`

## Variable Lineage Graph

| family | variables | lineage | admitted use |
| --- | --- | --- | --- |
| capability priors | K, model_calibration_history | leave-future-out historical cloud outcomes | pre-run only if frozen before target row |
| specialization priors | rho, specialization_alignment | historical model/category residuals | pre-run only if frozen; not structural proof |
| clean accessibility | A1, expected_files, relevant_files, context_budget, old_A | task labels and planned budget | initial prediction |
| post-retrieval accessibility | A2, A3, selected_file_count, context_tokens | retrieval/context assembly | forecast after retrieval, before generation |
| post-run diagnostics | A4, A5, E9, referenced_files, edited_files, tests | generated output and actions | diagnosis only |
| mixed composites | A, Actionability, EAC, Compatibility v2 | blend of priors/access/output-adjacent traces | not primitive without decomposition |

## Confidence Rating

High confidence: A4/A5/E9/referenced/edited/tests are contaminated for pre-run prediction. Moderate confidence: K/rho are admissible only as frozen historical priors. Moderate confidence: A1/context budget/task labels are clean but weak. Low confidence: discovered prompt/task proxies are under-instrumented and require frozen prospective collection.
