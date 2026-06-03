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
python -m agent_hub benchmark-suite --route coding --json
```

Scores are written to `.agent-hub/state/provider_scores.json`. The router adds
a small positive bias for providers with higher stored `overall_score`.

The benchmark suite compares static routing with adaptive routing. It reports
latency, success rate, failover frequency, cost, score deltas, workflow
effectiveness, and a winner, then writes a JSON report under
`.agent-hub/state/benchmark_reports`.

## API

```sh
curl http://127.0.0.1:8787/v1/provider-scores
```

The endpoint returns stored scores and benchmark task categories.
