# Routing Memory Privacy

Routing memory is designed to improve model selection without retaining full
prompts by default.

## Default Storage

By default, `.agent-hub/state/routing_memory.jsonl` stores metadata only:

- task type/category
- language/framework
- repo and context size buckets
- file extensions, not file contents
- risk, complexity, workflow hint, and permission requirements
- provider/model used
- latency, retries, fallback count, success/failure, timeout, permission denial,
  tool/reviewer failure, cancellation, cost estimate, and outcome score

It does not store full prompts, message arrays, tool arguments, file contents, or
raw provider responses by default.

## Prompt Hashes

Prompt hashes are opt-in per request with:

```json
{
  "agent_hub": {
    "routing_memory_prompt_hash": true
  }
}
```

The hash is SHA-256 over the request text. It helps correlate repeated tasks
without storing the prompt itself.

## Prompt Storage

Full prompt storage is disabled unless explicitly configured:

```json
{
  "routing_memory_store_prompts": false
}
```

Use `true` only for local debugging in a trusted workspace.

## Retention And Reset

```json
{
  "routing_memory_enabled": true,
  "routing_memory_retention_days": 30
}
```

Reset memory:

```sh
curl -X DELETE http://127.0.0.1:8787/v1/routing-memory
```
