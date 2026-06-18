# Quarantine Cause Table

| cause | frequency | severity | evidence |
| --- | ---: | --- | --- |
| provider unavailable | 17 | critical | failover/cooldown/invalid response before final provider |
| authentication/quota | 16 | critical | qwen/kimi/glm subscription-auth failures |
| parser/schema mismatch | 18 | high | example `gct-v2-agentic-025` |
| malformed JSON | 16 | medium | example `gct-v2-agentic-025` |
| timeout | 3 | high | nemotron overload/latency failover |
| missing required fields | 3 | medium | example `gct-v2-agentic-025` |
| invalid field types | 2 | medium | example `gct-v2-coding-023` |
