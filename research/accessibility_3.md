# Accessibility 3

Scope: Cloud-only aligned rows: 918 of 1091. Aligned exclusions: 173 rows by model {'gpt-5.5': 143, 'gemma4:31b-cloud': 10, 'nemotron-3-super:cloud': 10, 'kimi-k2.6:cloud': 10} and provider {'codex-cli': 143, 'ollama-cloud': 30}. Upstream strict audit additionally reported 11280 local deterministic rows, 2 timeout-only rows, and exclusion reasons {'duplicate task/model/context tuple': 5, 'local Ollama or otherwise disallowed model': 771, 'local deterministic proof row': 11280, 'provider failure/auth/subscription': 18, 'synthetic or derived benchmark row without allowed model provenance': 1380, 'timeout-only row with no usable output': 2, 'unsuccessful execution or unusable validation result': 4}.

## Result

| model | R2 |
| --- | ---: |
| K+rho+current A | 0.50962 |
| K+rho+pre-run A1-A3 | 0.506963 |
| K+rho+full A1-A5 | 0.609926 |

## Evidence

| component | corr | 95% corr CI | AUC | single-var R2 | timing |
| --- | --- | --- | --- | --- | --- |
| old_A | 0.110156 | [0.039, 0.164] | 0.56166 | 0.012134 | mixed/pre-existing |
| A | 0.22231 | [0.164, 0.276] | 0.659465 | 0.049422 | mixed/pre-existing |
| A1_exists | 0.083662 | [0.0, 0.139] | 0.517098 | 0.006999 | pre-run benchmark/task label |
| A2_retrieved | 0.101447 | [0.034, 0.173] | 0.554238 | 0.010292 | pre-generation retrieval |
| A3_surfaced | 0.024211 | [-0.035, 0.08] | 0.536968 | 0.000586 | pre-generation context allocation |
| A4_understood | 0.436311 | [0.375, 0.479] | 0.725416 | 0.190368 | post-generation proxy in current data |
| A5_linked_to_action | 0.634746 | [0.591, 0.678] | 0.893358 | 0.402903 | post-generation diagnostic in current data |

Current A beats the old context-volume proxy, and the full A1-A5 trace raises explanatory power by 0.100306 R2 over K+rho+A.

## Counter-Evidence

Pre-run A1-A3 alone lowers R2 by -0.002657 versus current A. The strongest accessibility components are A4 and A5, which are currently post-generation diagnostics.

## Uncertainty

The clean causal part of accessibility is weakly measured. The full trace is predictive, but some of that signal may be evidence-use outcome behavior rather than pre-run access.

## Falsification Attempt

If post-generation A4/A5 are banned, accessibility improvement disappears. Accessibility survives as a measurement target, but not as a fully validated prospective pre-run primitive.
