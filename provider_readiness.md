# Provider Readiness

Date: 2026-06-17

Scope: configured providers in `agent-hub.config.json`, plus provider families exposed by `agent_hub/provider_presets.py`.

## Certification Summary

Agent-Hub has a usable provider adapter surface, provider error normalization, quota header parsing, cooldowns, cost fields, and failover routing. It is not yet execution-ready for large-scale cloud experimentation because cloud authentication is not configured for direct OpenAI, Anthropic, or Gemini adapters, native schema enforcement is not part of the common provider contract, and cost/quota readiness is mostly inferred rather than measured.

## Configured Provider Matrix

| Provider | Auth | Quotas | Structured Output | JSON Reliability | Retry Support | Cost Estimation | Readiness |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `local-research` | None required | Not applicable | Not declared | Low: no JSON capability declaration | Router retry only | Free/local | Local only |
| `ollama-kimi-cloud` | Local Ollama session / cloud access required | Probe reached local Ollama; cloud quota not measured | Prompt/JSON mode only | Medium: `supports_json=True`, no schema contract | Output-token retry and router failover | Unknown/free flag only | Partial cloud |
| `ollama-glm-cloud` | Local Ollama session / cloud access required | Probe reached local Ollama; cloud quota not measured | Prompt/JSON mode only | Medium | Output-token retry and router failover | Unknown/free flag only | Partial cloud |
| `ollama-qwen-cloud` | Local Ollama session / cloud access required | Probe reached local Ollama; cloud quota not measured | Prompt/JSON mode only | Medium | Output-token retry and router failover | Unknown/free flag only | Partial cloud |
| `ollama-nemotron-cloud` | Local Ollama session / cloud access required | Probe reached local Ollama; cloud quota not measured | Prompt/JSON mode only | Medium | Output-token retry and router failover | Unknown/free flag only | Partial cloud |
| `ollama-gemma-cloud` | Local Ollama session / cloud access required | Probe reached local Ollama; cloud quota not measured | Prompt/JSON mode only | Medium | Output-token retry and router failover | Unknown/free flag only | Partial cloud |
| `custom-local` | Optional local endpoint auth | Endpoint timed out in prior audit | Prompt/JSON mode only | Medium if server honors JSON | Output-token retry and router failover | Unknown | Not cloud-ready |
| `ollama-qwen-coder` | None/local | Local endpoint reachable in prior audit | Tool-capable local adapter | Medium | Output-token retry and router failover | Free/local | Local only |
| `ollama-qwen3` | None/local | Local endpoint reachable in prior audit | Prompt/JSON mode only | Medium | Output-token retry and router failover | Free/local | Local only |
| `lm-studio` | None/local | Endpoint timed out in prior audit | Prompt/JSON mode only | Medium if server honors JSON | Output-token retry and router failover | Free/local | Not available |
| `localai` | None/local | Endpoint timed out in prior audit | Prompt/JSON mode only | Medium if server honors JSON | Output-token retry and router failover | Free/local | Not available |
| `vllm` | None/local | Endpoint timed out in prior audit | Tool-capable local adapter | Medium | Output-token retry and router failover | Free/local | Not available |
| `codex` | `OPENAI_API_KEY`; missing in audit | Unknown until authenticated | Native tools/functions | High if using OpenAI JSON/schema modes, but not enforced centrally | Output-token retry and router failover | Missing configured rates | Blocked |
| `codex-cli` | Local Codex CLI login | Not measurable through API headers | Prompt-enforced JSON | Medium | Process failure handling plus router failover | Free/local from config perspective | Local execution only |
| `claude` | `ANTHROPIC_API_KEY`; missing in audit | Unknown until authenticated | Native tools/functions | Medium-high, no central schema contract | Output-token retry and router failover | Missing configured rates | Blocked |
| `gemini` | `GEMINI_API_KEY`; missing in audit | Unknown until authenticated | Native tools/functions | Medium-high, no central schema contract | Output-token retry and router failover | Missing configured rates | Blocked |
| `chatgpt` | `OPENAI_API_KEY`; missing in audit | Unknown until authenticated | Native tools/functions | High if using OpenAI JSON/schema modes, but not enforced centrally | Output-token retry and router failover | Missing configured rates | Blocked |
| `echo` | None | Not applicable | Not declared | Low | Router failover only | Free/local | Test only |

## Provider Family Matrix

| Family | Auth | Quota Visibility | Structured Output | JSON Reliability | Retry Support | Cost Estimation |
| --- | --- | --- | --- | --- | --- | --- |
| OpenAI-compatible gateways | API key optional/required by endpoint | Header parser supports common rate-limit headers | Pass-through `response_format` and tools | Depends on backend | Shared output-token retry and router failover | Supported when per-million rates configured |
| OpenAI | `OPENAI_API_KEY` | Header parser available; not live-certified | Native JSON/tools possible | High, but schema not enforced centrally | Shared retry/failover | Missing in active config |
| Anthropic | `ANTHROPIC_API_KEY` | Header parser includes Anthropic rate-limit headers | Tools/input schema; JSON by prompt | Medium-high | Shared retry/failover | Missing in active config |
| Gemini | `GEMINI_API_KEY` | Limited quota inference from errors | Function declarations; JSON by prompt/config | Medium-high | Shared retry/failover | Missing in active config |
| Groq | `GROQ_API_KEY` | Header/error inference | OpenAI-compatible tools/JSON | Medium-high | Shared retry/failover | Preset metadata lacks fixed rates |
| OpenRouter | `OPENROUTER_API_KEY` | Credit headers parsed | OpenAI-compatible tools/JSON | Model-dependent | Shared retry/failover | Preset metadata lacks fixed rates |
| Ollama Cloud | Local Ollama auth/session | Local probe only; cloud quota not measured | JSON prompt/mode | Model-dependent | Shared retry/failover | Unknown/free flag only |

## Blockers

1. No live multi-provider cloud credential set is configured.
2. Cloud quota/cost readiness is inferred from headers and config, not certified by a preflight budget probe.
3. Structured output support is advertised as booleans, not a provider-neutral schema contract.
4. JSON reliability is prompt/repair based for most providers; malformed outputs can be quarantined in experiments but are not prevented at the provider layer.
5. Direct provider costs are mostly missing from the active config, making large-run budget estimates unreliable.

