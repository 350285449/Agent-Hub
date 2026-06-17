# Prediction Failure Analysis

Scope: Cloud-only aligned rows: 918 of 1091. Aligned exclusions: 173 rows by model {'gpt-5.5': 143, 'gemma4:31b-cloud': 10, 'nemotron-3-super:cloud': 10, 'kimi-k2.6:cloud': 10} and provider {'codex-cli': 143, 'ollama-cloud': 30}. Upstream strict audit additionally reported 11280 local deterministic rows, 2 timeout-only rows, and exclusion reasons {'duplicate task/model/context tuple': 5, 'local Ollama or otherwise disallowed model': 771, 'local deterministic proof row': 11280, 'provider failure/auth/subscription': 18, 'synthetic or derived benchmark row without allowed model provenance': 1380, 'timeout-only row with no usable output': 2, 'unsuccessful execution or unusable validation result': 4}.

## Major False Positives

| task | model | repository | category | predicted | actual - predicted |
| --- | --- | --- | --- | --- | --- |
| ytdl-site-analysis-01 | nemotron-3-super:cloud | ytdl_site | analysis | 0.379 | -0.379 |
| ytdl-site-analysis-01 | nemotron-3-super:cloud | ytdl_site | analysis | 0.379 | -0.379 |
| ytdl-site-analysis-01 | nemotron-3-super:cloud | ytdl_site | analysis | 0.379 | -0.379 |
| face-bug_fix-01 | nemotron-3-super:cloud | face | bug_fix | 0.367 | -0.367 |
| face-bug_fix-01 | nemotron-3-super:cloud | face | bug_fix | 0.367 | -0.367 |
| face-bug_fix-01 | nemotron-3-super:cloud | face | bug_fix | 0.367 | -0.367 |
| agent-hub-analysis-01 | nemotron-3-super:cloud | Agent-Hub | analysis | 0.358 | -0.358 |
| agent-hub-analysis-01 | nemotron-3-super:cloud | Agent-Hub | analysis | 0.358 | -0.358 |
| agent-hub-analysis-01 | nemotron-3-super:cloud | Agent-Hub | analysis | 0.358 | -0.358 |
| face-analysis-01 | nemotron-3-super:cloud | face | analysis | 0.354 | -0.354 |

## Major False Negatives

| task | model | repository | category | predicted | actual - predicted |
| --- | --- | --- | --- | --- | --- |
| ytdl-site-architecture-01 | nemotron-3-super:cloud | ytdl_site | architecture | 0.252 | 0.748 |
| face-testing-01 | nemotron-3-super:cloud | face | testing | 0.294 | 0.706 |
| face-testing-02 | nemotron-3-super:cloud | face | testing | 0.294 | 0.706 |
| face-testing-01 | nemotron-3-super:cloud | face | testing | 0.294 | 0.706 |
| agent-hub-refactor-01 | nemotron-3-super:cloud | Agent-Hub | refactor | 0.295 | 0.705 |
| ytdl-site-testing-01 | nemotron-3-super:cloud | ytdl_site | testing | 0.305 | 0.695 |
| ytdl-site-refactor-01 | nemotron-3-super:cloud | ytdl_site | refactor | 0.311 | 0.689 |
| face-analysis-01 | nemotron-3-super:cloud | face | analysis | 0.354 | 0.646 |
| agent-hub-analysis-01 | nemotron-3-super:cloud | Agent-Hub | analysis | 0.358 | 0.642 |
| agent-hub-analysis-01 | nemotron-3-super:cloud | Agent-Hub | analysis | 0.358 | 0.642 |

## Failure Clusters

| axis | cluster | rows | mean residual | residual sd |
| --- | --- | --- | --- | --- |
| category | bug_fix | 3 | -0.366595 | 0.0 |
| category | architecture | 10 | -0.140941 | 0.296397 |
| category | refactor | 13 | -0.140765 | 0.357415 |
| repository | face | 21 | -0.120784 | 0.396238 |
| category | testing | 21 | -0.098488 | 0.389135 |
| category | analysis | 20 | 0.086622 | 0.496284 |
| repository | Agent-Hub | 28 | -0.083818 | 0.385845 |
| context_budget | 25.0 | 30 | -0.082517 | 0.406539 |
| model | nemotron-3-super:cloud | 67 | -0.069775 | 0.414874 |
| context_budget | 0.0 | 34 | -0.06808 | 0.415406 |
| context_budget | 50.0 | 3 | 0.038417 | 0.471405 |
| repository | ytdl_site | 18 | 0.011579 | 0.464708 |

## Failure Hypotheses

False positives mostly indicate that historical K/rho/A over-credit cells where execution reliability, benchmark ambiguity, or repository-specific constraints dominate. False negatives indicate the opposite: coarse rho and A under-credit recoverable tasks where the model can exploit local structure despite low prior compatibility.

## Attack On Positive Results

The strongest attack is timing leakage. K and rho are historical outcome summaries, and A still mixes clean access with traces of evidence use. If a future frozen set cannot reproduce the holdout ordering, then the framework is explanatory bookkeeping, not predictive science.
