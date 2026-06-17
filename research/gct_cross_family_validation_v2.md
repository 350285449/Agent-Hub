# GCT Cross-Family Validation v2

## Task-Family Splits

| task family | frozen rows | minimum completed required |
| --- | --- | --- |
| coding | 50 | 40 |
| reasoning | 50 | 40 |
| research | 50 | 40 |
| agentic | 50 | 40 |

## Cloud-Model-Family Splits

| cloud model family | frozen rows | minimum completed required |
| --- | --- | --- |
| ollama-kimi-cloud | 40 | 20 |
| ollama-glm-cloud | 40 | 20 |
| ollama-qwen-cloud | 40 | 20 |
| ollama-nemotron-cloud | 40 | 20 |
| ollama-gemma-cloud | 40 | 20 |

## Robustness Rule

GCT survives across task families only if Model D beats Model A or retains Model E signal in coding, reasoning, research, and agentic splits separately. It survives across model families only if the direction is non-negative in at least four cloud model families with no single-family dependence.

## Current Status

Frozen coverage is balanced enough to run the test, but execution results are not yet present.
