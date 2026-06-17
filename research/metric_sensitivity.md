# Metric Sensitivity

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Alternative definitions intentionally perturb the implementation of `grounded_action_ratio`, `grounding_latency`, `evidence_action_latency`, and `grounding_integrity_score`.

| metric definition | single corr | single AUC | single R2 | holdout R2 with baseline | holdout R2 gain | holdout AUC |
| --- | --- | --- | --- | --- | --- | --- |
| grounded_action_ratio | 0.609686 | 0.888536 | 0.371717 | 0.556092 | 0.139998 | 0.943759 |
| gar_verification_weighted | 0.619642 | 0.892997 | 0.383957 | 0.550997 | 0.134903 | 0.945755 |
| gar_linked_mean | 0.620282 | 0.896477 | 0.384749 | 0.544674 | 0.12858 | 0.941401 |
| gar_linked_min | 0.597776 | 0.885354 | 0.357336 | 0.53674 | 0.120646 | 0.931967 |
| gis_observable_strict | 0.502456 | 0.797663 | 0.252462 | 0.536307 | 0.120213 | 0.92607 |
| gis_latency_heavy | 0.519435 | 0.805999 | 0.269813 | 0.505258 | 0.089164 | 0.921807 |
| gis_action_heavy | 0.557804 | 0.881343 | 0.311146 | 0.493881 | 0.077787 | 0.925435 |
| gis_equal_weight | 0.553918 | 0.875393 | 0.306825 | 0.493414 | 0.07732 | 0.922079 |
| grounding_integrity_score | 0.527479 | 0.882659 | 0.278234 | 0.487146 | 0.071052 | 0.919267 |
| eal_with_action | 0.402166 | 0.787712 | 0.161738 | 0.475869 | 0.059775 | 0.914097 |
| eal_strict | 0.279085 | 0.599223 | 0.077889 | 0.462681 | 0.046587 | 0.903211 |
| grounding_latency_integrity | 0.143784 | 0.569194 | 0.020674 | 0.443602 | 0.027508 | 0.886611 |
| grounding_latency_raw_inverse | 0.143784 | 0.569194 | 0.020674 | 0.443602 | 0.027508 | 0.886611 |
| grounding_latency_decisive_inverse | 0.143784 | 0.569194 | 0.020674 | 0.443602 | 0.027508 | 0.886611 |
| gar_strict | 0.331202 | 0.63516 | 0.109695 | 0.43807 | 0.021976 | 0.885976 |
| grounding_latency_soft | 0.1301 | 0.569194 | 0.016926 | 0.436092 | 0.019998 | 0.881168 |
| eal_raw_inverse | 0.130486 | 0.55966 | 0.017027 | 0.389723 | -0.026371 | 0.86348 |
| evidence_to_action_latency | -0.130486 | 0.44034 | 0.017027 | 0.389723 | -0.026371 | 0.86348 |

## Determination

Grounding Integrity survives metric sensitivity if action-linkage variants and score variants remain positive. It fails as a single-formula artifact if only the original formula works.
