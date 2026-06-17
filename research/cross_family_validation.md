# Cross-Family Validation

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Validation is limited by the current cloud-only panel: coding and reasoning have usable rows, agentic is underpowered, and research has no aligned cloud rows in the existing family slice.

## Candidate Cross-Family Stability

| candidate | model CV | task-family CV | benchmark CV | time-period CV | model spread | task spread | benchmark spread | time spread |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| grounded-action ratio | 0.919593 | 0.081029 | 0.535379 | 0.348745 | 0.52116 | 0.060861 | 0.483963 | 0.288506 |
| state-transition count | 0.114693 | 0.062556 | 0.171538 | 0.056709 | 0.161508 | 0.094949 | 0.371519 | 0.09597 |
| grounding latency | 0.486655 | 0.497143 | 0.408644 | 0.358932 | 0.633172 | 0.632424 | 0.694937 | 0.6307 |
| recovery event | 1.274124 | 0.726432 | 1.757928 | 1.192755 | 0.029056 | 0.018182 | 0.133333 | 0.08 |
| branch collapse | 0.992616 | 0.730286 | 1.63722 | 1.732051 | 0.152542 | 0.098202 | 0.189873 | 0.109067 |
| evidence-to-action latency | 0.739361 | 0.711688 | 0.776697 | 1.025164 | 0.509224 | 0.488485 | 0.574684 | 0.481932 |
| verification success | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

## Available Family Rows

| task family | rows | success rate | branch-collapse share | mean commitment pct | success commitment pct | failure stuck share |
| --- | --- | --- | --- | --- | --- | --- |
| agentic | 30 | 0.266667 | 0.0 | n/a | n/a | 0.954545 |
| coding | 723 | 0.603043 | 0.289073 | 50.0 | 50.0 | 0.299652 |
| reasoning | 165 | 0.539394 | 0.30303 | 50.0 | 50.0 | 0.355263 |

## Determination

Common dynamics are visible in coding and reasoning: evidence must be converted into grounded action, and mid-run convergence matters. Family-specific dynamics remain material: coding is dominated by file/edit/verifier pathways, reasoning by argument linkage, and agentic by action sequencing. Research cannot validate in this corpus because the aligned cloud slice has no research rows. This blocks any strong universality claim.
