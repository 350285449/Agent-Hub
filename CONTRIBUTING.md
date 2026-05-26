# Contributing

Thanks for helping improve Agent-Hub. This project is backend-first AI
infrastructure, so changes should preserve compatibility with existing
OpenAI-compatible, Anthropic-compatible, native, Cline, Continue, and VS Code
workflows.

## Development

1. Create a branch for the change.
2. Keep provider-specific behavior inside provider adapters.
3. Keep routing, health, context, workflow, and tool changes modular.
4. Add or update focused tests for behavior changes.
5. Run:

```sh
python -m unittest discover -s tests
python -m compileall -q agent_hub
```

## Pull Requests

Include:

- What changed and why.
- Compatibility impact.
- New configuration fields or endpoints.
- Tests run.
- Known limitations or follow-up work.

Do not commit local config files, API keys, `.agent-hub/` state, build
artifacts, `.vsix` packages, or provider health state.
