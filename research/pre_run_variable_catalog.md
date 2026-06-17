# Pre-Run Variable Catalog

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Each candidate was tested rather than assumed. Predictive power is shown as incremental clean-model performance when added to `K+rho+A1`.

| variable | timing | definition / measurement | reliability | single corr | holdout R2 | prospective R2 | prospective Brier gain | prospective plausibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| task_ambiguity | pre-run | Pre-run ambiguity proxy from missing/underspecified expected evidence labels. | low | -0.080732 | 0.416097 | 0.008432 | 0.001533 | yes |
| task_complexity | pre-run | Pre-run complexity proxy from expected/relevant evidence count and planned context. | low | 0.067812 | 0.401889 | 0.007762 | 0.001411 | yes |
| planning_depth | pre-run | Pre-run category prior for architecture/refactor/research tasks requiring explicit planning. | low | -0.025183 | 0.411089 | 0.01083 | 0.001969 | yes |
| retrieval_difficulty | pre-run | Pre-run expected evidence burden before retrieval is executed. | low | 0.065723 | 0.401416 | 0.00841 | 0.001529 | yes |
| context_mismatch | pre-run | Pre-run mismatch between expected evidence burden and planned context budget. | low | -0.056136 | 0.415098 | 0.011388 | 0.00207 | yes |
| context_completeness | pre-run | Pre-run planned context adequacy relative to expected evidence burden. | low | 0.078934 | 0.417021 | 0.012311 | 0.002238 | yes |
| tool_dependency_count | uncertain | Unavailable cleanly; current tests/verifiers are post-run, so only category prior is tested. | moderate | 0.110908 | 0.410108 | 0.0 | -0.001869 | not yet |
| evidence_scarcity | pre-run | Pre-run scarcity proxy from low expected/relevant file labels. | low | -0.065723 | 0.401416 | 0.00841 | 0.001529 | yes |
| benchmark_novelty | pre-run if frozen | Frozen historical row-count prior by repository/category cell. | moderate | -0.128052 | 0.426035 | 0.021566 | 0.00392 | yes |
| domain_familiarity | pre-run if frozen | Frozen historical repository familiarity prior. | unstable | -0.182958 | 0.432837 | 0.033365 | 0.006065 | yes |
| specialization_alignment | pre-run if frozen | Frozen rho/category alignment prior. | unstable | 0.685836 | 0.413055 | 0.009013 | 0.001638 | yes |
| model_calibration_history | pre-run if frozen | Frozen historical model success prior. | unstable | 0.694277 | 0.538622 | 0.0 | -0.005511 | not yet |
| route_confidence | pre-run if frozen | Frozen confidence prior from K/rho/context agreement. | unstable | 0.592778 | 0.417248 | 0.011666 | 0.002121 | yes |
| prompt_entropy | uncertain | Unavailable directly; proxy from category/repository/task-label diversity. | low | -0.070701 | 0.393378 | 0.0 | -0.005986 | not yet |

## Catalog Verdict

Clean pre-run variables exist, but most are weak. The only strong clean signals are frozen historical priors (`K`, `rho`, model calibration), which are explanatory memory rather than prospective mechanisms. No newly discovered candidate is strong enough to promote without a fresh frozen panel.
