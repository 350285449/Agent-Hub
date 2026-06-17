# Temporal Stability

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Rows were split by corpus order into early and late halves. Cross-time rows train on one half and test on the other.

| split | rows/test rows | success rate | GI/combined AUC | R2 gain over baseline | detectable failures share | central prevented rows | strongest warning |
| --- | --- | --- | --- | --- | --- | --- | --- |
| early | 459 | 0.642702 | 0.839872 | 0.115803 | 0.670732 | 0.244078 | contradictory grounding |
| late | 459 | 0.518519 | 0.911441 | 0.074245 | 0.524887 | 0.315643 | contradictory grounding |
| early->late | 459 | 0.518519 | 0.94938 | 0.09472 | n/a | n/a | n/a |
| late->early | 459 | 0.642702 | 0.915998 | 0.098265 | n/a | n/a | n/a |

## Determination

Temporal survival requires the sign of the effect to persist in both halves and under early-to-late/late-to-early transfer. Instability here would suggest instrumentation drift or corpus-construction artifact.
