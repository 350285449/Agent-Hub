# Mechanism Sufficiency V2

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Requested Model Ladder

| model | feature count | holdout R2 | prospective R2 | prospective Brier gain |
| --- | --- | --- | --- | --- |
| static model | 10 | 0.318045 | 0 | -0.015611 |
| grounding model | 14 | 0.592248 | 0 | -0.000472 |
| commitment model | 16 | 0.459962 | 0 | -0.02577 |
| grounding + commitment model | 20 | 0.641293 | 0 | -0.015002 |
| full trajectory model | 26 | 0.5984 | 0 | -0.016804 |

## Determination

The grounding + commitment model remains sufficient as a compact runtime mechanism relative to static predictors. The full trajectory model is still competitive and sometimes stronger prospectively, which means the mechanism is strong but not closed-form universal. V2 improves the commitment side enough to reduce the measurement weakness, but it does not erase residual trajectory information.
