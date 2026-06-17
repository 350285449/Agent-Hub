# Experiment Runner

## Current State

Agent-Hub has two runner families:

- `agent_hub.research.experiment_runner`: local deterministic context-ablation runner.
- `scripts/frozen_panel_executor.py`: frozen GCT panel runner with deterministic run IDs, row directories, JSONL event ledgers, malformed-output quarantine, structured-output validation, and readiness certification.

The frozen-panel executor is the correct base for execution-ready cloud experimentation.

## Requirements Assessment

| Requirement | Current Status | Evidence | Gap |
| --- | --- | --- | --- |
| Frozen panels | Partial | `research/gct_prospective_dataset_v2.jsonl`, `validate_frozen_panel_rows()` | Certification requires exactly 200 valid rows; live execution not proven |
| Distributed execution | Missing | Runner is single-process loop | Needs shard assignment, worker leases, and central result merge |
| Resume support | Missing/partial | Per-row output directories exist | Runner deletes existing `events.jsonl`, so completed rows are not resumable |
| Failure recovery | Partial | Provider retry/failover, quarantine, per-row failure status | Needs resumable retry policy and idempotent row state machine |
| Deterministic logging | Partial | Deterministic `panel_run_id()`, JSONL ledgers, sorted frozen order | Wall-clock timestamps remain nondeterministic; no manifest lock for config/provider versions |

## Execution-Ready Design

### Row State Machine

Each frozen row should have a durable state file:

```json
{
  "row_id": "row_001",
  "run_id": "gctrun_...",
  "status": "pending|leased|running|completed|failed|quarantined",
  "attempt": 1,
  "worker_id": "worker-a",
  "lease_expires_at": 1781720000.0,
  "input_hash": "sha256...",
  "config_hash": "sha256...",
  "events_path": "...",
  "result_path": "..."
}
```

### Distributed Execution

Workers should claim rows atomically from a shared state backend:

- Local mode: file lock per row.
- Cloud mode: Redis, Postgres, S3 object locks, or queue leases.
- Worker command: `agent-hub experiments run --panel gct-v2 --shard auto --resume`.

### Resume Rules

- Completed rows are skipped if `input_hash`, `schema_hash`, and `config_hash` match.
- Failed rows retry only if failure class is retryable.
- Quarantined rows never count as completed until manually released or repaired.
- Existing event ledgers are append-only; no automatic unlink on resume.

### Failure Recovery

Failure classes:

- Retry same provider: malformed JSON, timeout, transient 5xx, output token limit.
- Fail over provider: quota, rate limit, model unavailable, schema unsupported.
- Quarantine row: schema invalid after repair attempts, unresolved evidence refs, commitment during pre-commit.
- Abort panel: frozen panel hash mismatch, replay/synthetic input, provider set not cloud-only.

### Deterministic Logging

Every row must emit:

- `manifest.json`: code version, config hash, dataset hash, schema hash, seed, worker id.
- `events.jsonl`: append-only instrumentation events.
- `provider_attempts.jsonl`: raw provider attempt metadata.
- `raw_trace.json`: normalized trace.
- `outcome_metrics.json`, `gar.json`, `commitment_metrics.json`.
- `certification.json`: row-level gate result.

## Implementation Order

1. Stop deleting existing event ledgers when `--resume` is enabled.
2. Add row state files and completed-row skip logic.
3. Add file-lock local distributed mode.
4. Add provider-attempt ledger.
5. Add manifest hashes.
6. Add optional Redis/Postgres/S3 lease backend.
7. Add panel merge and certification command.

## Readiness Decision

The runner is suitable for dry-run validation and small sequential pilots. It is not yet execution-ready for large-scale cloud experimentation because distributed execution and resume are missing.

