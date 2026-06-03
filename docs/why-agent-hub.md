# Why Agent-Hub?

Agent-Hub is a local AI gateway for developers who want provider choice,
auditable coding workflows, and a single safety boundary for tools.

Use it when you want:

- One local OpenAI/Anthropic/OpenRouter-compatible API for many AI tools.
- Provider choice without hard-wiring every editor, script, or workflow to one
  vendor.
- Automatic routing to cheaper, faster, longer-context, or more reliable models
  based on the task.
- Lower cost through smart routing, context compression, and repo-map injection.
- Higher reliability through health tracking, cooldowns, retries, and provider
  fallback.
- Centralized safety checks before file writes, deletes, installs, shell
  commands, config edits, and external provider calls.
- Local, auditable coding workflows with request, routing, permission, tool, and
  workflow JSONL logs.
- Visibility into selected provider/model, why it was selected, context/cost
  estimates, fallbacks, blocked permissions, and workflow progress.

Agent-Hub is not trying to hide provider differences. It makes them explicit,
routes around failures, and keeps client-facing compatibility schemas stable.

## Common Uses

- Point Cline, Continue, Claude Code, VS Code, and scripts at one local
  endpoint.
- Run free/local models first and fall back to cloud providers only when needed.
- Keep high-risk workspace operations behind one permission policy.
- Route large coding tasks to long-context coding models while routing simple
  explanations to cheaper fast models.
- Debug provider failures with `/v1/routing/status`, `/v1/provider-health`, and
  `/dashboard/optimization`.

## Differentiator

The main differentiator is Smart Workspace-Aware Model Routing. Agent-Hub
classifies the request, repository hints, file types, risk level, required
capabilities, and context size before selecting a model. The routing decision is
logged with a human-readable reason so developers can see why a model was used.
