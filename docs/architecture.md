# Agent-Hub Architecture

Agent-Hub is a backend-first AI infrastructure layer. Clients send native,
OpenAI-compatible, Anthropic-compatible, or workflow requests; the backend
normalizes those requests, selects a provider, and returns a compatible
response without exposing internal details unless `expose_routing_details=true`.

For the platform-level architecture map, dependency analysis, and prioritized
modernization roadmap, see `docs/platform-architecture-roadmap.md`.

## Router

`agent_hub.core.router.AgentRouter` ranks enabled agents by route, task type,
health, quota, context window, streaming support, tool support, and user
preferences. It preserves failover details internally and can expose selected
provider, model, fallback chain, routing reason, score, stream mode, and
context compression metadata when detailed routing is enabled.

`agent_hub.core.provider_attempts.ProviderAttemptExecutor` owns the ranked
provider execution loop for non-streaming requests: cooldown/preflight skips,
permission blocks, retry/failover, validation recovery, output-limit
continuation, success/failure recording, and safe empty fallback generation.
The router still owns scoring and candidate selection.

## Application Services

`agent_hub.application` contains endpoint-independent services that coordinate
runtime systems for API handlers. The first services cover adaptive auto-mode
execution, feedback capture, optimization summaries, and provider-score
diagnostics so HTTP handlers can delegate business logic without owning it.

## Provider Manager

`agent_hub.core.provider_manager.ProviderManager` is the adapter gateway. It
bridges legacy `complete()` adapters and strict `chat()` / `stream()` adapters.
Provider-specific payload translation stays inside `agent_hub.providers`.
OpenAI-compatible provider authors can use the lightweight SDK template in
`docs/provider-sdk.md`, backed by `agent_hub.providers.sdk` descriptors.

## Streaming System

Native streaming uses provider adapter `stream()` generators that yield
normalized `StreamChunk` objects. The HTTP server emits OpenAI-compatible SSE
chunks and sets `X-Agent-Hub-Stream-Mode: native`. If no selected adapter can
stream natively, the existing compatibility stream remains available and sets
`X-Agent-Hub-Stream-Mode: compatibility`.

## Health System

Health state tracks success rate, latency, timeouts, quota/rate-limit state,
tool reliability, streaming speed, recent failures, and cooldowns. Health is
persisted in `.agent-hub/state/provider_health.json` and contributes to dynamic
provider scores.

Provider evaluation scores are stored in `.agent-hub/state/provider_scores.json`
and can add a small routing bias after real benchmark runs.

## Context Engine

`agent_hub.core.context.ContextEngine` estimates tokens, compresses old
conversation turns into rolling summaries, preserves protected/recent context,
tracks repository memory, and exposes future embedding/retrieval interfaces.

`agent_hub.repository` adds a repository indexer and selector for coding tasks:
file lists, language detection, important package/config files, changed files,
imports/references, compact file summaries, and anti-hallucination warnings for
referenced files that were not selected as evidence.

## Workflows

`agent_hub.workflows.WorkflowEngine` runs deterministic non-recursive
Planner -> Worker -> Reviewer workflows for code, review, debug, explain, and
refactor tasks. Optional stages add reviewer retry, shell validation commands,
validator review, patch summary, and a workflow state object.

## Tool System

`agent_hub.tools` defines MCP-shaped `Tool`, `ToolCall`, and `ToolResult`
objects, a registry, a permission layer, an execution pipeline, OpenAI tool
schema conversion, built-in local tools, and the provider tool-call loop.

## Dashboard

The root page and `/dashboard` expose a lightweight HTML dashboard. JSON status
lives at `/v1/status`, recent routing events at `/v1/routing-history`, and
stored benchmark scores at `/v1/provider-scores`.
