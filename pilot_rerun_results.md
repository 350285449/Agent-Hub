# Pilot Rerun Results

Command: `python scripts/frozen_panel_executor.py --execute --limit 20`

Completed rows: `19`.
Quarantined rows: `1`.
Failed rows: `0`.
Instrumentation coverage: `0.95`.
Providers observed: `ollama-gemma-cloud`.

| row | status | valid instrumentation | provider calls | failure |
| --- | --- | --- | --- | --- |
| gct-v2-agentic-025 | completed | True | pre_commit:ollama-gemma-cloud:1, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-coding-023 | completed | True | pre_commit:ollama-gemma-cloud:1, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-agentic-006 | completed | True | pre_commit:ollama-gemma-cloud:1, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-coding-027 | completed | True | pre_commit:ollama-gemma-cloud:1, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-research-026 | completed | True | pre_commit:ollama-gemma-cloud:1, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-agentic-043 | completed | True | pre_commit:ollama-gemma-cloud:2, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-reasoning-015 | completed | True | pre_commit:ollama-gemma-cloud:1, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-coding-045 | completed | True | pre_commit:ollama-gemma-cloud:1, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-research-044 | completed | True | pre_commit:ollama-gemma-cloud:1, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-reasoning-044 | completed | True | pre_commit:ollama-gemma-cloud:2, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-coding-036 | completed | True | pre_commit:ollama-gemma-cloud:2, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-agentic-030 | completed | True | pre_commit:ollama-gemma-cloud:1, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-reasoning-029 | quarantined | False | - | Provider returned invalid response: missing_content_or_tool_calls |
| gct-v2-reasoning-025 | completed | True | pre_commit:ollama-gemma-cloud:1, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-research-045 | completed | True | pre_commit:ollama-gemma-cloud:2, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-coding-018 | completed | True | pre_commit:ollama-gemma-cloud:1, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-reasoning-041 | completed | True | pre_commit:ollama-gemma-cloud:2, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-agentic-014 | completed | True | pre_commit:ollama-gemma-cloud:1, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-agentic-019 | completed | True | pre_commit:ollama-gemma-cloud:2, commitment:ollama-gemma-cloud:1 | - |
| gct-v2-coding-039 | completed | True | pre_commit:ollama-gemma-cloud:2, commitment:ollama-gemma-cloud:1 | - |
