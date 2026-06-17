# Missing Primitive Investigation

Scope: Cloud-only aligned rows: 918 of 1091. Aligned exclusions: 173 rows by model {'gpt-5.5': 143, 'gemma4:31b-cloud': 10, 'nemotron-3-super:cloud': 10, 'kimi-k2.6:cloud': 10} and provider {'codex-cli': 143, 'ollama-cloud': 30}. Upstream strict audit additionally reported 11280 local deterministic rows, 2 timeout-only rows, and exclusion reasons {'duplicate task/model/context tuple': 5, 'local Ollama or otherwise disallowed model': 771, 'local deterministic proof row': 11280, 'provider failure/auth/subscription': 18, 'synthetic or derived benchmark row without allowed model provenance': 1380, 'timeout-only row with no usable output': 2, 'unsuccessful execution or unusable validation result': 4}.

## Candidate Scan

| candidate | rows | incremental R2 over K+rho+A | residual corr | timing risk |
| --- | --- | --- | --- | --- |
| Actionability | 918 | 0.001281 | 0.052112 | pre/mixed |
| E9 | 918 | 0.068862 | 0.301681 | post-output or contaminated |
| Route Friction | 878 | 0.000788 | 0.029784 | pre/mixed |
| Retrieval Selectivity | 878 | 0.000034 | 0.00251 | pre/mixed |
| Compatibility v2 | 878 | 0.003652 | 0.061319 | pre/mixed |
| EAC | 878 | 0.000631 | 0.036102 | pre/mixed |
| referenced_files | 918 | 0.058925 | 0.310201 | post-output or contaminated |
| selected_file_count | 918 | 0.001452 | 0.054547 | pre/mixed |
| context_budget | 918 | 0.000534 | -0.016226 | pre/mixed |

## Evidence

Only E9 and referenced-file count produce material residual gains, and both observe generated behavior. Clean candidates such as Compatibility v2, Route Friction, Retrieval Selectivity, and Actionability add little after K+rho+A.

## Counter-Evidence

Output-side evidence use is real predictive signal. If a pre-run instrument can predict that behavior without reading the output, it could become a fourth primitive candidate.

## Uncertainty

Current candidates are not deconfounded from K/rho/A well enough to promote. Provider/model exact crosses are incomplete, and prospective cloud-only evidence is narrow.

## Falsification Attempt

Deconfounding fails the candidate set: when post-output traces are removed, no candidate adds even 0.01 R2 over K+rho+A. The fourth primitive search remains open, but no fourth primitive survives this pass.
