# Architecture

Agent Hub is a local AI middleware layer.

Core surfaces:

- OpenAI Chat Completions
- OpenAI Responses
- Anthropic Messages
- Cline/Roo/OpenCode-compatible OpenAI endpoint
- Claude Code-compatible Anthropic endpoint
- native workspace-agent endpoint
- VS Code sidebar and chat participant

Core systems:

- provider router with health, quota, latency, capability, cost, cooldown, and
  failover memory
- central permission manager
- token budget manager and protected context categories
- provider adapters for OpenAI, Anthropic, Gemini, OpenAI-compatible, local
  research, and debug echo
- team-agent execution roles
- observability logs and metrics

Structured context is normalized into a provider-neutral `HubRequest`, but rich
message blocks stay structured until a specific provider adapter needs a text
fallback.
