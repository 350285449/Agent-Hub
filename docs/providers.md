# Provider Adapters

Provider adapters live in `agent_hub.providers` and should keep
provider-specific request/response logic isolated.

## Required Interface

Adapters should expose:

- `chat(request)` for normalized non-streaming calls.
- `complete(request)` for legacy compatibility.
- `stream(request)` only when the provider truly supports native streaming.
- `supports_streaming()`, `supports_tools()`, `supports_vision()`.
- `context_limit()` and `cost_estimate()` when known.

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
