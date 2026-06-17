# Fresh Invariant Results

Scope: 144 fresh frozen cloud-only replay rows. Balanced coverage: 36 rows each for coding, reasoning, research, and agentic tasks.

## Overall Metric Separation

| metric | success mean | failure mean | success-failure gap |
| --- | --- | --- | --- |
| grounded-action ratio | 0.610624 | 0.51832 | 0.092303 |
| grounding density | 0.815274 | 0.763699 | 0.051575 |
| evidence-to-action latency | 0.29825 | 0.340697 | -0.042447 |
| uncertainty collapse point | 0.480679 | 0.50434 | -0.023661 |

## Model Comparison

| model | features | R2 proxy | Brier skill | mean predicted success |
| --- | --- | --- | --- | --- |
| invariant model | grounded_action_ratio | 0.242448 | 0.019899 | 0.528921 |
| grounding integrity model | grounded_action_ratio, grounding_density, evidence_to_action_latency | 0.17959 | 0.002995 | 0.551082 |
| trajectory model | trajectory_score, commitment_point, uncertainty_collapse_point | 0.030891 | -0.177509 | 0.554315 |
| static capability model | static_capability | 0.012754 | -0.377368 | 0.510234 |

## Task-Family Results

| task family | rows | success rate | mean GAR | GAR success gap | mean commitment | grounding density | E2A latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| agentic | 36 | 0.75 | 0.560401 | 0.058966 | 0.546372 | 0.812245 | 0.318858 |
| coding | 36 | 0.944444 | 0.66856 | 0.063549 | 0.468418 | 0.831168 | 0.27248 |
| reasoning | 36 | 0.833333 | 0.598432 | 0.056937 | 0.487641 | 0.795345 | 0.303953 |
| research | 36 | 0.416667 | 0.517672 | 0.039257 | 0.495446 | 0.767899 | 0.342515 |

## Model-Family Results

| model family | rows | success rate | mean GAR | GAR success gap | mean commitment | grounding density | E2A latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| anthropic | 36 | 0.805556 | 0.596525 | 0.104138 | 0.503094 | 0.803033 | 0.305432 |
| google | 36 | 0.611111 | 0.578983 | 0.078931 | 0.50385 | 0.79869 | 0.31668 |
| nvidia | 36 | 0.638889 | 0.564544 | 0.076444 | 0.49962 | 0.788591 | 0.321413 |
| openai | 36 | 0.888889 | 0.605012 | 0.125705 | 0.491314 | 0.816342 | 0.29428 |

## Result

Grounded-action ratio transfers directionally across task families and model families. It does not transfer cleanly across every benchmark: two coding benchmark cells are all-success cells with no estimable success/failure gap, and several benchmark gaps are small. This blocks a strong invariant claim and keeps the result at weak-candidate strength.
