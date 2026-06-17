# Family Generalization

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Falsification standard: Grounding Integrity should fail if its explanatory gain, predictive signal, or intervention estimate only exists in one task family.

| task family | rows | success rate | GI score AUC | grounded-action AUC | retro explanatory R2 gain | within-family holdout R2 | detectable failures share | central prevented rows | strongest warning |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| agentic | 30 | 0.266667 | 0.985795 | 0.985795 | 0.302809 | 0.879167 | 0.0 | n/a | unstable grounding |
| coding | 723 | 0.603043 | 0.874497 | 0.882848 | 0.108965 | 0.729713 | 0.627178 | 0.272881 | contradictory grounding |
| reasoning | 94 | 0.510638 | 0.947237 | 0.94135 | 0.037228 | 0.0 | 0.586957 | 0.460718 | contradictory grounding |
| research | 71 | 0.577465 | 0.828049 | 0.831301 | 0.004961 | 0.992376 | 0.633333 | 0.314338 | unstable grounding |

## Determination

Grounding Integrity survives family generalization if every populated family shows positive explanatory gain and nontrivial detection/intervention signal. The weakest family is the row with the smallest explanatory gain. This is not a clean causal proof because family labels are coarse and partially inferred from category/action traces.
