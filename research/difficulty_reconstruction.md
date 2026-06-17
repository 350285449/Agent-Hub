# Difficulty Reconstruction

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Difficulty was rebuilt from ambiguity, novelty, planning depth, retrieval burden, verification burden, and branching factor, ignoring prior Difficulty versions.

## Reconstructed Candidates

| difficulty candidate | field | holdout R2 | prospective R2 | prospective Brier gain | verdict |
| --- | --- | --- | --- | --- | --- |
| difficulty_novelty_planning | difficulty_novelty_planning | 0.431212 | 0.026881 | 0.004886 | weak composite only |
| difficulty_novelty_retrieval | difficulty_novelty_retrieval | 0.422494 | 0.025663 | 0.004665 | weak composite only |
| difficulty_mean | difficulty_mean | 0.430493 | 0.025207 | 0.004582 | weak composite only |
| difficulty_novelty_solution | difficulty_novelty_solution | 0.433192 | 0.025206 | 0.004582 | weak composite only |
| difficulty_planning_solution | difficulty_planning_solution | 0.429039 | 0.025038 | 0.004551 | weak composite only |
| difficulty_retrieval_solution | difficulty_retrieval_solution | 0.412213 | 0.024588 | 0.00447 | weak composite only |
| difficulty_novelty_verification | difficulty_novelty_verification | 0.430172 | 0.02335 | 0.004245 | weak composite only |
| difficulty_shift | difficulty_shift | 0.433118 | 0.022282 | 0.00405 | weak composite only |
| difficulty_task_novelty | difficulty_task_novelty | 0.432671 | 0.02213 | 0.004023 | weak composite only |
| difficulty_search | difficulty_search | 0.423508 | 0.021743 | 0.003952 | weak composite only |
| difficulty_verification_solution | difficulty_verification_solution | 0.4269 | 0.020061 | 0.003647 | weak composite only |
| difficulty_planning_retrieval | difficulty_planning_retrieval | 0.416791 | 0.019835 | 0.003606 | weak composite only |
| difficulty_planning_verification | difficulty_planning_verification | 0.422072 | 0.019594 | 0.003562 | weak composite only |
| difficulty_task_planning | difficulty_task_planning | 0.426827 | 0.018729 | 0.003404 | weak composite only |
| difficulty_task_solution | difficulty_task_solution | 0.428902 | 0.01862 | 0.003385 | weak composite only |
| difficulty_access | difficulty_access | 0.411577 | 0.013788 | 0.002506 | reject |

## Verdict

A clean Difficulty variable is not recovered. The best composites are mixtures of ambiguity, support, retrieval burden, and verification burden, but they are redundant with K/rho/A-like historical and access priors. Difficulty is useful as a diagnostic decomposition of failures; it is not a stable standalone pre-run predictor in this dataset.
