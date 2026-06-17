# Model-Family Analysis

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Family Slices

| family | rows | success rate | top predictor | top corr | second predictor | second corr | dominant failure mode |
| --- | --- | --- | --- | --- | --- | --- | --- |
| general | 413 | 0.956416 | calibration_history | -1.0 | K | -0.983517 | overfit historical priors |
| reasoning | 483 | 0.285714 | rho | 0.241534 | distribution_shift_risk | -0.163039 | overfit historical priors |

## Result

Prediction is family-dependent in practice, but not in a way that yields a universal new primitive. Reasoning and agentic families lean on historical capability/specialization priors. Coding/search-heavy rows expose retrieval and tool-risk failures. The family effect mostly says that `rho` should be vectorized by family, not that a fourth primitive has been found.
