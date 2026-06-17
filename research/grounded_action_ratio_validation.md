# Grounded-Action Ratio Validation

## Transfer Checks

| axis | coefficient of variation | positive success gaps in every group | verdict |
| --- | --- | --- | --- |
| task family | 0.094565 | True | weak pass |
| model family | 0.02672 | True | weak pass |
| benchmark | 0.099981 | False | fail |

## Benchmark-Level Stability

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

The grounded-action ratio survives balanced research and agentic coverage as a directional invariant candidate. The signal is not merely a coding artifact: research and agentic rows retain positive success gaps. The evidence remains weak rather than strong because benchmark dependence is still visible and the result is a frozen replay tournament rather than live multi-provider prospective execution.
