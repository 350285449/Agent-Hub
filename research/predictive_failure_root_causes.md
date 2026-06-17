# Predictive Failure Root Causes

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Variance Attribution

| information set | fields | retrospective R2 | holdout R2 | prospective reconstructed R2 | prospective Brier gain |
| --- | --- | --- | --- | --- | --- |
| strict pre-run measured variables | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files | 0.507582 | 0.406068 | 0.0 | -0.005365 |
| post-retrieval pre-generation variables | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files, A2_retrieved, A3_surfaced | 0.508699 | 0.397847 | 0.0 | -0.009789 |
| all catalogued pre-run proxies | A1_exists, K, benchmark_novelty, context_budget, context_completeness, context_mismatch, domain_familiarity, evidence_scarcity, expected_files, model_calibration_history, old_A, planning_depth, relevant_files, retrieval_difficulty, rho, route_confidence, specialization_alignment, task_ambiguity, task_complexity | 0.522119 | 0.551962 | 0.0 | -0.01326 |
| execution/post-run diagnostics | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files, A2_retrieved, A3_surfaced, A4_understood, A5_linked_to_action, E9, referenced_files, edited_files, tests_or_verifiers | 0.630704 | 0.605473 | 0.0 | 0.0 |

## Root Causes

| cause | evidence | contribution |
| --- | --- | --- |
| execution-path dependence | execution diagnostics add 0.207626 holdout R2 and 0 prospective reconstructed R2 beyond post-retrieval variables | major for explaining outcomes, not admissible for pre-run prediction |
| benchmark noise | repeated-cell outcome dispersion remains visible in same model/repo/category/context cells | material measurement floor |
| distribution shift | holdout R2 is much larger than prospective reconstructed R2 for every clean information set | major |
| task-family heterogeneity | coding, reasoning, research, and agentic slices change achievable R2 and transfer behavior | major |
| measurement limits | strict pre-run variables explain far less prospectively than in retrospective/holdout checks | major |
| calibration limits | best clean prospective Brier gains are small and do not support confident probability forecasts | major |
| predictor instability | K/rho/history-heavy predictors transfer poorly into narrow future panels | major |

## Benchmark Noise Cells

| cell | rows | success rate | outcome sd |
| --- | --- | --- | --- |
| nemotron-3-super:cloud / ytdl_site / bug_fix / historical / 100.0 | 4 | 0.5 | 0.5 |
| nemotron-3-super:cloud / Agent-Hub / analysis / prospective / 25.0 | 4 | 0.5 | 0.5 |
| nemotron-3-super:cloud / Agent-Hub / bug_fix / historical / 25.0 | 30 | 0.533333 | 0.498888 |
| nemotron-3-super:cloud / Agent-Hub / bug_fix / historical / 50.0 | 30 | 0.466667 | 0.498888 |
| nemotron-3-super:cloud / Agent-Hub / bug_fix / historical / 100.0 | 30 | 0.433333 | 0.495536 |
| nemotron-3-super:cloud / Agent-Hub / bug_fix / historical / 0.0 | 30 | 0.333333 | 0.471405 |
| gemma4:31b-cloud / Agent-Hub / bug_fix / unmatched_evidence_access / 25.0 | 3 | 0.666667 | 0.471405 |
| nemotron-3-super:cloud / Agent-Hub / bug_fix / unmatched_evidence_access / 0.0 | 3 | 0.666667 | 0.471405 |
| nemotron-3-super:cloud / ytdl_site / bug_fix / historical / 25.0 | 3 | 0.666667 | 0.471405 |
| nemotron-3-super:cloud / ytdl_site / bug_fix / historical / 50.0 | 3 | 0.666667 | 0.471405 |
| nemotron-3-super:cloud / ytdl_site / bug_fix / historical / 75.0 | 3 | 0.333333 | 0.471405 |
| gemma4:31b-cloud / ytdl_site / refactor / historical / 0.0 | 3 | 0.666667 | 0.471405 |

## Verdict

The failures are not explained by one missing variable. The main pattern is a gap between explanatory reconstruction and future-outcome prediction: pre-run information is too coarse, task-family transfer is unstable, and substantial signal appears only after execution begins or after output exists.
