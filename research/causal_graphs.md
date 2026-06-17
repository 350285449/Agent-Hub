# Causal Graph Discovery

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

These are causal candidates, not causal proofs. They are ranked by clean prospective behavior with a small complexity penalty.

## Candidate Graphs

| graph | structure | holdout R2 | prospective R2 | prospective Brier gain | rank score | verdict |
| --- | --- | --- | --- | --- | --- | --- |
| G11 Interaction-gated prior |  -> Success via K + rho + A1_exists + old_A + distribution_shift_risk + rho>distribution_shift_risk | 0.485686 | 0.064732 | 0.011767 | 0.070499 | best available graph |
| G8 Access-mediated |  -> Success via K + rho + A1_exists + retrieval_difficulty + context_completeness | 0.406442 | 0.011313 | 0.002057 | 0.00937 | not sufficient |
| G9 Shift-moderated |  -> Success via K + rho + distribution_shift_risk + novelty_distance | 0.421381 | 0.002539 | 0.000462 | 0.001001 | not sufficient |
| G2 rho-only causal |  -> Success via rho | 0.342555 | 0.0 | -0.002814 | -0.002814 | not sufficient |
| G1 K-only causal |  -> Success via K | 0.419786 | 0.0 | -0.004159 | -0.004159 | not sufficient |
| G7 K/rho confounded priors |  -> Success via K + rho + calibration_history | 0.538624 | 0.0 | -0.005511 | -0.005511 | diagnostic prior graph |
| G10 Combined causal candidate |  -> Success via K + rho + A1_exists + old_A + difficulty_novelty_planning + calibration_history | 0.55042 | 0.0 | -0.009628 | -0.015628 | not sufficient |
| G3 A-only causal |  -> Success via A1_exists + old_A | 0.0 | 0.0 | -0.148024 | -0.148024 | not sufficient |
| G4 Difficulty causal |  -> Success via difficulty_novelty_planning | 0.0 | 0.0 | -0.148771 | -0.148771 | not sufficient |
| G6 Retrieval causal |  -> Success via retrieval_difficulty + context_completeness | 0.0 | 0.0 | -0.151639 | -0.151639 | not sufficient |
| G5 Planning causal |  -> Success via planning_horizon | 0.0 | 0.0 | -0.164781 | -0.164781 | not sufficient |

## Interpretation

The best graph is an interaction-gated prior graph: historical specialization (`rho`) predicts better when it exceeds measured distribution-shift risk. Direct `Difficulty -> Success`, `Planning -> Success`, and `Retrieval -> Success` graphs are underpowered and too redundant to stand alone.
