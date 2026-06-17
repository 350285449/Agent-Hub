# Prospective Validation v3

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Clean Tournament

| model | rows | corr | AUC | Brier | base Brier | Brier gain | R2 | calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K | 67 | 0.0 | 0.5 | 0.185937 | 0.181778 | -0.004159 | 0.0 | 0.064494 |
| K+rho | 67 | 0.248682 | 0.64951 | 0.180139 | 0.181778 | 0.001638 | 0.009013 | 0.077292 |
| K+rho+A1 | 67 | 0.248682 | 0.64951 | 0.180139 | 0.181778 | 0.001638 | 0.009013 | 0.077292 |
| K+rho+A1-A3 | 67 | 0.229719 | 0.636642 | 0.180652 | 0.181778 | 0.001126 | 0.006192 | 0.077699 |
| K+rho+A1-A5 | 67 | 0.42758 | 0.76777 | 0.161207 | 0.181778 | 0.020571 | 0.113163 | 0.11497 |

## Decision

Best prior prospective reconstruction: `K+rho+A1-A5` with R2 `0.113163`. This is not strong prospective validation because these feature values were reconstructed after the fact and the accepted set is narrow. The truly frozen older compatibility tournament remains near zero after cloud-only filtering.

## Answers

1. Truly pre-run predictors: `A1_exists`, planned `context_budget`, benchmark/task labels, and frozen historical priors (`K`, `rho`, compatibility priors) with the caveat that the priors are outcome-derived. `A2/A3` are only post-retrieval pre-generation.
2. Retrospective dependence on contamination: measured by the R2 loss table; the A1-A5 advantage over A1-A3 is diagnostic contamination, not clean forecast power.
3. Best clean pre-run model: `K+rho+A1` for initial routing; `K+rho+A1-A3` after retrieval is frozen.
4. Why prospective prediction fails: leakage, small imbalanced prospective cloud rows, benchmark drift, unstable `rho`, and model-family concentration.
5. Methodology or theory: primarily methodology. The theory is explanatory/diagnostic until clean prospective evidence exists.
6. Can K+rho+A predict future outcomes before execution: not established. Clean K+rho+A1/A1-A3 does not yet meet strong prospective criteria.
7. Scientific status: Agent-Hub is currently explanatory and diagnostic science, not validated predictive science.
