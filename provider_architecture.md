# Provider Architecture

## Current State

Provider execution already has the core pieces:

- `agent_hub.providers.base.ProviderAdapter` defines common chat, stream, health, capability, context, cost, request normalization, and response normalization methods.
- `agent_hub.providers.registry.ProviderRegistry` maps configured provider types to adapters.
- `agent_hub.core.provider_attempts.ProviderAttemptExecutor` executes ranked candidates with cooldowns, retries, failover, output validation, and usage recording.
- `agent_hub.providers.errors` normalizes provider errors into retryable categories.
- `agent_hub.providers.quota` parses common quota/rate-limit headers.
- `agent_hub.providers.shared._post_json_with_output_retry` retries once with a safer output token limit when providers reject the requested output budget.

## Target Common Interface

The execution-ready interface should extend the current adapter contract with schema-aware calls:

```python
class ProviderAdapter(Protocol):
    def chat(self, request: ChatRequest | HubRequest) -> ChatResponse: ...
    def structured_chat(
        self,
        request: ChatRequest | HubRequest,
        schema: dict[str, Any],
        *,
        strict: bool = True,
    ) -> ChatResponse: ...
    def validate_structured_response(
        self,
        response: ChatResponse,
        schema: dict[str, Any],
    ) -> ValidationResult: ...
```

`ChatRequest.raw["response_format"]` is currently passed through for OpenAI-compatible providers. That is useful but insufficient because Anthropic, Gemini, Ollama Cloud, and OpenRouter models need provider-specific schema translation and a common post-parse validator.

## Required Provider Layer Behavior

1. Normalize schema requests into provider-native mechanisms:
   - OpenAI-compatible: `response_format` JSON schema or tool/function call.
   - Anthropic: forced tool call with `input_schema` or JSON prompt fallback.
   - Gemini: function declaration or `generationConfig.responseMimeType`.
   - Ollama/OpenRouter/gateways: best available JSON mode, with declared reliability grade.

2. Enforce schema after response:
   - Parse exact JSON object.
   - Reject markdown/prose wrappers unless repair mode is explicitly enabled.
   - Validate against JSON Schema.
   - Attach `schema_valid`, `schema_errors`, and `schema_repaired` metadata.

3. Retry automatically:
   - Retry malformed JSON on same provider with a repair prompt.
   - Retry provider output-limit errors with reduced token budget.
   - Fail over when provider is unavailable, quota-limited, unsupported, too slow, or repeatedly malformed.

4. Preserve deterministic traces:
   - Every attempt must record provider, model, request id, schema id/hash, attempt number, repair reason, failover reason, latency, usage, and cost estimate.

## Automatic Failover

Current failover is production-useful: retryable provider errors, low confidence, output validation failure, output limits, cooldowns, and performance thresholds can move execution to the next candidate. The remaining blocker is that schema failure is not yet a first-class provider-layer failure. It exists in experiment code, but not in the base adapter contract.

## Schema Enforcement Plan

Implementation order:

1. Add `StructuredOutputSpec` and `StructuredValidationResult` dataclasses.
2. Add optional `structured_output` field to `ChatRequest`.
3. Implement provider-specific request translation.
4. Add a standard JSON Schema validator dependency or minimal internal validator.
5. Update `ProviderAttemptExecutor` to treat schema invalidity as retryable until `max_schema_repair_attempts`, then fail over.
6. Emit schema metrics to observability.

## Readiness Decision

The abstraction layer is partially built. It is strong enough for manually supervised cloud runs, but not yet strong enough for large-scale unsupervised experiments because schema enforcement is outside the common provider interface.

