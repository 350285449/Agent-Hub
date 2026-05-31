# Agent-Hub Architecture Modernization Phase 0

This note records the Phase 0 baseline for the architecture modernization work.
It is intentionally descriptive: no runtime behavior was changed in this phase.

## Public Surface

Public imports that must remain stable during the evolutionary refactor:

- `agent_hub`: `AgentConfig`, `HubConfig`, `RouteRule`, `HubRequest`,
  `HubResponse`, `ProviderResult`, `AgentRouter`, `AgentRunner`,
  `TeamAgentRunner`, reasoning state models, config helpers, and
  `backend_version`.
- `agent_hub.router`: legacy router facade for `AgentRouter`,
  `RoutingDecision`, `RouterError`, routing error constants, and token helpers.
- `agent_hub.providers`: current provider facade for `ProviderError`,
  `Provider`, concrete adapters, and `create_provider`.
- `agent_hub.providers.base`: strict adapter protocol and normalized provider
  request/response/stream models.
- `agent_hub.tools`: tool registry, tool types, tool loop metadata, execution
  context, execution pipeline, and built-in registry helpers.
- `agent_hub.workflows`: workflow engine, workflow state/result models, and
  extension-point models.
- `agent_hub.api.openai_compat` and `agent_hub.api.server`: compatibility
  import paths used by clients and tests.

Compatibility endpoints that must remain stable:

- OpenAI-compatible: `/v1/chat/completions`,
  `/api/v1/chat/completions`, `/openrouter/v1/chat/completions`,
  `/v1/responses`, `/v1/models`, `/models`, `/api/v1/models`.
- Anthropic-compatible: `/v1/messages`.
- Native: `/v1/route`, `/agent`, `/v1/agent`.
- Diagnostics and status: `/health`, `/limits`, `/usage`, `/metrics`,
  `/permissions`, `/debug/request`, `/debug/context`, `/v1/status`,
  `/v1/routing/status`, `/v1/routing/last-decision`,
  `/v1/routing/test-failover`, `/v1/limits`, `/v1/usage`,
  `/v1/client-sources`, `/v1/routing-history`, `/v1/provider-scores`,
  `/v1/provider-health`, `/v1/events`, `/v1/tools`,
  `/v1/workflows/status`, `/v1/plugins`, `/v1/enterprise/audit`.

Provider contract surface that must remain stable:

- `ProviderAdapter.chat()`
- `ProviderAdapter.stream()`
- `ProviderAdapter.health_check()`
- `ProviderAdapter.supports_streaming()`
- `ProviderAdapter.supports_tools()`
- `ProviderAdapter.supports_vision()`
- `ProviderAdapter.context_limit()`
- `ProviderAdapter.cost_estimate()`
- `ProviderAdapter.normalize_request()`
- `ProviderAdapter.normalize_response()`

## Dependency Graph Baseline

Current high-level dependency graph:

```text
server -> router, runner, workflows, payloads, permissions, observability, plugins
core.router -> providers, provider_manager, permissions, tools, health, repository,
               payloads, session, streaming, observability
agent_runner -> router, agent_tools, reasoning, context, token_budget
agent_tools -> permissions, enterprise, observability, config, models
providers -> config, debug, models, payloads, provider_presets,
             response_normalization
workflows -> router, tools, payloads, observability
permissions -> security, enterprise, token_budget, config
cli -> server, router, runner, team_runner, payloads, config mutation, diagnostics
```

Current fan-out baseline to reduce over later phases:

```text
agent_hub.core.router        <= 23 internal modules
agent_hub.server             <= 16 internal modules
agent_hub.cli                <= 12 internal modules
agent_hub.providers.__init__ <= 10 internal modules
```

Known dependency cycles:

```text
agent_hub.config <-> agent_hub.discovery
agent_hub.providers.__init__ <-> agent_hub.providers.groq
agent_hub.providers.__init__ <-> agent_hub.providers.ollama
agent_hub.providers.__init__ <-> agent_hub.providers.openrouter
```

Phase 0 guardrails allow these known cycles as baseline debt but reject new
cycles. Future phases should remove the allowed cycles rather than add to them.

## Coupling Assessment

Primary coupling points:

- `core/router.py` mixes routing selection, provider execution, failover,
  provider permission gates, context preparation, session history, streaming,
  tool loops, health persistence, recommendations, and diagnostics.
- `server.py` mixes HTTP routing, OpenAI/Anthropic/native compatibility,
  model aliasing, diagnostics authorization, dashboard HTML, SSE emission, and
  response/error shaping.
- `providers/__init__.py` mixes concrete adapters, provider registry, HTTP
  transport, error classification, quota parsing, request shaping, and local
  web research.
- `agent_tools.py` mixes agent instructions, filesystem tools, patching,
  shell execution, checkpoints, repository maps, permission checks, and events.
- `permissions.py` mixes provider trust, tool permission request construction,
  IDE compatibility policy, enterprise checks, and risk thresholds.
- `observability.py` is called directly from routing, tools, workflows,
  security, enterprise, and server helpers.

## Hidden Architectural Risks

- API drift: compatibility endpoints are used by IDEs and OpenAI/Anthropic
  clients, so response keys and streaming markers need fixture coverage.
- Permission drift: provider and tool permission behavior exists in multiple
  paths, which raises the risk of accidental bypass or over-blocking.
- Streaming drift: native and compatibility streaming are selected in the
  router and emitted in the server; splitting either side can break clients.
- Provider drift: adapter implementations, factory registration, transport
  errors, and quota parsing currently share one module.
- Observability drift: direct event writes make it hard to preserve diagnostics
  semantics while moving core logic.
- Import drift: heavy public package imports currently load runtime services;
  future extraction must keep public imports stable.

## Phase Risk Report

| Phase | Risk | Primary compatibility concern |
| --- | --- | --- |
| 0 Guardrails | Low | Tests must describe current behavior without blocking future reductions |
| 0.5 API Stability | Medium | Golden fixtures must normalize dynamic ids and timestamps |
| 1 Provider Extraction | Medium | Existing provider imports and mocked provider tests must keep working |
| 1.5 Capability Model | Medium | Capability defaults must match current `AgentConfig` behavior |
| 2 Router Decomposition | High | Failover, health, permissions, streaming, and tool-loop behavior |
| 3 Tool Runtime Unification | High | Workspace mutation, shell approval, patch rollback, and legacy agent tools |
| 4 Security Consolidation | High | Avoid permission bypass, over-blocking, or LAN diagnostics exposure |
| 5 Observability Modernization | Medium | Preserve event names and dashboard/extension diagnostics |
| 6 Workflow Modernization | Medium | Preserve stage order, prompt intent, validation, and metadata |

## Phase 0 Guardrails Added

The Phase 0 test guardrails cover:

- public import compatibility
- compatibility endpoint registration
- provider adapter contract surface
- domain-candidate import boundaries
- known dependency-cycle baseline
- fan-out baseline ceilings for high-risk modules
- payload and streaming shape fixtures for OpenAI, Anthropic, and native models

These tests are designed to be tightened in later phases as cycles are removed
and services are extracted.
