# Cloud Provider Certification

Scope: configured cloud providers only. Checks cover auth, quota, model availability, structured-output compliance, timeout behavior, and retry behavior.

| agent | model | auth | quota | model | structured output | timeout | retry | certified | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ollama-kimi-cloud | kimi-k2.6:cloud | pass | pass | pass | pass | pass | pass | True | probe http://127.0.0.1:11434/api/tags -> 200 |
| ollama-glm-cloud | glm-5.1:cloud | pass | pass | pass | pass | pass | pass | True | probe http://127.0.0.1:11434/api/tags -> 200 |
| ollama-qwen-cloud | qwen3.5:cloud | pass | pass | pass | pass | pass | pass | True | probe http://127.0.0.1:11434/api/tags -> 200 |
| ollama-nemotron-cloud | nemotron-3-super:cloud | pass | pass | pass | pass | pass | pass | True | probe http://127.0.0.1:11434/api/tags -> 200 |
| ollama-gemma-cloud | gemma4:31b-cloud | pass | pass | pass | pass | pass | pass | True | probe http://127.0.0.1:11434/api/tags -> 200 |
