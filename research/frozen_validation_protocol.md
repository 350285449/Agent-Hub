# Frozen Validation Protocol

Status: activated because a weak interaction signal survived enough falsification to merit one frozen test, not because it is accepted.

## Pre-Registered Variables

- `K`: frozen historical cloud-only model prior, computed before outcome collection.
- `rho`: frozen historical cloud-only model/category specialization prior, computed before outcome collection.
- `A1_exists`: task-side benchmark/evidence existence flag.
- `old_A`: planned context-budget proxy.
- `distribution_shift_risk`: frozen support-distance proxy from historical model/repository/category coverage.
- Interaction: exactly `rho > distribution_shift_risk`, encoded as `1.0` when `rho` is greater than `distribution_shift_risk`, otherwise `0.0`.

## Thresholds

No threshold tuning after outcomes. The only interaction threshold is strict greater-than. The literal product is logged but not a primary feature.

## Scoring

Primary score: Brier gain over `K+rho+A1+old_A`. Secondary score: prospective R2. Tertiary: calibration error and AUC.

## Success Criteria

Success requires all of the following on a new cloud-only panel: at least `120` rows, at least `3` cloud model families, no Codex/Ollama/local/self-hosted/quantized/edge rows, R2 improvement at least `0.01`, Brier-gain improvement at least `0.003`, and positive improvement in leave-one-family-out scoring.
