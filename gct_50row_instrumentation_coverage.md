# GCT 50-Row Instrumentation Coverage

Completed-row instrumentation coverage: `48/50` = `96.00%`.

| field | completed rows with value | coverage | notes |
| --- | --- | --- | --- |
| GAR | `48/48` | `100.00%` | captured directly or derived from row artifacts |
| pre_commit_GAR | `48/48` | `100.00%` | captured directly or derived from row artifacts |
| post_commit_GAR | `48/48` | `100.00%` | captured directly or derived from row artifacts |
| commitment_timing | `48/48` | `100.00%` | captured directly or derived from row artifacts |
| commitment_strength | `48/48` | `100.00%` | captured directly or derived from row artifacts |
| commitment_quality | `48/48` | `100.00%` | captured directly or derived from row artifacts |
| uncertainty_collapse | `48/48` | `100.00%` | derived from emitted uncertainty sequence; no separate post-commit uncertainty event exists |
| intervention_delivery | `48/48` | `100.00%` | treatment rows record delivered pre-commit gates; controls are not_applicable_control |
| intervention_timing | `48/48` | `100.00%` | treatment rows record delivered pre-commit gates; controls are not_applicable_control |
| outcome | `48/48` | `100.00%` | captured directly or derived from row artifacts |

Provider coverage:
- Accepted provider calls: `{'ollama-gemma-cloud': 96}`.
- Accepted model calls: `{'gemma4:31b': 96}`.
- Failover/cooldown events by agent from raw traces: `{'ollama-qwen-cloud': 86, 'ollama-kimi-cloud': 86, 'ollama-glm-cloud': 86, 'ollama-nemotron-cloud': 86}`.

Instrumentation sufficiency assessment: row-level event instrumentation is sufficient for the completed 48 rows, but provider diversity is not sufficient for 200-row authorization.
