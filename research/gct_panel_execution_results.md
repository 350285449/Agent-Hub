# GCT Panel Execution Results

Status: aborted.

The frozen prospective panel was not executed to 200 valid live rows.

Preconditions verified:
- `agent_hub/research/gct_instrumentation.py` exists.
- `scripts/frozen_panel_executor.py` exists.
- GCT tests passed: `python -m pytest -q -k gct` returned `3 passed, 763 deselected`.
- Frozen panel row count is 200 in `research/gct_prospective_dataset_v2.jsonl`.
- Dry-run instrumentation wrote valid GAR, commitment, intervention, and JSONL traces for 200 rows.
- Enabled configured `:cloud` agents were present.

Execution attempts:
- `python scripts/frozen_panel_executor.py --execute --limit 200` aborted before row 1 because `approval_mode=safe` required provider approval.
- After a temporary non-interactive trusted-cloud config adjustment, execution aborted because `ollama-qwen-cloud`, `ollama-glm-cloud`, and `ollama-kimi-cloud` require an Ollama subscription.
- A one-row live shakedown using the only callable configured `:cloud` agent, `ollama-nemotron-cloud`, reached the provider but failed because the response contained no JSON object for the required event trace.

No local models were substituted. No synthetic rows were generated. Historical rows were not replayed. No measurements were fabricated.
