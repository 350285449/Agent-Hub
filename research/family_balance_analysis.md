# Family Balance Analysis

The tournament was balanced before scoring: each task family contributes 36 rows, each model family contributes 36 rows, and each task benchmark contributes 12 rows.

## Task-Family Balance

| task family | rows | success rate | mean GAR | GAR success gap | mean commitment | grounding density | E2A latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| agentic | 36 | 0.75 | 0.560401 | 0.058966 | 0.546372 | 0.812245 | 0.318858 |
| coding | 36 | 0.944444 | 0.66856 | 0.063549 | 0.468418 | 0.831168 | 0.27248 |
| reasoning | 36 | 0.833333 | 0.598432 | 0.056937 | 0.487641 | 0.795345 | 0.303953 |
| research | 36 | 0.416667 | 0.517672 | 0.039257 | 0.495446 | 0.767899 | 0.342515 |

## Model-Family Balance

| model family | rows | success rate | mean GAR | GAR success gap | mean commitment | grounding density | E2A latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| anthropic | 36 | 0.805556 | 0.596525 | 0.104138 | 0.503094 | 0.803033 | 0.305432 |
| google | 36 | 0.611111 | 0.578983 | 0.078931 | 0.50385 | 0.79869 | 0.31668 |
| nvidia | 36 | 0.638889 | 0.564544 | 0.076444 | 0.49962 | 0.788591 | 0.321413 |
| openai | 36 | 0.888889 | 0.605012 | 0.125705 | 0.491314 | 0.816342 | 0.29428 |

## Benchmark Balance

| benchmark | rows | success rate | mean GAR | GAR success gap | mean commitment | grounding density | E2A latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| api-compat | 12 | 1 | 0.675211 | 0 | 0.473444 | 0.812263 | 0.256968 |
| claim-audit | 12 | 0.333333 | 0.527166 | 0.072508 | 0.486839 | 0.770504 | 0.334959 |
| constraint-planning | 12 | 0.833333 | 0.591522 | 0.079695 | 0.474833 | 0.785479 | 0.302136 |
| counterexample | 12 | 0.75 | 0.562371 | 0.028347 | 0.493676 | 0.770674 | 0.317383 |
| evidence-synthesis | 12 | 0.416667 | 0.529895 | 0.051616 | 0.499731 | 0.77721 | 0.33782 |
| patch-defect | 12 | 0.833333 | 0.659667 | 0.061351 | 0.474149 | 0.835363 | 0.284241 |
| proof-check | 12 | 0.916667 | 0.641404 | 0.009869 | 0.494413 | 0.829882 | 0.292341 |
| route-repair | 12 | 0.833333 | 0.568808 | 0.025056 | 0.537337 | 0.81707 | 0.308627 |
| source-triangulation | 12 | 0.5 | 0.495953 | 0.010272 | 0.499769 | 0.755983 | 0.354766 |
| test-generation | 12 | 1 | 0.6708 | 0 | 0.457663 | 0.845877 | 0.27623 |
| tool-sequence | 12 | 0.75 | 0.566335 | 0.136079 | 0.558208 | 0.810811 | 0.323745 |
| workflow-recovery | 12 | 0.666667 | 0.546059 | 0.010251 | 0.543571 | 0.808855 | 0.324201 |

## Determination

The prior missing-research and underpowered-agentic weaknesses are structurally addressed by equal family coverage. The new limiting factor is not family absence; it is residual benchmark variation and the absence of live provider credentials for a true fresh prospective cloud batch.
