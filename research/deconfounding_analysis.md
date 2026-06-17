# Adversarial Deconfounding

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Controls: `K`, `rho`, `A1-A3`, task family, model family, and benchmark one-hot controls. This is deliberately adversarial because benchmark controls can absorb real distributional signal.

| control set | control features | control R2 | + GI score R2 | GI score delta | + GI metrics R2 | GI metrics delta | + combined GI R2 | combined delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K+rho+A1-A3 | 5 | 0.416094 | 0.487146 | 0.071052 | 0.592381 | 0.176287 | 0.591585 | 0.175491 |
| + task family | 9 | 0.412682 | 0.491218 | 0.078536 | 0.471383 | 0.058701 | 0.591685 | 0.179003 |
| + model family | 8 | 0.23548 | 0.148998 | -0.086482 | 0.973463 | 0.737983 | 0.973487 | 0.738007 |
| + benchmark | 14 | 0.405969 | 0.472664 | 0.066695 | 0.589426 | 0.183457 | 0.589385 | 0.183416 |
| + all controls | 21 | 0.238856 | 0.0 | -0.238856 | 0.865496 | 0.62664 | 0.974626 | 0.73577 |

## Determination

The key row is `+ all controls`. If the combined delta remains positive after all controls, the result is not explained away by K/rho/accessibility, family, model, or benchmark composition. If the delta collapses, Grounding Integrity is partly a distribution artifact.
