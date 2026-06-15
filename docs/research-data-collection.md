# Research Data Collection

Agent-Hub can collect local research data for studying AI routing, context
optimization, token efficiency, and model performance.

Automatic route telemetry is opt-in:

```sh
AGENT_HUB_RESEARCH_TELEMETRY=1 agent-hub serve
```

Logging is best-effort. Research write failures are ignored and never change
routing behavior or provider execution.

## Run Telemetry

Completed route outcomes are appended to:

```text
.agent-hub/research/runs.jsonl
```

Rows include:

- `task_id`
- `task_type`
- `selected_model`
- `candidate_models`
- `input_tokens`
- `output_tokens`
- `context_files`
- `context_token_count`
- `latency_ms`
- `cost_estimate`
- `validation_score`
- `success`
- `retry_count`

## Context Ablation

Context ablation records are written to:

```text
.agent-hub/research/context_ablation.jsonl
```

The standard context levels are `0`, `25`, `50`, `75`, and `100` percent.

## File Statistics

Per-file usefulness stats are written to:

```text
.agent-hub/research/file_stats.json
```

Each file tracks selections, successful inclusions, failed inclusions, and
average validation score.

## Dataset Export

Research datasets can be exported to:

```text
.agent-hub/research/dataset.csv
```

Columns include task type, model, context tokens, file count, latency, cost,
validation score, and success.

## Reports

Research reports are written to:

```text
.agent-hub/research/report.md
```

The report summarizes success rates, model comparison, average latency,
average cost, context statistics, and the most useful files.

Offline mathematical analysis can be generated with:

```sh
agent-hub research analyze
```

This writes:

```text
.agent-hub/research/analysis.json
.agent-hub/research/pareto_frontier.json
.agent-hub/research/information_density.json
.agent-hub/research/context_efficiency_curve.json
.agent-hub/research/context_efficiency_curve.md
.agent-hub/research/math_research_summary.md
```

The analysis layer computes success rates by model, task type, and context
bucket; validation and latency averages; retry rate; success per 1k context
tokens; cost per successful run; model efficiency scores; Pareto-optimal runs;
file-level information density; and context efficiency curves.

## Research Purpose

These artifacts support future mathematical research on information density,
context efficiency, Pareto routing, Bayesian model success estimation, and
multi-objective optimization.
