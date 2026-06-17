# Provider Audit

Scope: every configured provider in `agent-hub.config.json`. Authentication and quota are inferred from configured keys, HTTP status, and provider error text; no theory verdict is made.

| agent | provider_type | model | enabled | cloud | reachable | authenticated | quota_status | subscription | JSON | structured output | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| local-research | local-research | local-extractive-research | True | False | True | True | not_applicable | not declared | False | not_declared | - |
| ollama-kimi-cloud | ollama-cloud | kimi-k2.6:cloud | True | True | True | True | not_exhausted_by_probe | requires local Ollama with cloud model access | True | json_mode_or_prompt_enforced | probe http://127.0.0.1:11434/api/tags -> 200 |
| ollama-glm-cloud | ollama-cloud | glm-5.1:cloud | True | True | True | True | not_exhausted_by_probe | requires local Ollama with cloud model access | True | json_mode_or_prompt_enforced | probe http://127.0.0.1:11434/api/tags -> 200 |
| ollama-qwen-cloud | ollama-cloud | qwen3.5:cloud | True | True | True | True | not_exhausted_by_probe | requires local Ollama with cloud model access | True | json_mode_or_prompt_enforced | probe http://127.0.0.1:11434/api/tags -> 200 |
| ollama-nemotron-cloud | ollama-cloud | nemotron-3-super:cloud | True | True | True | True | not_exhausted_by_probe | requires local Ollama with cloud model access | True | json_mode_or_prompt_enforced | probe http://127.0.0.1:11434/api/tags -> 200 |
| ollama-gemma-cloud | ollama-cloud | gemma4:31b-cloud | True | True | True | True | not_exhausted_by_probe | requires local Ollama with cloud model access | True | json_mode_or_prompt_enforced | probe http://127.0.0.1:11434/api/tags -> 200 |
| custom-local | openai-compatible | local-model | True | False | False | None | unknown | not declared | True | json_mode_or_prompt_enforced | probe http://127.0.0.1:8000/v1/models failed: URLError: <urlopen error timed out> |
| ollama-qwen-coder | openai-compatible | qwen2.5-coder:7b | True | False | True | True | not_exhausted_by_probe | not declared | True | json_mode_or_prompt_enforced | probe http://127.0.0.1:11434/v1/models -> 200 |
| ollama-qwen3 | openai-compatible | qwen3:8b | True | False | True | True | not_exhausted_by_probe | not declared | True | json_mode_or_prompt_enforced | probe http://127.0.0.1:11434/v1/models -> 200 |
| lm-studio | openai-compatible | local-model | True | False | False | None | unknown | not declared | True | json_mode_or_prompt_enforced | probe http://127.0.0.1:1234/v1/models failed: URLError: <urlopen error timed out> |
| localai | openai-compatible | llama-3.2-1b-instruct:q4_k_m | True | False | False | None | unknown | not declared | True | json_mode_or_prompt_enforced | probe http://127.0.0.1:8080/v1/models failed: URLError: <urlopen error timed out> |
| vllm | openai-compatible | local-model | True | False | False | None | unknown | not declared | True | json_mode_or_prompt_enforced | probe http://127.0.0.1:8000/v1/models failed: URLError: <urlopen error timed out> |
| codex | openai | gpt-4o-mini | False | True | None | False | unknown | requires OPENAI_API_KEY | True | native_tools_or_functions | missing env OPENAI_API_KEY |
| codex-cli | codex-cli | gpt-5.5 | True | False | True | True | not_applicable | not declared | True | json_mode_or_prompt_enforced | - |
| claude | anthropic | claude-3-5-haiku-latest | False | True | None | False | unknown | requires ANTHROPIC_API_KEY | True | native_tools_or_functions | missing env ANTHROPIC_API_KEY |
| gemini | gemini | gemini-2.0-flash | False | True | None | False | unknown | requires GEMINI_API_KEY | True | native_tools_or_functions | missing env GEMINI_API_KEY |
| chatgpt | openai | gpt-4o-mini | False | True | None | False | unknown | requires OPENAI_API_KEY | True | native_tools_or_functions | missing env OPENAI_API_KEY |
| echo | echo | local-echo | True | False | True | True | not_applicable | not declared | False | not_declared | - |
