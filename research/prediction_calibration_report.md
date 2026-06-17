# Prediction Calibration Report

Scope: Cloud-only aligned rows: 918 of 1091. Aligned exclusions: 173 rows by model {'gpt-5.5': 143, 'gemma4:31b-cloud': 10, 'nemotron-3-super:cloud': 10, 'kimi-k2.6:cloud': 10} and provider {'codex-cli': 143, 'ollama-cloud': 30}. Upstream strict audit additionally reported 11280 local deterministic rows, 2 timeout-only rows, and exclusion reasons {'duplicate task/model/context tuple': 5, 'local Ollama or otherwise disallowed model': 771, 'local deterministic proof row': 11280, 'provider failure/auth/subscription': 18, 'synthetic or derived benchmark row without allowed model provenance': 1380, 'timeout-only row with no usable output': 2, 'unsuccessful execution or unusable validation result': 4}.

## Retrospective Frozen-Style Holdout

| model | rows | corr | AUC | Brier | base Brier | Brier gain | R2 | calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K | 157 | 0.658603 | 0.663643 | 0.129747 | 0.22362 | 0.093873 | 0.433758 | 0.055325 |
| K+rho | 157 | 0.670606 | 0.84316 | 0.131252 | 0.22362 | 0.092368 | 0.449712 | 0.10314 |
| K+rho+A | 157 | 0.676773 | 0.879354 | 0.126126 | 0.22362 | 0.097494 | 0.458021 | 0.069331 |
| K+rho+A1-A5 | 157 | 0.799124 | 0.938316 | 0.08489 | 0.22362 | 0.13873 | 0.638599 | 0.078624 |

## Prior Prospective Set Reconstructed With v2 Features

| model | rows | corr | AUC | Brier | base Brier | Brier gain | R2 | calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K | 67 | 0.0 | 0.5 | 0.185937 | 0.181778 | -0.004159 | 0.0 | 0.064 |
| K+rho | 67 | 0.248682 | 0.64951 | 0.180139 | 0.181778 | 0.001639 | 0.061843 | 0.077 |
| K+rho+A | 67 | 0.305486 | 0.706495 | 0.176989 | 0.181778 | 0.004789 | 0.093322 | 0.07 |
| K+rho+A1-A5 | 67 | 0.42758 | 0.76777 | 0.161207 | 0.181778 | 0.020571 | 0.182824 | 0.114985 |

This reconstruction is not accepted as clean v2 prospective evidence because K/rho/A were not frozen for those rows before execution. It is a falsification stress test against the current measurement family.

## K+rho+A Reliability Curve: Holdout

| prediction bin | rows | mean predicted | mean actual | actual - predicted |
| --- | --- | --- | --- | --- |
| 0.0-0.2 | 27 | 0.063 | 0.0 | -0.063 |
| 0.2-0.4 | 91 | 0.294 | 0.22 | -0.074 |
| 0.4-0.6 | 1 | 0.404 | 0.0 | -0.404 |
| 0.6-0.8 | 6 | 0.697 | 0.5 | -0.197 |
| 0.8-1.0 | 32 | 0.964 | 0.938 | -0.027 |

## K+rho+A Reliability Curve: Prior Prospective Reconstruction

| prediction bin | rows | mean predicted | mean actual | actual - predicted |
| --- | --- | --- | --- | --- |
| 0.0-0.2 | 0 |  |  |  |
| 0.2-0.4 | 67 | 0.309 | 0.239 | -0.07 |
| 0.4-0.6 | 0 |  |  |  |
| 0.6-0.8 | 0 |  |  |  |
| 0.8-1.0 | 0 |  |  |  |

## Verdict

Calibration is not yet acceptable prospectively. Holdout calibration can look useful, but the prior prospective reconstruction is narrow, model-imbalanced, and does not validate the retrospective ceiling.
