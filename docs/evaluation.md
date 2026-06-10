# Provider Evaluation

Provider evaluation stores observed model quality instead of relying only on
static config scores.

## Benchmark Types

- coding
- reasoning
- summarization
- tool calling
- long context
- latency

## Run

```sh
python -m agent_hub eval --route coding --json
python -m agent_hub benchmark-suite --route coding --limit 24 --json
agent-hub benchmark --dataset coding-100 --export results.json
agent-hub benchmark verify results.json --dataset coding-100
agent-hub benchmark compare --baseline claude-sonnet --dataset coding-100
```

Scores are written to `.agent-hub/state/provider_scores.json`. The router adds
a small positive bias for providers with higher stored `overall_score`.

The benchmark suite compares static routing with adaptive routing. It reports
latency, success rate, failover frequency, cost, score deltas, workflow
effectiveness, and a winner, then writes a JSON report under
`.agent-hub/state/benchmark_reports`.

The built-in suite contains 24 coding, reasoning, summarization, tool-calling,
long-context, and latency tasks. Up to 50 custom tasks can be run in one suite.

## Public Benchmark Datasets

Reproducible datasets live under `benchmarks/` with a manifest at
`benchmarks/manifest.json`.

- `coding-100` is the high-signal public proof dataset for coding workflows.
- `proof-50` is the default mixed proof dataset.

One-click export:

```sh
agent-hub benchmark --dataset coding-100 --baseline claude-sonnet --route coding --export results.json
```

Shareable comparison:

```sh
agent-hub benchmark compare --baseline claude-sonnet --dataset coding-100
agent-hub benchmark compare results.json --dataset coding-100
```

Verification mode reruns the dataset fingerprint checks against the current
public corpus and the exported report:

```sh
agent-hub benchmark verify results.json --dataset coding-100
```

Every proof report includes the dataset name, task count, fingerprint, rerun
command, and verify command so results can be compared without trusting a
server.

## API

```sh
curl http://127.0.0.1:8787/v1/provider-scores
curl http://127.0.0.1:8787/v1/model-leaderboard
curl http://127.0.0.1:8787/v1/benchmarks
```

The leaderboard and benchmark endpoints include a `summary` object and an
`empty_state` object when there is not enough measured data yet. The matching
dashboard pages (`/dashboard/model-leaderboard` and `/dashboard/benchmarks`)
show the same guidance as readable setup instructions instead of an empty JSON
blob.

`/health`, `agent-hub health --json`, and `/v1/readiness` also surface this data
state. A route-ready setup can score highly before benchmark reports exist, but
the readiness score keeps a warning on `data_products` until leaderboard samples
or benchmark reports have been recorded.
