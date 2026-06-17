# Mechanism Sufficiency

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Attack: ask whether the compressed mechanism explains most surviving signal without importing a larger theory.

## Core Comparisons

| model | holdout R2 | prospective R2 | prospective Brier gain |
| --- | ---: | ---: | ---: |
| compressed mechanism | 0.641183 | 0.080038 | 0.014549 |
| full dynamic trajectory | 0.611615 | 0.117627 | 0.021382 |
| mechanism without grounding | 0.625139 | 0.058987 | 0.010723 |
| mechanism without commitment | 0.597608 | 0.07479 | 0.013595 |

## Sufficiency Verdict

The compressed mechanism explains most surviving signal if the target is runtime diagnosis rather than pre-run forecasting. The full dynamic model is competitive, but it does not make the compressed core obsolete; most of its advantage is trajectory detail around the same evidence-grounding-commitment path.

The mechanism is not fully sufficient as a causal intervention law. Delivered repair causality remains the missing test.
