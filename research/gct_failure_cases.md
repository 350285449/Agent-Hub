# GCT Failure Cases

Status: not available.

No model-outcome failure cases can be reported because the prospective panel did not execute to valid measured rows.

Execution blocker cases:
- Configured cloud agents `ollama-kimi-cloud`, `ollama-glm-cloud`, and `ollama-qwen-cloud` returned subscription-required errors.
- Configured cloud agent `ollama-nemotron-cloud` was callable but returned non-JSON/malformed output for the required instrumentation phase.
