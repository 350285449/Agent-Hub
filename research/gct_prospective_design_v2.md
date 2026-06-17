# GCT Prospective Design v2

Trial id: `gct-prospective-cloud-2026-06-17-v2`. Frozen seed: `20260617`. Frozen panel: `research/gct_prospective_dataset_v2.jsonl`.

## Status

This file freezes the first valid prospective evaluation design. The prior 16-row panel is excluded from adjudication and is not used for row generation, scoring, fitting, or conclusion selection.

The v2 panel contains 200 fresh rows, balanced by task family and assigned before execution. The panel is frozen but not marked complete until every row has auditable cloud execution metadata, a trace ledger, and an outcome label from the frozen rubric.

## Design

| dimension | value |
| --- | --- |
| rows frozen | 200 |
| minimum completed rows required | 200 |
| reuse/replay rows | 0 admitted |
| execution mode | cloud models only |
| control | 100 |
| treatment | 100 |
| holdout rows | 60 |
| training rows | 140 |

## Family Balance

| family | frozen rows |
| --- | --- |
| coding | 50 |
| reasoning | 50 |
| research | 50 |
| agentic | 50 |

## Cloud Family Balance

| cloud model family | frozen rows |
| --- | --- |
| ollama-kimi-cloud | 40 |
| ollama-glm-cloud | 40 |
| ollama-qwen-cloud | 40 |
| ollama-nemotron-cloud | 40 |
| ollama-gemma-cloud | 40 |

## Prospective Freeze Rules

- Dataset rows are frozen before any v2 outcome is observed.
- Model-family assignment, arm assignment, holdout status, evidence units, and success rubrics are frozen in the row file.
- A run is completed only if the selected model is one of the five cloud model families and the response includes raw provider/model metadata.
- Local echo, local research, local OpenAI-compatible models, Codex CLI, and replayed historical traces are disallowed.
- Rows with missing instrumentation are retained as invalid/incomplete, not imputed.

## Validity Gates

The trial is invalid for theory adjudication unless all of these hold:

- 200 completed cloud runs.
- At least four populated cloud model families.
- At least 40 completed rows per task family.
- No control-family success saturation above 95%.
- True event-level GAR is measured from the action ledger.
- The causal intervention is delivered before the first commitment event.
- Outcome scoring is independent of GAR and commitment scoring.
