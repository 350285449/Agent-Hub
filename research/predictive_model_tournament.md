# Predictive Model Tournament

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Retrospective

| model | features | rows | corr | AUC | Brier | R2 |
| --- | --- | --- | --- | --- | --- | --- |
| Model A: K | K | 918 | 0.692927 | 0.723925 | 0.12647 | 0.480148 |
| Model B: K+rho | K, rho | 918 | 0.70976 | 0.867172 | 0.120408 | 0.503759 |
| Model C: K+rho+A1 | K, rho, A1_exists | 918 | 0.710176 | 0.868181 | 0.120356 | 0.504349 |
| Model D: K+rho+A1-A3 | K, rho, A1_exists, A2_retrieved, A3_surfaced | 918 | 0.712013 | 0.896411 | 0.11954 | 0.506963 |
| Model E: best clean pre-run | K, rho, A1_exists, old_A | 918 | 0.711601 | 0.893965 | 0.119748 | 0.506376 |
| Model F: best clean + discovered | K, rho, A1_exists, old_A, domain_familiarity | 918 | 0.716637 | 0.90528 | 0.117883 | 0.513569 |
| Model G: all pre-run variables | A1_exists, K, benchmark_novelty, context_budget, context_completeness, context_mismatch, domain_familiarity, evidence_scarcity, expected_files, model_calibration_history, old_A, planning_depth, relevant_files, retrieval_difficulty, rho, route_confidence, specialization_alignment, task_ambiguity, task_complexity | 918 | 0.722578 | 0.911679 | 0.115909 | 0.522119 |

## Holdout

| model | rows | corr | AUC | Brier | base Brier | Brier gain | R2 | calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Model A: K | 157 | 0.658603 | 0.663643 | 0.129747 | 0.22362 | 0.093872 | 0.419786 | 0.055332 |
| Model B: K+rho | 157 | 0.670606 | 0.84316 | 0.131252 | 0.22362 | 0.092367 | 0.413055 | 0.103248 |
| Model C: K+rho+A1 | 157 | 0.670606 | 0.84316 | 0.131252 | 0.22362 | 0.092367 | 0.413055 | 0.103248 |
| Model D: K+rho+A1-A3 | 157 | 0.671952 | 0.86094 | 0.130573 | 0.22362 | 0.093047 | 0.416094 | 0.102099 |
| Model E: best clean pre-run | 157 | 0.671355 | 0.86103 | 0.128897 | 0.22362 | 0.094723 | 0.423589 | 0.077267 |
| Model F: best clean + discovered | 157 | 0.682206 | 0.894231 | 0.124127 | 0.22362 | 0.099493 | 0.444919 | 0.065298 |
| Model G: all pre-run variables | 157 | 0.771029 | 0.903302 | 0.10019 | 0.22362 | 0.123429 | 0.551962 | 0.132365 |

## Frozen Prospective Reconstruction

| model | rows | corr | AUC | Brier | base Brier | Brier gain | R2 | calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Model A: K | 67 | 0.0 | 0.5 | 0.185937 | 0.181778 | -0.004159 | 0.0 | 0.064494 |
| Model B: K+rho | 67 | 0.248682 | 0.64951 | 0.180139 | 0.181778 | 0.001638 | 0.009013 | 0.077292 |
| Model C: K+rho+A1 | 67 | 0.248682 | 0.64951 | 0.180139 | 0.181778 | 0.001638 | 0.009013 | 0.077292 |
| Model D: K+rho+A1-A3 | 67 | 0.229719 | 0.636642 | 0.180652 | 0.181778 | 0.001126 | 0.006192 | 0.077699 |
| Model E: best clean pre-run | 67 | 0.254409 | 0.670956 | 0.178903 | 0.181778 | 0.002875 | 0.015813 | 0.070746 |
| Model F: best clean + discovered | 67 | 0.295854 | 0.675858 | 0.174193 | 0.181778 | 0.007585 | 0.041726 | 0.058443 |
| Model G: all pre-run variables | 67 | 0.436312 | 0.754902 | 0.195037 | 0.181778 | -0.01326 | 0.0 | 0.158174 |

## Result

Best clean pre-run model: `K, rho, A1_exists, old_A`. Best prospective row by Brier gain/R2: `Model F: best clean + discovered`. Clean prospective R2 remains `0.015813` with Brier gain `0.002875`; this is near-zero prediction, not predictive science.
