# Leakage Audit

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Timing Classification

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

## Clean Predictor Sets

- Initial-route clean set: `K`, `rho`, `A1_exists`, `context_budget`, task/repository/model identifiers only if converted to frozen priors.
- Post-retrieval pre-generation clean set: initial-route set plus `A2_retrieved` and `A3_surfaced`.
- Removed from pre-run prediction: `A`, `A4_understood`, `A5_linked_to_action`, `Actionability`, `E9`, `referenced_files`, `edited_files`, `tests_or_verifiers`, and any same-run success/validation/error/latency fields.

## Verdict

The strongest retrospective accessibility gain is contaminated. `A4_understood` and `A5_linked_to_action` directly observe generated behavior. `K` and `rho` are not post-run traces for the target row when frozen, but they are historical outcome priors, so they test stability of past performance rather than a purely structural theory.
