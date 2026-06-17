# Execution Path Dependence

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Pre-Run Versus Execution Information

| information set | fields | retrospective R2 | holdout R2 | prospective reconstructed R2 | prospective Brier gain |
| --- | --- | --- | --- | --- | --- |
| strict pre-run measured variables | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files | 0.507582 | 0.406068 | 0.0 | -0.005365 |
| post-retrieval pre-generation variables | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files, A2_retrieved, A3_surfaced | 0.508699 | 0.397847 | 0.0 | -0.009789 |
| all catalogued pre-run proxies | A1_exists, K, benchmark_novelty, context_budget, context_completeness, context_mismatch, domain_familiarity, evidence_scarcity, expected_files, model_calibration_history, old_A, planning_depth, relevant_files, retrieval_difficulty, rho, route_confidence, specialization_alignment, task_ambiguity, task_complexity | 0.522119 | 0.551962 | 0.0 | -0.01326 |
| execution/post-run diagnostics | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files, A2_retrieved, A3_surfaced, A4_understood, A5_linked_to_action, E9, referenced_files, edited_files, tests_or_verifiers | 0.630704 | 0.605473 | 0.0 | 0.0 |

Estimated additional variance visible only after retrieval/generation/action traces: `0.207626` R2 in holdout and `0` R2 in reconstructed prospective scoring.

## Prospective Residual Clusters

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
| error_type | calibration_error | 48 | -0.343355 | 0.059605 | 0.343355 |

## Interpretation

The run itself creates observables that are strongly related to success: whether decisive evidence was surfaced, understood, linked to action, referenced, edited, and verified. Those are not valid initial predictors. They explain why retrospective models looked powerful and why prospective models fail when restricted to information available before execution.
