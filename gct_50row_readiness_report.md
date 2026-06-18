# GCT 50-Row Readiness Report

Command: `python scripts/frozen_panel_executor.py --execute --limit 50`.

Readiness metrics:
- Completed rows: `48/50`.
- Quarantine rate: `2/50` = `4.00%`.
- Malformed-ingestion count: `0`.
- Instrumentation coverage: `48/50` = `96.00%`.
- Provider failure row rate: `1/50` = `2.00%`.
- Schema failure row rate: `1/50` = `2.00%`.

Provider assessment:
- Accepted calls were dominated by `ollama-gemma-cloud`: `96` of `96` accepted calls.
- Other cloud agents produced repeated failover/cooldown/authentication events: `{'ollama-qwen-cloud': 86, 'ollama-kimi-cloud': 86, 'ollama-glm-cloud': 86, 'ollama-nemotron-cloud': 86}`.

Decision:
- The 50-row stage clears the minimum completion threshold: 48 completed rows.
- The malformed-ingestion count is zero.
- Quarantines worked: invalid rows were isolated rather than ingested.
- Full 200-row execution is not allowed because provider diversity failed and one provider dominated all accepted calls.

FINAL VERDICT: C. 50-row ready but not 200-row ready.
