# Ceiling Stress Test

Scope: Cloud-only aligned rows: 918 of 1091. Aligned exclusions: 173 rows by model {'gpt-5.5': 143, 'gemma4:31b-cloud': 10, 'nemotron-3-super:cloud': 10, 'kimi-k2.6:cloud': 10} and provider {'codex-cli': 143, 'ollama-cloud': 30}. Upstream strict audit additionally reported 11280 local deterministic rows, 2 timeout-only rows, and exclusion reasons {'duplicate task/model/context tuple': 5, 'local Ollama or otherwise disallowed model': 771, 'local deterministic proof row': 11280, 'provider failure/auth/subscription': 18, 'synthetic or derived benchmark row without allowed model provenance': 1380, 'timeout-only row with no usable output': 2, 'unsuccessful execution or unusable validation result': 4}.

## Main Estimate

| quantity | cloud-only value |
| --- | ---: |
| K+rho+A R2 | 0.50962 |
| K+rho+A1-A5 R2 | 0.609926 |
| observed measured-feature R2 | 0.513246 |
| mean primitive reliability | 0.625 |
| reliability-corrected R2 | 0.815391 |
| ceiling estimate | 0.865391 |

The previous 0.771 ceiling is not stable under cloud-only recomputation; the analogous estimate is 0.865391.

## Stress Tests

| subset | rows | K+rho+A R2 | K+rho+A1-A5 R2 |
| --- | --- | --- | --- |
| all cloud | 918 | 0.50962 | 0.609926 |
| no Agent-Hub | 352 | 0.54241 | 0.64383 |
| Agent-Hub only | 566 | 0.494318 | 0.597459 |
| live only | 879 | 0.509083 | 0.611454 |
| no unmatched evidence rows | 878 | 0.508721 | 0.610995 |
| major models only | 890 | 0.487671 | 0.597339 |

## Evidence

Most cloud-only subsets remain above 0.50 R2 for K+rho+A, and reliability correction remains high.

## Counter-Evidence

The estimate depends strongly on outcome-derived K/rho reliability. The prospective cloud-only tournament does not validate this ceiling.

## Uncertainty

Treat 0.865391 as a measurement-ceiling prior, not as achieved explanatory power. The credible practical band is roughly 0.70-0.87 depending on whether post-run accessibility diagnostics are admitted.

## Falsification Attempt

Under a strict pre-run A1-A3 rule, R2 is 0.506963, below current A. That falsifies the claim that clean accessibility measurement alone already raises explanatory power.
