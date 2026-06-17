# GCT Necessity Test

## Counterexample Search

| counterexample class | rows |
| --- | --- |
| low grounding + success | 0 |
| poor commitment + success | 4 |

## Examples

| task | family | grounding | commitment | success |
| --- | --- | --- | --- | --- |
| gct-coding-002 | coding | 1 | 0.45 | 1 |
| gct-reasoning-003 | reasoning | 0.5625 | 0.15 | 1 |
| gct-agentic-004 | agentic | 1 | 0.45 | 1 |
| gct-research-002 | research | 0.55 | 0 | 1 |

## Determination

Grounding and commitment are not logically necessary if any counterexample row exists. They are practically necessary only if counterexamples are rare and ablations lose holdout performance.
