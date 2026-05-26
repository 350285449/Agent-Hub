# Agent-Hub Architecture

Agent-Hub is a backend-first AI infrastructure layer. Clients send native,
OpenAI-compatible, Anthropic-compatible, or workflow requests; the backend
normalizes those requests, selects a provider, and returns a compatible
response without exposing internal details unless `expose_routing_details=true`.

## Router

`agent_hub.core.router.AgentRouter` ranks enabled agents by route, task type,
health, quota, context window, streaming support, tool support, and user
preferences. It preserves failover details internally and can expose selected
provider, model, fallback chain, routing reason, score, stream mode, and
context compression metadata when detailed routing is enabled.

## Provider Manager

`agent_hub.core.provider_manager.ProviderManager` is the adapter gateway. It
bridges legacy `complete()` adapters and strict `chat()` / `stream()` adapters.
Provider-specific payload translation stays inside `agent_hub.providers`.

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

## Context Engine

`agent_hub.core.context.ContextEngine` estimates tokens, compresses old
conversation turns into rolling summaries, preserves protected/recent context,
tracks repository memory, and exposes future embedding/retrieval interfaces.

## Workflows

`agent_hub.workflows.WorkflowEngine` runs deterministic non-recursive
Planner -> Worker -> Reviewer workflows for code, review, debug, explain, and
refactor tasks. Workflow stages share explicit memory and progress metadata.

## Tool System

`agent_hub.tools` defines MCP-shaped `Tool`, `ToolCall`, and `ToolResult`
objects, a registry, a permission layer, an execution pipeline, OpenAI tool
schema conversion, and built-in local tools.
