# Prospective Prediction Framework

Scope: Cloud-only aligned rows: 918 of 1091. Aligned exclusions: 173 rows by model {'gpt-5.5': 143, 'gemma4:31b-cloud': 10, 'nemotron-3-super:cloud': 10, 'kimi-k2.6:cloud': 10} and provider {'codex-cli': 143, 'ollama-cloud': 30}. Upstream strict audit additionally reported 11280 local deterministic rows, 2 timeout-only rows, and exclusion reasons {'duplicate task/model/context tuple': 5, 'local Ollama or otherwise disallowed model': 771, 'local deterministic proof row': 11280, 'provider failure/auth/subscription': 18, 'synthetic or derived benchmark row without allowed model provenance': 1380, 'timeout-only row with no usable output': 2, 'unsuccessful execution or unusable validation result': 4}.

## Frozen Rule

The v2 framework is prediction-first. Every row must be written with model, repository, category, context budget, K, rho, A, success probability, confidence interval, and uncertainty estimate before execution. Outcomes are appended only after the frozen forecast file exists.

## Cloud-Only Inclusion

Allowed model IDs are gemma4:31b-cloud, glm-5.1:cloud, kimi-k2.6:cloud, nemotron-3-super:cloud, qwen3.5:cloud. Codex, Ollama, local, self-hosted, quantized, and edge results are excluded before every statistic is computed.

## Benchmark Sets

| set | forecast rows | mean p(success) | min p | max p | mean uncertainty p(1-p) |
| --- | --- | --- | --- | --- | --- |
| calibration_grid | 120 | 0.32 | 0.025 | 1.0 | 0.103 |
| hard_generalization | 135 | 0.314 | 0.025 | 1.0 | 0.094 |
| accessibility_stress | 90 | 0.311 | 0.067 | 1.0 | 0.099 |

## Model Tournament

The frozen comparison models are K, K+rho, K+rho+A, and K+rho+A1-A5. A1-A5 is reported as an upper-bound diagnostic because A4/A5 are currently post-generation traces; K+rho+A is the primary deployable forecast model until A4/A5 can be measured before generation.

## Required Metrics

Calibration error, reliability curves, Brier score, base-rate Brier gain, prediction error, false-positive clusters, and false-negative clusters are recomputed from cloud-only rows. A positive result is accepted only if it beats K and K+rho prospectively, not merely retrospectively.

## Falsification Gates

- Reject strong predictive-science claims if prospective R2 remains below 0.25 or Brier does not beat base rate by at least 0.03.
- Reject Accessibility as prospective improvement if K+rho+A does not beat K+rho on frozen outcomes.
- Treat the 0.865391 ceiling as unvalidated if real prospective R2 remains near zero.
- Promote no fourth primitive from residuals unless it is measurable before execution and survives deconfounding.
