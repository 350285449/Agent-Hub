# Fresh Invariant Tournament Design

Freeze timestamp: 2026-06-17. Scope: cloud-only balanced tournament. This run does not perform new theory search, new primitive search, or intervention testing.

Important execution note: no provider API credentials were present in the environment, so the executable artifact is a fresh frozen cloud-only replay tournament over cloud model families and benchmark cells. It excludes local/self-hosted model rows and does not reuse the old imbalanced 918-row panel as decisive evidence.

## Frozen Benchmark Set

| task family | benchmark | coverage | status |
| --- | --- | --- | --- |
| coding | patch-defect | 3 replicates per frozen cloud model | held fixed before scoring |
| coding | api-compat | 3 replicates per frozen cloud model | held fixed before scoring |
| coding | test-generation | 3 replicates per frozen cloud model | held fixed before scoring |
| reasoning | proof-check | 3 replicates per frozen cloud model | held fixed before scoring |
| reasoning | counterexample | 3 replicates per frozen cloud model | held fixed before scoring |
| reasoning | constraint-planning | 3 replicates per frozen cloud model | held fixed before scoring |
| research | source-triangulation | 3 replicates per frozen cloud model | held fixed before scoring |
| research | evidence-synthesis | 3 replicates per frozen cloud model | held fixed before scoring |
| research | claim-audit | 3 replicates per frozen cloud model | held fixed before scoring |
| agentic | tool-sequence | 3 replicates per frozen cloud model | held fixed before scoring |
| agentic | workflow-recovery | 3 replicates per frozen cloud model | held fixed before scoring |
| agentic | route-repair | 3 replicates per frozen cloud model | held fixed before scoring |

Rows frozen before scoring: 144 = 4 task families x 3 benchmarks x 4 cloud model families x 3 replicates.

## Frozen Model List

| model family | model | provider route |
| --- | --- | --- |
| openai | gpt-4o-mini | openai |
| anthropic | claude-3-5-haiku-latest | anthropic |
| google | gemini-2.0-flash | gemini |
| nvidia | nemotron-3-super:cloud | ollama-cloud |

## Frozen Scoring Rules

| quantity | definition | primary use |
| --- | --- | --- |
| grounded-action ratio | share of downstream action tied to surfaced/understood evidence | primary invariant candidate |
| commitment point | execution fraction where the run collapses to a dominant action branch | secondary candidate; expected near 50% |
| uncertainty collapse point | execution fraction where predicted outcome uncertainty materially falls | trajectory timing check |
| evidence-to-action latency | fractional delay between decisive evidence and action linkage | supporting grounding measure; lower is better |
| grounding density | density of evidence-linked actions across the execution trace | supporting grounding measure; higher is better |

## Frozen Invariant Definitions

Strong transfer requires positive grounded-action success gaps in every task family, model family, and benchmark, with mean grounded-action ratio coefficient of variation no higher than 0.10 in each grouping axis. Weak invariant retention requires task-family and model-family transfer, plus benchmark failures being localized and diagnosable rather than a global sign reversal. Commitment remains centered near 50% only if aggregate mean is in [0.45, 0.55] and every task-family and model-family mean is also in that band.
