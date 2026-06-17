# Execution Science

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Timing Windows

| window | fields | retrospective R2 | holdout R2 | holdout Brier gain | prospective R2 | prospective Brier gain |
| --- | --- | --- | --- | --- | --- | --- |
| pre-run | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files | 0.507582 | 0.406068 | 0.090805 | 0.0 | -0.005365 |
| during execution | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files, A2_retrieved, A3_surfaced | 0.508699 | 0.397847 | 0.088966 | 0.0 | -0.009789 |
| post-run diagnostic | K, rho, A1_exists, old_A, context_budget, expected_files, relevant_files, A2_retrieved, A3_surfaced, A4_understood, A5_linked_to_action, E9, referenced_files, edited_files, tests_or_verifiers | 0.630704 | 0.605473 | 0.135396 | 0.051793 | 0.009415 |
| all catalogued pre-run proxies | A1_exists, K, benchmark_novelty, context_budget, context_completeness, context_mismatch, domain_familiarity, evidence_scarcity, expected_files, model_calibration_history, old_A, planning_depth, relevant_files, retrieval_difficulty, rho, route_confidence, specialization_alignment, task_ambiguity, task_complexity | 0.522119 | 0.551962 | 0.123429 | 0.0 | -0.01326 |

## Result

The useful explanatory signal is not concentrated before execution. Initial pre-run variables explain `0.406068` holdout R2. Post-retrieval execution variables explain `0.397847` holdout R2, which does not beat the pre-run set in this corpus. Full post-run diagnostics explain `0.605473` holdout R2.

Execution/post-run observables add `0.199405` holdout R2 over the pre-run set. The best clean prospective pre-run R2 remains `0` in this reconstructed cloud-only panel.

## Interpretation

Agent success is not primarily fixed before the run. The run creates decisive observables: evidence retrieval, evidence surfacing, whether evidence is understood, whether it is linked to action, file references, edits, and verifiers. Some of these are available during execution; the strongest are only diagnostic after output exists.

## Classification

Agent-Hub should become `C. Execution Science`: a system for instrumenting, steering, and diagnosing the execution process. Pure predictive science is too strong; diagnostic science is too passive.
