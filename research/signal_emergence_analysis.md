# Signal Emergence Analysis

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Direct Comparison

| window | fields | retrospective R2 | holdout R2 | holdout Brier gain | prospective R2 | prospective Brier gain |
| --- | --- | --- | --- | --- | --- | --- |
| pre-run | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files | 0.507582 | 0.406068 | 0.090805 | 0.0 | -0.005365 |
| during execution | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files, A2_retrieved, A3_surfaced | 0.508699 | 0.397847 | 0.088966 | 0.0 | -0.009789 |
| post-run diagnostic | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files, A2_retrieved, A3_surfaced, A4_understood, A5_linked_to_action, E9, referenced_files, edited_files, tests_or_verifiers | 0.630704 | 0.605473 | 0.135396 | 0.051793 | 0.009415 |
| all catalogued pre-run proxies | A1_exists, K, benchmark_novelty, context_budget, context_completeness, context_mismatch, domain_familiarity, evidence_scarcity, expected_files, model_calibration_history, old_A, planning_depth, relevant_files, retrieval_difficulty, rho, route_confidence, specialization_alignment, task_ambiguity, task_complexity | 0.522119 | 0.551962 | 0.123429 | 0.0 | -0.01326 |

## Where Signal First Appears

Weak useful signal appears before execution through `K`, `rho`, task labels, planned context, and historical priors. It is useful for rough stratification, not reliable probability prediction.

Retrieval/context assembly adds little stable holdout signal by itself in this pass. The first material increase appears by the end of execution, when evidence-use and action traces are visible.

## Prospective Failure Clusters

| axis | cluster | rows | mean residual | residual sd | mean abs error |
| --- | --- | --- | --- | --- | --- |
| error_type | false_negative | 16 | 0.621734 | 0.055148 | 0.621734 |
| error_type | false_positive | 3 | -0.507299 | 0.0 | 0.507299 |
| category | bug_fix | 3 | -0.507299 | 0.0 | 0.507299 |
| category | analysis | 20 | 0.030569 | 0.507217 | 0.500242 |
| repository | face | 21 | -0.222384 | 0.40662 | 0.454038 |
| repository | ytdl_site | 18 | 0.00314 | 0.464542 | 0.434667 |
| context_budget |  | 34 | -0.14737 | 0.419172 | 0.4285 |
| context_budget | 50.0 | 3 | 0.051355 | 0.471405 | 0.427326 |
| model | nemotron-3-super:cloud | 67 | -0.120227 | 0.420847 | 0.417175 |
| context_budget | 25.0 | 30 | -0.106623 | 0.412591 | 0.403324 |
| category | refactor | 13 | -0.173221 | 0.379727 | 0.392649 |
| repository | Agent-Hub | 28 | -0.122917 | 0.378751 | 0.378282 |
| category | testing | 21 | -0.130401 | 0.369533 | 0.3694 |
| category | architecture | 10 | -0.215439 | 0.307469 | 0.35621 |

## Answer

Prediction is fundamentally limited before execution under the current variable family. The limitation is empirical, not philosophical: pre-run holdout looks respectable, but prospective transfer collapses. Signal becomes reliable when the execution path starts revealing whether the agent found and used the right evidence.
