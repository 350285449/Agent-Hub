# Fourth Primitive Final Trial

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Admission rule: pre-run, deconfounded after clean model, improves prospective R2, improves Brier/calibration, and remains stable across datasets.

| candidate | timing | holdout R2 | prospective R2 | Brier gain delta vs clean | verdict | measurement |
| --- | --- | --- | --- | --- | --- | --- |
| task_ambiguity | pre-run | 0.425618 | 0.015333 | -8.8e-05 | reject | Pre-run ambiguity proxy from missing/underspecified expected evidence labels. |
| task_complexity | pre-run | 0.401211 | 0.014929 | -0.000161 | reject | Pre-run complexity proxy from expected/relevant evidence count and planned context. |
| planning_depth | pre-run | 0.421355 | 0.016997 | 0.000215 | reject | Pre-run category prior for architecture/refactor/research tasks requiring explicit planning. |
| retrieval_difficulty | pre-run | 0.412765 | 0.015105 | -0.000129 | reject | Pre-run expected evidence burden before retrieval is executed. |
| context_mismatch | pre-run | 0.423367 | 0.015427 | -7.1e-05 | reject | Pre-run mismatch between expected evidence burden and planned context budget. |
| context_completeness | pre-run | 0.427671 | 0.014391 | -0.000259 | reject | Pre-run planned context adequacy relative to expected evidence burden. |
| tool_dependency_count | uncertain | 0.419599 | 0.0 | -0.003588 | reject | Unavailable cleanly; current tests/verifiers are post-run, so only category prior is tested. |
| evidence_scarcity | pre-run | 0.412765 | 0.015105 | -0.000129 | reject | Pre-run scarcity proxy from low expected/relevant file labels. |
| benchmark_novelty | pre-run if frozen | 0.434007 | 0.026336 | 0.001912 | reject: historical prior, not primitive | Frozen historical row-count prior by repository/category cell. |
| domain_familiarity | pre-run if frozen | 0.444919 | 0.041726 | 0.00471 | reject: historical prior, not primitive | Frozen historical repository familiarity prior. |
| specialization_alignment | pre-run if frozen | 0.423589 | 0.015813 | 0.0 | reject | Frozen rho/category alignment prior. |
| model_calibration_history | pre-run if frozen | 0.539611 | 0.0 | -0.008579 | reject | Frozen historical model success prior. |
| route_confidence | pre-run if frozen | 0.41728 | 0.012931 | -0.000524 | reject | Frozen confidence prior from K/rho/context agreement. |
| prompt_entropy | uncertain | 0.404208 | 0.0 | -0.00754 | reject | Unavailable directly; proxy from category/repository/task-label diversity. |

## Final Decision

No fourth primitive survives. Several variables are diagnostically useful, especially post-run evidence-use traces, but none meet the clean prospective admission rule. Reject every candidate until frozen cloud-only evidence says otherwise.
