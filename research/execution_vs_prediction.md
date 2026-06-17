# Execution Versus Prediction

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Evidence Table

| window | fields | retrospective R2 | holdout R2 | holdout Brier gain | prospective R2 | prospective Brier gain |
| --- | --- | --- | --- | --- | --- | --- |
| pre-run | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files | 0.507582 | 0.406068 | 0.090805 | 0.0 | -0.005365 |
| during execution | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files, A2_retrieved, A3_surfaced | 0.508699 | 0.397847 | 0.088966 | 0.0 | -0.009789 |
| post-run diagnostic | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files, A2_retrieved, A3_surfaced, A4_understood, A5_linked_to_action, E9, referenced_files, edited_files, tests_or_verifiers | 0.630704 | 0.605473 | 0.135396 | 0.051793 | 0.009415 |
| all catalogued pre-run proxies | A1_exists, K, benchmark_novelty, context_budget, context_completeness, context_mismatch, domain_familiarity, evidence_scarcity, expected_files, model_calibration_history, old_A, planning_depth, relevant_files, retrieval_difficulty, rho, route_confidence, specialization_alignment, task_ambiguity, task_complexity | 0.522119 | 0.551962 | 0.123429 | 0.0 | -0.01326 |

## Benchmark Noise

| cell | rows | success rate | outcome sd |
| --- | --- | --- | --- |
| nemotron-3-super:cloud / ytdl_site / bug_fix / 100.0 | 4 | 0.5 | 0.5 |
| nemotron-3-super:cloud / Agent-Hub / bug_fix / 25.0 | 30 | 0.533333 | 0.498888 |
| nemotron-3-super:cloud / Agent-Hub / bug_fix / 50.0 | 30 | 0.466667 | 0.498888 |
| nemotron-3-super:cloud / Agent-Hub / bug_fix / 100.0 | 30 | 0.433333 | 0.495536 |
| nemotron-3-super:cloud / face / testing / 25.0 | 5 | 0.6 | 0.489898 |
| nemotron-3-super:cloud / Agent-Hub / analysis / 25.0 | 5 | 0.6 | 0.489898 |
| nemotron-3-super:cloud / ytdl_site / analysis / 0.0 | 5 | 0.4 | 0.489898 |
| nemotron-3-super:cloud / ytdl_site / analysis / 25.0 | 5 | 0.4 | 0.489898 |
| nemotron-3-super:cloud / face / analysis / 25.0 | 5 | 0.4 | 0.489898 |
| nemotron-3-super:cloud / Agent-Hub / bug_fix / 0.0 | 33 | 0.363636 | 0.481046 |
| nemotron-3-super:cloud / ytdl_site / bug_fix / 25.0 | 3 | 0.666667 | 0.471405 |
| nemotron-3-super:cloud / ytdl_site / bug_fix / 50.0 | 3 | 0.666667 | 0.471405 |

## Direct Answers

1. Useful signal first appears before execution, but only weakly and unreliably for future prediction.
2. Prediction is currently limited before execution because the strongest variables are historical priors or later execution traces.
3. Agent outcomes are primarily execution-driven in the evidence: post-run diagnostic R2 exceeds pre-run holdout R2 by `0.199405`.
4. Full execution traces dominate pre-run variables for explanation; retrieval-stage variables alone do not. They do not become admissible initial predictors merely because they explain outcomes.

## Operational Consequence

Agent-Hub should spend less effort promising exact pre-run success probabilities and more effort measuring live execution state, detecting divergence early, and adapting while the run is still recoverable.
