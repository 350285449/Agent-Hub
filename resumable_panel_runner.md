# Resumable Panel Runner

Checkpoint path: `.agent-hub\research\gct_balanced_live_50_preflight\panel_checkpoint.json`.

- The runner writes `row_result.json` after every row.
- Accepted rows are recorded in `accepted_row_ids` and skipped on resume.
- Quarantined rows are recorded in `quarantined_row_ids` and skipped only with that explicit checkpoint record.
- The summary never ingests malformed provider payloads; event ingestion happens only after strict validation succeeds.
- Duplicate accepted rows are prevented by row-id checkpoint membership.
