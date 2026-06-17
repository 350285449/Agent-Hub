# Randomized Trial Results

Scope: cloud models only. This is the frozen two-arm randomized assignment over the existing cloud corpus.

## Intention-To-Treat Assignment Contrast

| arm | runs | successes | failures | success rate | failure rate | trigger-eligible runs | delivered interventions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Control | 466 | 261 | 205 | 56.0% | 44.0% | 192 | 0 |
| Treatment | 452 | 272 | 180 | 60.2% | 39.8% | 176 | 0 |

## Randomization Balance

| field | value | control runs | treatment runs |
| --- | --- | --- | --- |
| model_family | glm-5.1 | 3 | 3 |
| model_family | google | 209 | 204 |
| model_family | kimi-k2.6 | 3 | 3 |
| model_family | nemotron-3-super | 243 | 234 |
| model_family | qwen | 8 | 8 |
| task_family | architecture | 32 | 28 |
| task_family | coding | 379 | 374 |
| task_family | documentation | 18 | 16 |
| task_family | research | 37 | 34 |

## Result

The randomized groups are frozen and comparable, but the treatment arm has zero delivered interventions in the available corpus. The observed assignment contrast is therefore a random split of historical no-intervention cloud rows, not evidence that the intervention policy was executed.
