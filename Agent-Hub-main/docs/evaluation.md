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
- `before-after-10` is the Marketplace proof dataset for raw-agent versus
  Agent Hub comparisons across large refactors, cross-file bugs, missing
  context recovery, UI plus backend changes, test generation, and vague repair
  requests.

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

## Before/After Proof Matrix

Run each baseline against the same dataset and compare the exported report:

| Scenario | Baseline command | Agent Hub comparison |
| --- | --- | --- |
| Claude Code alone vs Claude Code + Agent Hub | `agent-hub benchmark --dataset before-after-10 --baseline claude-sonnet --route coding --export claude.json` | `agent-hub benchmark compare claude.json --dataset before-after-10` |
| Codex alone vs Codex + Agent Hub | `agent-hub benchmark --dataset before-after-10 --baseline codex --route coding --export codex.json` | `agent-hub benchmark compare codex.json --dataset before-after-10` |
| Cline alone vs Cline + Agent Hub | Run the `before-after-10` prompts through Cline CLI or VS Code Cline with its normal provider. | Point Cline at Agent Hub (`Base URL /v1`, model `agent-hub-coding`) and run the same prompts, or configure a `cline` baseline agent before using `agent-hub benchmark compare`. |

Track these fields from `benchmark-report.json`:

| Metric | Report field |
| --- | --- |
| Tokens used | `comparison.token_reduction` |
| Raw vs optimized request tokens actually sent | `token_savings_proof` |
| Cost | `comparison.cost_reduction` |
| Retries | `comparison.prompt_loops_avoided` and per-task `failover_count` |
| Task success | `comparison.success_delta` and `agent_hub_summary.success_rate` |
| Patch quality | `agent_hub_summary.quality_score` and per-task `score_delta` |
| Files touched | provider/tool logs for the benchmark session |
| Time to useful output | `time_to_working_solution_ms` and `average_latency_ms` |

Token savings must be calculated from the raw agent request tokens versus the
Agent Hub optimized request tokens actually sent. The proof report writes this
as `token_savings_proof.not_repo_size_delta: true`; do not publish savings that
are only `original repo size - compressed repo size`.

## Stress Cases

Use `before-after-10` before publishing screenshots or marketplace claims. It
includes tasks where optimization can hurt quality:

| Failure case | Covered by |
| --- | --- |
| Large refactor | `before-after-001`, `before-after-009` |
| Cross-file bug | `before-after-002` |
| Missing context bug | `before-after-003`, `before-after-010` |
| UI plus backend change | `before-after-004` |
| Test generation | `before-after-005` |
| Vague request like "fix this app" | `before-after-006` |

If context compression removes needed context, the expected recovery behavior is
to detect the missing symbol or file, retry once with the omitted context, and
record the recovered attempt in the failover/retry fields.

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
