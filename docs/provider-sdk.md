# Provider SDK

Agent-Hub provider integrations should implement the stable adapter contract in
`agent_hub.providers.base`. For OpenAI-compatible chat completions APIs, most
providers can use the SDK descriptor path instead of writing a full adapter.

## OpenAI-Compatible Provider Template

```python
from agent_hub.providers.sdk import (
    ProviderCapabilities,
    ProviderDescriptor,
    SimpleOpenAICompatibleProvider,
)


class DemoProvider(SimpleOpenAICompatibleProvider):
    descriptor = ProviderDescriptor(
        provider_type="demo-ai",
        display_name="Demo AI",
        base_url="https://api.demo.example/v1",
        api_key_env="DEMO_API_KEY",
        capabilities=ProviderCapabilities(
            supports_tools=True,
            supports_streaming=True,
            context_window=128_000,
        ),
        default_free=False,
    )
```

`SimpleOpenAICompatibleProvider` fills missing `AgentConfig` defaults from the
descriptor, then delegates payload translation, streaming, errors, and response
normalization to the built-in OpenAI-compatible adapter.

## Descriptor Fields

- `provider_type`: stable provider identifier, used by routing and analytics.
- `display_name`: human-readable provider name.
- `provider`: runtime adapter family, usually `openai-compatible`.
- `base_url`: provider API root; `/v1/chat/completions` is appended by default.
- `api_key_env`: environment variable used when no explicit key is configured.
- `chat_completions_path`: override for providers that do not use
  `/v1/chat/completions`.
- `headers`: default request headers.
- `capabilities`: tools, streaming, JSON, vision, function calling, and context
  metadata.
- `pricing`: known input/output cost per million tokens.

Descriptors can generate config entries:

```python
agent = DemoProvider.descriptor.create_agent(
    name="demo-coder",
    model="demo/coder",
    enabled=True,
)
```

Built-in provider metadata can be inspected with
`builtin_provider_descriptors()`.

## Conformance Report

Provider authors can run a no-network SDK contract check before wiring live
credentials:

```python
from agent_hub.providers.sdk import provider_conformance_report

report = provider_conformance_report(DemoProvider)
assert report["ok"], report["checks"]
```

The report verifies the stable `ProviderAdapter` method surface, descriptor
metadata, request/response normalization, health shape, and cost-estimate shape
without making a provider call.
