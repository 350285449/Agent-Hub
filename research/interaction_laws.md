# Interaction Laws

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Interaction And Nonlinear Search

| candidate effect | local fields | holdout R2 | prospective R2 | delta Brier gain vs existing | verdict |
| --- | --- | --- | --- | --- | --- |
| rho>distribution_shift_risk | rho, distribution_shift_risk, rho>distribution_shift_risk | 0.485686 | 0.064732 | 0.008892 | survives weakly |
| search_complexity^2 | old_A, search_complexity, search_complexity^2 | 0.439748 | 0.029383 | 0.002466 | survives weakly |
| search_complexity_high | old_A, search_complexity, search_complexity_high | 0.431117 | 0.025455 | 0.001752 | survives weakly |
| search_complexity_low | old_A, search_complexity, search_complexity_low | 0.431117 | 0.025455 | 0.001752 | survives weakly |
| K*search_complexity | K, search_complexity, K*search_complexity | 0.428308 | 0.024667 | 0.001609 | survives weakly |
| K>rho | K, rho, K>rho | 0.390893 | 0.023018 | 0.001309 | survives weakly |
| rho*distribution_shift_risk | rho, distribution_shift_risk, rho*distribution_shift_risk | 0.428453 | 0.022837 | 0.001276 | survives weakly |
| planning_horizon_low | old_A, planning_horizon, planning_horizon_low | 0.424201 | 0.022009 | 0.001126 | survives weakly |
| K>planning_horizon | K, planning_horizon, K>planning_horizon | 0.425329 | 0.021803 | 0.001088 | survives weakly |
| planning_horizon^2 | old_A, planning_horizon, planning_horizon^2 | 0.423763 | 0.02179 | 0.001086 | survives weakly |
| K*planning_horizon | K, planning_horizon, K*planning_horizon | 0.42416 | 0.020742 | 0.000895 | survives weakly |
| K*rho | K, rho, K*rho | 0.410833 | 0.019773 | 0.000719 | survives weakly |
| rho_high | old_A, rho, rho_high | 0.422629 | 0.019199 | 0.000615 | survives weakly |
| K*A1_exists | K, A1_exists, K*A1_exists | 0.423589 | 0.015813 | 0.0 | reject |
| K>A1_exists | K, A1_exists, K>A1_exists | 0.423589 | 0.015813 | 0.0 | reject |
| rho*A1_exists | rho, A1_exists, rho*A1_exists | 0.423589 | 0.015813 | 0.0 | reject |
| rho>A1_exists | rho, A1_exists, rho>A1_exists | 0.423589 | 0.015813 | 0.0 | reject |
| retrieval_difficulty_low | old_A, retrieval_difficulty, retrieval_difficulty_low | 0.412765 | 0.015105 | -0.000129 | reject |
| K>retrieval_difficulty | K, retrieval_difficulty, K>retrieval_difficulty | 0.403201 | 0.014556 | -0.000229 | reject |
| K*retrieval_difficulty | K, retrieval_difficulty, K*retrieval_difficulty | 0.37994 | 0.014296 | -0.000276 | reject |
| K^2 | old_A, K, K^2 | 0.019026 | 0.011299 | -0.000821 | reject |
| planning_horizon_high | old_A, planning_horizon, planning_horizon_high | 0.418563 | 0.01027 | -0.001008 | reject |
| rho^2 | old_A, rho, rho^2 | 0.441439 | 0.009153 | -0.001211 | reject |
| K>search_complexity | K, search_complexity, K>search_complexity | 0.211124 | 0.0 | -0.00496 | reject |

## Thresholds And Phase Transitions

The search found a real reconstructed escape signal: `rho > distribution_shift_risk` lifts prospective reconstructed R2 above the prior discovered-extension ceiling. It is still not a mature law. The effect is small, selected from a search, and depends on frozen historical support estimates, so it must be treated as a candidate interaction for future frozen validation rather than protected theory.
