# Prospective Validation v2

Scope: Cloud-only aligned rows: 918 of 1091. Aligned exclusions: 173 rows by model {'gpt-5.5': 143, 'gemma4:31b-cloud': 10, 'nemotron-3-super:cloud': 10, 'kimi-k2.6:cloud': 10} and provider {'codex-cli': 143, 'ollama-cloud': 30}. Upstream strict audit additionally reported 11280 local deterministic rows, 2 timeout-only rows, and exclusion reasons {'duplicate task/model/context tuple': 5, 'local Ollama or otherwise disallowed model': 771, 'local deterministic proof row': 11280, 'provider failure/auth/subscription': 18, 'synthetic or derived benchmark row without allowed model provenance': 1380, 'timeout-only row with no usable output': 2, 'unsuccessful execution or unusable validation result': 4}.

## Answers

1. Can K+rho+A predict future outcomes? Not established. It has retrospective holdout signal, but clean future v2 outcomes are still pending.
2. Is calibration acceptable? Not prospectively. The prior prospective reconstruction and old compatibility tournament are too narrow and weak.
3. What is the real prospective R2? The only actually frozen cloud-only prospective tournament remains effectively 0 for the accepted cloud subset; v2 real R2 is pending until the frozen sets are executed.
4. What causes major forecast failures? Coarse rho cells, repository-specific execution constraints, ambiguous benchmark labels, and post-run contamination in A-like variables.
5. Does Accessibility improve prospective prediction? Retrospectively it can, especially with A1-A5; prospectively it is unproven because clean pre-run A must beat K+rho after freezing.
6. Is the 0.865 ceiling reflected in real forecasting performance? No. The ceiling is a measurement prior, not observed prospective performance.
7. Is Agent-Hub becoming predictive science or only explanatory science? It is not yet predictive science. It becomes predictive only if the frozen v2 forecasts calibrate on new cloud-only outcomes.

## Tournament Status

Best retrospective holdout model by R2: K+rho+A1-A5 (0.638599). Best prior prospective reconstruction by R2: K+rho+A1-A5 (0.182824).

## Decision

The framework survives as a forecast protocol, not as a validated predictive theory. The next execution must be adversarial: prioritize uncertain cells near p=0.5, hard repositories, low context budgets, and model/category cells where retrospective fit is likely to fail.
