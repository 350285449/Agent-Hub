# API Compatibility

Agent-Hub exposes compatibility endpoints while keeping internal orchestration
metadata out of public responses by default.

## Endpoints

- `POST /v1/chat/completions`
- `POST /api/v1/chat/completions`
- `POST /openrouter/v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/messages`
- `GET /v1/models`

## Schema Rules

- OpenAI Chat Completions return `id`, `object`, `created`, `model`,
  `choices`, and `usage`.
- OpenAI Responses return `id`, `object`, `created_at`, `status`, `model`,
  `output`, `output_text`, and `usage`.
- Anthropic Messages return `id`, `type`, `role`, `content`, `model`,
  `stop_reason`, `stop_sequence`, and `usage`.
- Streaming responses preserve expected SSE framing and final terminators.
- Tool calls are preserved in provider-native OpenAI, Anthropic, and Responses
  compatible shapes.
- Error responses use the expected public error shape for the compatibility
  endpoint.

## Metadata Policy

Internal metadata is not emitted on compatibility endpoints unless detailed
routing is enabled. Hidden by default:

- workflow memory and stage outputs
- provider health internals
- routing candidate scorecards
- repository context selection
- tool-loop internals
- failover metadata beyond public headers

When `expose_routing_details=true`, responses may include an `agent_hub` object
with selected provider/model, routing reason, fallback chain, task
classification, and context/cost estimates.

## Tests

Compatibility coverage includes:

- golden fixtures in `tests/test_api_golden_fixtures.py`
- schema guardrails in `tests/test_architecture_guardrails.py`
- streaming helpers in `tests/test_api_compatibility_phase9.py`
- model rows and headers in `tests/test_api_compatibility_phase8.py`
- endpoint/request mapping in `tests/test_api_compatibility_phase7.py`
- metadata leak checks in `tests/test_smart_workspace_routing.py`
