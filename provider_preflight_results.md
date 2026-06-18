# Provider Preflight Results

Approved cloud routes: `[]`.
Approved model families: `[]`.
Required model families: `3`.
Abort: `True`.
Blockers: live structured preflight rejected: ollama-kimi-cloud,ollama-glm-cloud,ollama-qwen-cloud,ollama-nemotron-cloud,ollama-gemma-cloud, provider diversity preflight failed: 0 approved families < 3

Live structured preflight:

| route | passed | category | message |
| --- | --- | --- | --- |
| ollama-kimi-cloud | False | authentication_error | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 48261911-402d-45b5-877f-f041f1433821) |
| ollama-glm-cloud | False | authentication_error | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: d00077a2-edff-46a2-a38f-1b20c44adbc7) |
| ollama-qwen-cloud | False | authentication_error | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: f1470a01-cc2e-441d-940f-03c291f3b5ba) |
| ollama-nemotron-cloud | False | structured_output_failure | json_decode:Expecting value |
| ollama-gemma-cloud | False | structured_output_failure | json_decode:Expecting value;json_decode:Expecting ',' delimiter |

Certification:

| route | auth | quota | subscription | availability | structured output | timeout | certified |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ollama-kimi-cloud | pass | pass | requires local Ollama with cloud model access | pass | pass | pass | True |
| ollama-glm-cloud | pass | pass | requires local Ollama with cloud model access | pass | pass | pass | True |
| ollama-qwen-cloud | pass | pass | requires local Ollama with cloud model access | pass | pass | pass | True |
| ollama-nemotron-cloud | pass | pass | requires local Ollama with cloud model access | pass | pass | pass | True |
| ollama-gemma-cloud | pass | pass | requires local Ollama with cloud model access | pass | pass | pass | True |
