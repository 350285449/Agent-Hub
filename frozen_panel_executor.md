# Frozen Panel Executor

Status: implemented.

Executor:

```text
scripts/frozen_panel_executor.py
```

Frozen dataset:

```text
research/gct_prospective_dataset_v2.jsonl
```

## Execution Modes

Dry-run instrumentation validation:

```powershell
python scripts\frozen_panel_executor.py --limit 200
```

Real cloud execution:

```powershell
python scripts\frozen_panel_executor.py --limit 200 --execute
```

The executor uses cloud-only routing in execution mode. It requires enabled agents whose provider type is `ollama-cloud` and whose model name ends in `:cloud`.

## Per-Row Outputs

For each frozen row:

- raw provider trace
- JSONL event ledger
- GAR metrics
- commitment metrics
- outcome metrics

The panel summary is written to:

```text
.agent-hub/research/gct_frozen_panel_runs/panel_execution_summary.json
```

## Outcome Metrics

Outcome metrics are stored separately from GAR and commitment metrics. The current implemented scorer uses frozen evidence-unit coverage and marks dry-run rows as `dry_run_no_outcome: true`.

