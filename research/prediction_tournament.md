# Prediction Tournament

Scope: Cloud-only aligned rows: 918 of 1091. Aligned exclusions: 173 rows by model {'gpt-5.5': 143, 'gemma4:31b-cloud': 10, 'nemotron-3-super:cloud': 10, 'kimi-k2.6:cloud': 10} and provider {'codex-cli': 143, 'ollama-cloud': 30}. Upstream strict audit additionally reported 11280 local deterministic rows, 2 timeout-only rows, and exclusion reasons {'duplicate task/model/context tuple': 5, 'local Ollama or otherwise disallowed model': 771, 'local deterministic proof row': 11280, 'provider failure/auth/subscription': 18, 'synthetic or derived benchmark row without allowed model provenance': 1380, 'timeout-only row with no usable output': 2, 'unsuccessful execution or unusable validation result': 4}.

## Frozen Prospective Cloud-Only Result

| rows | successes | failures | excluded non-cloud rows | corr | AUC | Brier | R2 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 67 | 16 | 51 | 10 | 0.009754 | 0.48223 | 0.231827 | 0 |

The filtered prospective set contains models {'nemotron-3-super:cloud': 67}.

## Retrospective Frozen-Style Holdout

| model | rows | corr | AUC | Brier | R2 |
| --- | --- | --- | --- | --- | --- |
| K+rho+A | 157 | 0.676773 | 0.879354 | 0.126126 | 0.458021 |
| K+rho+A1-A3 | 157 | 0.671952 | 0.86094 | 0.130573 | 0.451519 |
| K+rho+A1-A5 | 157 | 0.799124 | 0.938316 | 0.08489 | 0.638599 |

## Evidence

The retrospective cloud-only holdout supports K+rho+A directionally. The true frozen prospective cloud-only tournament does not.

## Counter-Evidence

The prospective tournament used an older frozen compatibility score, not a freshly frozen K+rho+A model, and after exclusions it is all Nemotron cloud. That is a severe coverage limitation.

## Uncertainty

Prospective cloud-only validation is inconclusive-to-negative, not decisive. A clean next tournament must freeze K, rho-vector, and A1-A3 before collection and balance at least three cloud models.

## Falsification Attempt

All-model prospective R2 was 0.098044; cloud-only R2 is 0. The generalization claim fails under the user's cloud-only exclusion rule.
