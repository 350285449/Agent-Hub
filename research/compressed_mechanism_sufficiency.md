# Compressed Mechanism Sufficiency

Scope: cloud models only. No new theories, primitive searches, or large theory tournaments. This file compares the compressed mechanism against the existing model families.

## Model Comparison

| model | interpretation | holdout power | prospective reconstruction | robustness | sufficiency result |
| --- | --- | ---: | ---: | --- | --- |
| `K+rho+A1-A3` | static capability/access baseline | holdout R2 0.416094 | R2 0.006192 | useful baseline, weak prospective | insufficient |
| Grounding Integrity only | grounding/action diagnostics | holdout R2 0.465703 | R2 0.009762 | survives benchmark/model/family shifts with caveats | useful but incomplete |
| Branch Commitment only | prefix collapse/commitment timing | 50% prefix holdout R2 0.632214 | R2 0.109202 | aggregate timing stable, family stability weak | strong diagnostic, incomplete alone |
| Grounding + Branch Commitment | compressed mechanism core | explains conversion plus commitment | best conceptual fit to observed collapse | robust as runtime mechanism | sufficient for most surviving signal |
| Full execution trajectory model | richer retrieval/state/transition model | dynamic event holdout R2 0.604526 | R2 0.078260 | broadest diagnostic coverage | not materially better than compressed core |

## Explanatory Power

The compressed mechanism explains why prior theory families collapsed:

- Decisive Evidence Theory collapses into whether evidence becomes grounding.
- Branch Collapse, Uncertainty Collapse, Execution Lock-In, State Reachability, Information Flow, Runtime Control, Runtime Integrity, and Error Recovery collapse into execution trajectory behavior around grounding and commitment.
- Independent theory gains vanish or turn negative after Grounding Integrity, trajectory, and family controls.

The best summary from the prior collapse analysis remains: evidence must become grounded action before branch commitment, and recovery/control matters mostly as late correction of the same execution path.

## Predictive Power

Pre-run prediction remains weak. `K+rho+A1-A3` reaches only reconstructed prospective R2 0.006192. Broader pre-run models improve holdout more than prospective performance, which is a diagnostic-over-predictive signature.

Runtime prediction is stronger. At 50% execution, prefix features reach holdout R2 0.632214 and prospective R2 0.109202. The predictive jump appears when evidence has had enough time to convert into grounding and branch commitment.

## Holdout Performance

The compressed mechanism is favored on holdout evidence because the important pieces align:

- `K+rho+A1-A3`: holdout R2 0.416094.
- Grounding Integrity combined model: holdout R2 0.591585, a +0.175491 gain over `K+rho+A1-A3`.
- 50% trajectory commitment: holdout R2 0.632214.
- Minimal grounding group: holdout R2 0.612539.
- Full dynamic event model: holdout R2 0.604526.

The full trajectory model does not clearly beat the compressed mechanism. The minimal grounding group plus commitment timing recovers the important signal without needing a larger theory structure.

## Reconstructed Prospective Performance

Prospective reconstruction is positive but modest:

- `K+rho+A1-A3`: R2 0.006192.
- Grounding Integrity combined model: R2 0.069023.
- 50% trajectory commitment: R2 0.109202.
- Minimal grounding group: R2 0.101662.
- Full dynamic event model: R2 0.078260.

This supports the compressed mechanism as the best current runtime candidate, not as a solved pre-run forecasting law.

## Robustness

The mechanism survives the main robustness checks with limits:

- Grounded-action ratio has positive success gaps across task and model families, but benchmark-level stability is uneven.
- Commitment point is near 50% aggregate but drifts by family, especially agentic tasks.
- Grounding Integrity survives deconfounding and randomization checks as a warning signal, but delivered intervention causality is not proven.
- Cross-family validation supports coding and reasoning better than agentic/research slices.

## Determination

The compressed mechanism is sufficient to explain most surviving Agent-Hub outcome signal in the current cloud-only corpus. It outperforms static access/capability baselines and captures the explanatory substance of the full execution trajectory model.

It is not complete. Its main missing piece is causal intervention proof: the randomized artifact assigned treatment, but no treatment interventions were delivered, so recovery causality remains unvalidated.
