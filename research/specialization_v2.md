# Specialization v2

Scope: Cloud-only aligned rows: 918 of 1091. Aligned exclusions: 173 rows by model {'gpt-5.5': 143, 'gemma4:31b-cloud': 10, 'nemotron-3-super:cloud': 10, 'kimi-k2.6:cloud': 10} and provider {'codex-cli': 143, 'ollama-cloud': 30}. Upstream strict audit additionally reported 11280 local deterministic rows, 2 timeout-only rows, and exclusion reasons {'duplicate task/model/context tuple': 5, 'local Ollama or otherwise disallowed model': 771, 'local deterministic proof row': 11280, 'provider failure/auth/subscription': 18, 'synthetic or derived benchmark row without allowed model provenance': 1380, 'timeout-only row with no usable output': 2, 'unsuccessful execution or unusable validation result': 4}.

## Evidence

| rho dimension proxy | corr | AUC | single-var R2 | redundancy vs K/A |
| --- | --- | --- | --- | --- |
| agent_execution | 0.649966 | 0.915319 | 0.422456 | 0.534782 |
| reasoning | 0.463698 | 0.79079 | 0.215016 | 0.391251 |
| coding | 0.416345 | 0.740265 | 0.173343 | 0.296717 |
| planning | 0.356243 | 0.743973 | 0.126909 | 0.230463 |
| retrieval | 0.351946 | 0.674092 | 0.123866 | 0.714606 |
| long_context | 0.317418 | 0.660998 | 0.100754 | 0.483081 |
| research | 0.0 | 0.5 | 0.0 | 0.0 |
| math | 0.0 | 0.5 | 0.0 | 0.0 |
| tool_use | 0.0 | 0.5 | 0.0 | 0.0 |

rho is the strongest reliability-adjusted variable in the cloud-only audit: corr 0.685836 with reliability 0.678 when ranked against measured competitors.

## Counter-Evidence

rho is still an outcome-derived model-task residual, and several subdimensions are actually proxies for output behavior or category labels. Removing rho costs only 0.024088 R2.

## Uncertainty

The decomposition is observable but not yet causally clean. Repository affinity, tool affinity, and long-context affinity are confounded with model family and benchmark provenance.

## Falsification Attempt

Adding Compatibility v2, Route Friction, Retrieval Selectivity, and Actionability to K+rho+A raises R2 only from 0.50962 to 0.513246. This argues against a hidden fourth factor inside current measured variables, but it also shows rho is not independently settled.
