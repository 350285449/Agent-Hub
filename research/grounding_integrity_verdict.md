# Grounding Integrity Verdict

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Answers

1. Does Grounding Integrity survive benchmark shifts? Yes, with caveats.
2. Does it survive model shifts? Yes.
3. Does it survive family shifts? Yes.
4. Does it survive alternative definitions? Yes.
5. Does it survive deconfounding? Yes.
6. Does it survive randomization? Yes.
7. Does it survive temporal testing? Yes.
8. Is the recovery estimate robust? Moderately.
9. What is the strongest remaining weakness? The strongest remaining weakness is causal status: Grounding Integrity survives as a diagnostic control signal, but the corpus still cannot prove that interventions will recover the estimated failures without a frozen live repair experiment.

## Final Requirement

Selected verdict: **C. Grounding Integrity is robust.**

## Evidence For

- Combined model remains above baseline in the main holdout/randomization comparison: 0.591585 R2 real versus 0.410629 shuffled mean.
- Adversarial all-control combined delta is 0.73577, after K/rho/A1-A3 plus task-family, model-family, and benchmark controls.
- Alternative action/score metrics retain positive holdout gains across the strongest variants: top sensitivity delta 0.139998.
- Realistic intervention estimate is 0.326857 of all failures.

## Evidence Against

- Prospective reconstruction remains weak in the prior assessment, so this is stronger as online diagnostic evidence than as pre-execution forecasting.
- Benchmark and model-family holdouts are uneven; sparse groups make some apparent stability underpowered.
- Several Grounding Integrity fields are execution-stage diagnostics, so they should not be sold as clean pre-run primitives.
- Recovery estimates are counterfactual and depend on repair efficacy assumptions that have not been validated in a live intervention trial.

## Final Determination

The falsification run does not destroy Grounding Integrity. It does demote any overclaim that this is a clean pre-run law. The result survives best as a runtime diagnostic and control signal: strong enough for subsystem design, not yet strong enough to claim validated causal recovery without a frozen intervention trial.
