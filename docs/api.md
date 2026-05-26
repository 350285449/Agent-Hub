# API Examples

Agent-Hub exposes native and compatibility endpoints on the local server.

## OpenAI Chat Completions

```sh
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agent-hub-coding",
    "messages": [{"role": "user", "content": "Fix the failing test"}]
  }'
```

## Streaming

```sh
curl -N http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agent-hub-coding",
    "stream": true,
    "messages": [{"role": "user", "content": "Write a short plan"}]
  }'
```

The response header `X-Agent-Hub-Stream-Mode` is `native` when the selected
provider streams live chunks and `compatibility` when Agent-Hub streams a
completed response.

Set `"force_compatibility_streaming": true` to bypass provider-native streaming
for fragile clients or providers. Malformed, empty, or partial provider SSE
chunks are ignored and logged when raw debugging is enabled; Agent-Hub always
terminates OpenAI-compatible streams with a valid final chunk and `[DONE]`.

## Tool Calls

For Agent-Hub-owned built-in tools, model `tool_calls` are executed locally,
tool results are appended to message history, and the provider is called again
until a final answer or `max_tool_iterations` is reached. Routing metadata
includes `tool_calls`, `tool_results`, and `tool_iteration_count` when detailed
routing is enabled.

Tool-call arguments are validated before execution. Invalid JSON is repaired
when possible or converted to `{}`, missing tool names are skipped, duplicate
tool-loop iterations are stopped, and oversized tool results are compacted
before they are sent back to the provider.

Tool execution emits compact internal events to
`.agent-hub/state/events.jsonl` with the event name `tool.executed`, duration,
success status, and result size.

## Provider Response Safety

Before returning OpenAI-compatible, Anthropic, Gemini, Ollama, Groq, or
OpenRouter responses, Agent-Hub normalizes provider-specific payloads into a
strict shape. If a provider returns empty content, missing `choices`, malformed
tool calls, or an incomplete response, Agent-Hub retries once, falls back to the
next route candidate, and finally returns:

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "[Provider returned malformed response]"
      }
    }
  ]
}
```

Use `"debug_raw_provider_responses": true` to write redacted traces to
`.agent-hub/debug/`.

## Workflows

```sh
curl http://127.0.0.1:8787/v1/workflows/code \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Add validation for config loading"}]
  }'
```

Use `validate=true` to add the optional validator stage. Use
`patch_summary=true` to include a deterministic patch-summary stage. If
`validation_commands` are configured and shell tools are allowed, workflows run
those commands through the same shell policy as normal tools.

Workflow extension-point models are available for future planner/reviewer,
parallel-provider, consensus, and result-merge strategies. They are passive
configuration objects today and do not change workflow execution behavior.

## Health

```sh
curl http://127.0.0.1:8787/health
```

Health includes provider status, latency, score, cooldowns, streaming support,
limits, routing capabilities, context diagnostics, and enabled features.

## Dashboard And Debugging

```sh
curl http://127.0.0.1:8787/v1/status
curl http://127.0.0.1:8787/v1/routing-history
curl http://127.0.0.1:8787/v1/provider-scores
curl http://127.0.0.1:8787/v1/provider-health
curl http://127.0.0.1:8787/v1/events
curl http://127.0.0.1:8787/v1/tools
curl http://127.0.0.1:8787/v1/workflows/status
curl http://127.0.0.1:8787/v1/plugins
curl http://127.0.0.1:8787/v1/enterprise/audit
```

If Agent Hub is configured with a public bind host such as `0.0.0.0`, the
diagnostic endpoints above require `Authorization: Bearer <token>` or
`X-Agent-Hub-Diagnostics-Token`. Configure the token with
`diagnostics_auth_token` or `diagnostics_auth_token_env`.

Diagnostic responses are recursively redacted before they are returned. Provider
errors, audit rows, and plugin metadata should keep useful context while
masking API keys, bearer tokens, auth headers, and secret-looking strings.

`/dashboard` renders the same core provider status in lightweight HTML.
Internal foundation events are stored in `.agent-hub/state/events.jsonl` and
include `provider.selected`, `provider.failed`, `router.fallback`,
`stream.started`, `stream.failed`, `tool.executed`, and `context.truncated`.
`/metrics` also exposes metrics-ready counters for provider failures, routing
fallbacks, stream failures, context truncation, and tool execution.

## Provider Evaluation

```sh
python -m agent_hub eval --route coding --json
```

The command runs benchmark task types for coding, reasoning, summarization,
tool calling, long context, and latency, then stores scores in local state.

## Cline

- Base URL: `http://127.0.0.1:8787/v1`
- API key: any local placeholder
- Model: `agent-hub-coding`

## Continue

Use an OpenAI-compatible model entry:

```json
{
  "title": "Agent-Hub",
  "provider": "openai",
  "model": "agent-hub-coding",
  "apiBase": "http://127.0.0.1:8787/v1",
  "apiKey": "local"
}
```
