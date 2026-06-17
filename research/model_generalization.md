# Model Generalization

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Falsification standard: the result should fail if it is carried by one provider/model family.

| model family | rows | success rate | GI score AUC | grounded-action AUC | retro explanatory R2 gain | within-family holdout R2 | detectable failures share | central prevented rows | strongest warning |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| google | 413 | 0.956416 | 0.932419 | 0.88038 | 0.001621 | 0.91993 | 0.555556 | 0.061728 | contradictory grounding |
| nemotron-3-super | 477 | 0.289308 | 0.824762 | 0.831132 | 0.00649 | 0.974645 | 0.637168 | 0.185789 | delayed grounding |

## Determination

The strongest falsifier would be a model family with adequate rows, mixed outcomes, and zero or negative Grounding Integrity gain. Model-family imbalance remains a material weakness even where the direction survives.
