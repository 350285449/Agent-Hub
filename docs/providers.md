# Provider Adapters

Provider adapters live in `agent_hub.providers` and should keep
provider-specific request/response logic isolated.

## Required Interface

Adapters should expose:

- `chat(request)` for normalized non-streaming calls.
- `complete(request)` for legacy compatibility.
- `stream(request)` only when the provider truly supports native streaming.
- `supports_streaming()` and `supports_tools()`.
- `context_limit()` and `cost_estimate()` when known.
- Optional config fields `cost_per_million_input` and
  `cost_per_million_output` help adaptive routing prefer cheaper providers
  when reliability, latency, context, and capability scores are otherwise
  comparable.

Streaming adapters yield `StreamChunk(text, delta, model, finish_reason, raw)`.
Do not advertise streaming support unless the provider endpoint can stream
incremental chunks.

## Adding A Provider

1. Add an adapter module under `agent_hub/providers/`.
2. Translate `HubRequest` or `ChatRequest` into the provider API payload.
3. Normalize the response into `ProviderResult` or `ChatResponse`.
4. Implement native `stream()` if supported.
5. Register the provider in `create_provider()`.
6. Add config defaults or provider presets if appropriate.
7. Add tests for payload translation, errors, streaming, and tool handling.

Provider plugins can be described with a manifest under `.agent-hub/plugins`.
Discovery is manifest-first by default, and trusted plugins can opt into
bounded local-process JSON execution. See `docs/plugins.md`.

## Codex CLI Provider

`provider_type: "codex-cli"` is not an OpenAI-compatible HTTP endpoint. It
invokes `codex exec` locally and reuses the Codex CLI's cached ChatGPT login.
Use it when you want Codex access without `OPENAI_API_KEY`; keep the existing
`codex` / `openai` provider for standard API-key routing.

By default the adapter runs with `--sandbox read-only`,
`--ask-for-approval never`, and `--ephemeral`. Override those with
`AGENT_HUB_CODEX_CLI_SANDBOX`, `AGENT_HUB_CODEX_CLI_APPROVAL`, and
`AGENT_HUB_CODEX_CLI_PROFILE` when needed.

For the easiest no-key setup in VS Code, run `Agent Hub: Install Codex CLI` if
`codex` is missing, then run `Agent Hub: Use Codex CLI Without API Key` or click
`Codex CLI Mode` in Agent Hub. That enables `codex-cli`, disables API-key
fallbacks, caps output, and uses compact Codex prompts. Set
`AGENT_HUB_CODEX_CLI_PROMPT_TOKENS` to override the provider-side prompt budget.

Token Safe Mode is separate from Codex CLI Mode: it routes free cloud models
first to avoid spending Codex calls, but keeps Codex CLI and API-key fallback
requests at the normal context and output budget.

Free Only Mode is stricter. It sets `free_only=true` and
`disable_non_free_models=true`, disables `codex-cli` and hosted API-key agents,
and rewrites cloud routes to eligible free/local/free-tier models only. Use it
when Codex CLI or paid/API-key fallback calls should not run at all.
