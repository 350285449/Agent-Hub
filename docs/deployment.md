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

For production-style local use, start from
`examples/agent-hub.production.json` and adjust provider keys, routes, plugin
directories, and context limits for your environment.
