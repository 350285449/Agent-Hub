# Accessibility 2.0

Accessibility should be decomposed by timing. A clean pre-run A can include evidence existence, retrieval, and surfacing. Understanding/linking are diagnostic unless measured before answer generation by a frozen evaluator.

| component | corr | AUC | single-var R2 | redundancy vs K/rho/A | timing |
| --- | --- | --- | --- | --- | --- |
| A1_exists | 0.091766 | 0.519249 | 0.008421 | 0.081794 | pre-run benchmark/task label |
| A2_retrieved | 0.146315 | 0.580762 | 0.021408 | 0.731963 | pre-generation retrieval |
| A3_surfaced | 0.049948 | 0.556372 | 0.002495 | 0.492643 | pre-generation context allocation |
| A4_understood | 0.408766 | 0.714202 | 0.16709 | 0.391163 | post-generation proxy in current data |
| A5_linked_to_action | 0.606513 | 0.889898 | 0.367858 | 0.387855 | post-generation diagnostic in current data |

- Original current Evidence Access A corr: `0.249122`, AUC: `0.677463`.
- Old context-volume A corr: `0.145217`, AUC: `0.579915`.
- A2.0 component-only R2: `0.463645`.
- K+rho+A2.0 component R2: `0.59362`.

Causal plausibility: A1-A3 are plausible pre-run accessibility causes. A4-A5 are stronger predictors only when they use output-side traces, so they should be treated as post-run diagnostics unless collected by independent pre-run annotation.
