# GCT Prospective Dataset

Trial id: `gct-prospective-cloud-2026-06-17-v1`. Frozen seed: `20260617`. Dataset file: `research/gct_prospective_dataset.jsonl`.

## Scope

This is a fresh cloud-only prospective panel. Prompts were generated for this run and are marked as not replay rows and not reused benchmark rows. Prior `research/` and `.agent-hub/research/` rows were not used as outcomes.

| measure | value |
| --- | --- |
| frozen rows | 16 |
| successful live cloud rows | 16 |
| cloud-only enforcement | selected agent must be configured ollama-cloud / -cloud |
| blocked rows | 0 |

## Balanced Coverage

| family | rows | success rate |
| --- | --- | --- |
| agentic | 4 | 1 |
| coding | 4 | 0.75 |
| reasoning | 4 | 0.75 |
| research | 4 | 0.75 |

## Failure Handling

Rows with `ok=false` are retained as execution failures, not silently removed. They are excluded from model fitting because no trajectory measurements exist.
