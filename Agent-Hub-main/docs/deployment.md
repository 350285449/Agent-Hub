# Deployment

Agent Hub ships basic deployment templates:

- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `examples/agent-hub.production.json`

Build and run:

```sh
docker compose up --build
```

Healthcheck:

```sh
curl http://127.0.0.1:8787/health
```

The container command runs:

```sh
agent-hub --config /config/agent-hub.config.json serve --host 0.0.0.0 --port 8787
```

Mount a config file at `/config/agent-hub.config.json`, workspace files at
`/workspace`, and state at `/data/.agent-hub`. Keep real `.env` values and
provider keys out of git.

Because the example container binds to `0.0.0.0`, Docker Compose requires
`AGENT_HUB_API_TOKEN` and `AGENT_HUB_TRUSTED_APPROVAL_TOKEN`. Agent Hub refuses
to start on a public bind without API authentication, and every endpoint
requires the API token. Enterprise audit events are written under the configured
state directory.

Use one of the shipped profiles:

- `examples/agent-hub.dev.json`: localhost development, shell disabled.
- `examples/agent-hub.local-power-user.json`: localhost shell access with approval.
- `examples/agent-hub.production.json`: public auth, privacy guardrails, no shell.

Before carrying an older config forward, inspect migrations:

```sh
python -m agent_hub --config /config/agent-hub.config.json migrate-config --json
```

Add `--write` to update renamed keys in place, or `--output` to write a new
file.

Optional real-provider stress checks are disabled unless explicitly requested:

```sh
AGENT_HUB_RUN_REAL_PROVIDER_STRESS=1 python scripts/real_provider_stress.py
```

The harness exercises repeated provider calls and failover reporting without
requiring API keys in the normal test suite.

For a clean second-machine acceptance check, clone the repo on that machine and
run:

```sh
python scripts/fresh_machine_acceptance.py --json
```

The script creates a temporary workspace and virtual environment, installs the
checkout, starts the server on a free localhost port, checks core HTTP
surfaces, and routes one diagnostic request through the local `echo` provider.
It does not require Ollama, LM Studio, API keys, provider quota, or existing
`.agent-hub` state.

For production-style local use, start from
`examples/agent-hub.production.json` and adjust provider keys, routes, plugin
directories, and context limits for your environment.
