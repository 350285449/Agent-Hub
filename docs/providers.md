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

Provider plugins can be described with a manifest under `.agent-hub/plugins`,
but Agent Hub currently treats plugins as manifest-only metadata and does not
execute third-party plugin code. See `docs/plugins.md`.

## Codex CLI Provider

`provider_type: "codex-cli"` is not an OpenAI-compatible HTTP endpoint. It
invokes `codex exec` locally and reuses the Codex CLI's cached ChatGPT login.
Use it when you want Codex access without `OPENAI_API_KEY`; keep the existing
`codex` / `openai` provider for standard API-key routing.

By default the adapter runs with `--sandbox read-only`,
`--ask-for-approval never`, and `--ephemeral`. Override those with
`AGENT_HUB_CODEX_CLI_SANDBOX`, `AGENT_HUB_CODEX_CLI_APPROVAL`, and
`AGENT_HUB_CODEX_CLI_PROFILE` when needed.
