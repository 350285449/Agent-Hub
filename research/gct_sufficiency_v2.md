# GCT Sufficiency v2

## Question

How much trajectory information is retained by Grounding + Commitment?

## Estimands

- Variance explained by Model D on holdout.
- Variance explained by Model E on holdout.
- Retained trajectory information = `R2_D / R2_E`, reported only if `R2_E > 0`.
- Predictive loss vs full trajectory = `Brier_D - Brier_E` and `R2_E - R2_D`.

## Sufficiency Rule

GCT is sufficient only if Model D retains at least 80% of Model E holdout variance and loses no more than 0.03 Brier against Model E, with stability across task and model-family splits.

## Current Status

Not estimable until valid v2 execution exists.
