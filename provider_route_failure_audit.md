# Provider Route Failure Audit

Scope: non-Gemma cloud routes observed in provider failover, quarantine, and structured-output validation traces.

| route | family | auth | quota | subscription | cooldown | structured output | timeout | executor incompatibility | provider unavailable | other | examples |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| ollama-glm-cloud | glm | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: d00077a2-edff-46a2-a38f-1b20c44adbc7) |
| ollama-kimi-cloud | kimi | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 48261911-402d-45b5-877f-f041f1433821) |
| ollama-nemotron-cloud | nemotron | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | json_decode:Expecting value |
| ollama-qwen-cloud | qwen | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: f1470a01-cc2e-441d-940f-03c291f3b5ba) |
