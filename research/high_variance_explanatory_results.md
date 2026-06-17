# High Variance Explanatory Results

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Explanatory power is the blended holdout/prospective/Brier gain over K+rho+A1-A3. Transferability is the mean of positive leave-benchmark and leave-model-family split shares. Robustness is mean residual gain across variable ablations after all core controls.

| theory | explanatory power | transferability | robustness | diagnostic correlation | classification |
| --- | --- | --- | --- | --- | --- |
| Tool Trust Calibration Theory | 0.000268 | 0 | -0.020596 | 0.041944 | collapsed |
| Antifragility Theory | 0.000268 | 0 | -0.020596 | 0.075898 | collapsed |
| Collective Intelligence Theory | 0.017646 | 0 | 0 | 0.125184 | collapsed |
| Adaptive Networks Theory | 0.000491 | 0 | 0 | 0.349774 | collapsed |
| Verification Debt Theory | 0.044861 | 0 | 0.003821 | 0.117419 | redundant |
| Controllability Theory | 0.000268 | 0 | -0.020596 | 0.058921 | collapsed |
| Context Drift Theory | 0.058396 | 0 | 0 | 0.252745 | collapsed |
| Observability Theory | 0.050381 | 0 | 0 | 0.136777 | collapsed |
| Regret Minimization Theory | 0.055806 | 0 | -0.020596 | 0.206979 | collapsed |
| Rational Inattention Theory | 0.097036 | 0 | -0.000006 | 0.160031 | diagnostic only |
| Fixed Point Theory | 0.154652 | 0 | 0 | 0.373733 | collapsed |
| Organizational Failure Theory | 0.009311 | 0 | 0 | 0.140239 | collapsed |
| Cascade Failure Theory | 0.039041 | 0 | 0 | 0.272734 | collapsed |
| Value of Information Theory | 0.117949 | 0 | 0 | 0.15943 | collapsed |
| State Estimation Theory | 0.037878 | 0 | 0 | 0.221737 | collapsed |
| Predictive Processing Theory | 0.105354 | 0 | 0 | 0.276987 | collapsed |
| Constraint Satisfaction Theory | 0.145172 | 0 | 0 | 0.249858 | collapsed |
| Global Workspace Theory | 0.149553 | 0 | 0 | 0.187805 | collapsed |
| Narrative Coherence Theory | 0.145445 | 0 | 0 | 0.327715 | collapsed |
| Information Asymmetry Theory | 0.036143 | 0 | 0 | 0.09417 | collapsed |

## Result

Most theories explain historical variance before strict controls because their variables touch evidence, state, verification, or commitment timing. That is not enough. After transfer and robustness tests, no theory clears the strong independent-mechanism threshold; the best results are diagnostic or weak residuals.
