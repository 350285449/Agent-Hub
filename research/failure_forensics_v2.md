# Failure Forensics v2

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Model used: clean post-retrieval `K+rho+A1-A3`; post-run diagnostics are excluded.

## Largest False Positives

| task | model | repository | category | context | predicted | actual - predicted |
| --- | --- | --- | --- | --- | --- | --- |
| face-bug_fix-01 | nemotron-3-super:cloud | face | bug_fix | 0.0 | 0.399 | -0.399 |
| face-bug_fix-01 | nemotron-3-super:cloud | face | bug_fix | 0.0 | 0.399 | -0.399 |
| face-bug_fix-01 | nemotron-3-super:cloud | face | bug_fix | 0.0 | 0.399 | -0.399 |
| face-analysis-01 | nemotron-3-super:cloud | face | analysis | 0.0 | 0.384 | -0.384 |
| face-analysis-01 | nemotron-3-super:cloud | face | analysis | 0.0 | 0.384 | -0.384 |
| face-analysis-01 | nemotron-3-super:cloud | face | analysis | 25.0 | 0.384 | -0.384 |
| face-analysis-01 | nemotron-3-super:cloud | face | analysis | 25.0 | 0.384 | -0.384 |
| face-analysis-01 | nemotron-3-super:cloud | face | analysis | 0.0 | 0.384 | -0.384 |
| agent-hub-analysis-01 | nemotron-3-super:cloud | Agent-Hub | analysis | 0.0 | 0.377 | -0.377 |
| agent-hub-analysis-01 | nemotron-3-super:cloud | Agent-Hub | analysis | 25.0 | 0.377 | -0.377 |
| agent-hub-analysis-01 | nemotron-3-super:cloud | Agent-Hub | analysis | 25.0 | 0.377 | -0.377 |
| ytdl-site-analysis-01 | nemotron-3-super:cloud | ytdl_site | analysis | 25.0 | 0.361 | -0.361 |

## Largest False Negatives

| task | model | repository | category | context | predicted | actual - predicted |
| --- | --- | --- | --- | --- | --- | --- |
| ytdl-site-architecture-01 | nemotron-3-super:cloud | ytdl_site | architecture | 0.0 | 0.238 | 0.762 |
| ytdl-site-refactor-01 | nemotron-3-super:cloud | ytdl_site | refactor | 25.0 | 0.277 | 0.723 |
| agent-hub-refactor-01 | nemotron-3-super:cloud | Agent-Hub | refactor | 50.0 | 0.278 | 0.722 |
| ytdl-site-testing-01 | nemotron-3-super:cloud | ytdl_site | testing | 0.0 | 0.288 | 0.712 |
| face-testing-01 | nemotron-3-super:cloud | face | testing | 0.0 | 0.315 | 0.685 |
| face-testing-02 | nemotron-3-super:cloud | face | testing | 0.0 | 0.315 | 0.685 |
| face-testing-01 | nemotron-3-super:cloud | face | testing | 25.0 | 0.315 | 0.685 |
| ytdl-site-analysis-01 | nemotron-3-super:cloud | ytdl_site | analysis | 25.0 | 0.361 | 0.639 |
| ytdl-site-analysis-01 | nemotron-3-super:cloud | ytdl_site | analysis | 25.0 | 0.361 | 0.639 |
| ytdl-site-analysis-01 | nemotron-3-super:cloud | ytdl_site | analysis | 0.0 | 0.361 | 0.639 |
| agent-hub-analysis-01 | nemotron-3-super:cloud | Agent-Hub | analysis | 0.0 | 0.377 | 0.623 |
| agent-hub-analysis-01 | nemotron-3-super:cloud | Agent-Hub | analysis | 0.0 | 0.377 | 0.623 |

## Residual Clusters

| axis | cluster | rows | mean residual | residual sd | mean abs error |
| --- | --- | --- | --- | --- | --- |
| error_type | false_negative | 16 | 0.663542 | 0.045233 | 0.663542 |
| category | analysis | 20 | 0.075377 | 0.499176 | 0.489056 |
| context_budget | 50.0 | 3 | 0.055045 | 0.471405 | 0.426096 |
| repository | ytdl_site | 18 | 0.030796 | 0.46489 | 0.426065 |
| repository | face | 21 | -0.147579 | 0.398242 | 0.401932 |
| category | bug_fix | 3 | -0.398693 | 0.0 | 0.398693 |
| context_budget |  | 34 | -0.080765 | 0.419342 | 0.395432 |
| model | nemotron-3-super:cloud | 67 | -0.077699 | 0.417869 | 0.394615 |
| context_budget | 25.0 | 30 | -0.087499 | 0.408153 | 0.390541 |
| category | testing | 21 | -0.111124 | 0.389494 | 0.37459 |
| repository | Agent-Hub | 28 | -0.095037 | 0.385247 | 0.36891 |
| category | refactor | 13 | -0.130578 | 0.363762 | 0.352765 |
| error_type | calibration_error | 51 | -0.310246 | 0.047992 | 0.310246 |
| category | architecture | 10 | -0.148618 | 0.30361 | 0.300968 |

## Recurring Causes

Benchmark effects and model-family effects dominate the prospective errors. Retrieval effects appear after A2/A3, but clean retrieval measurements do not rescue forecasting. Planning proxies are weak. The largest failures are consistent with unstable historical priors and benchmark drift rather than a clean missing primitive.
