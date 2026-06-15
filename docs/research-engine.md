# Agent-Hub Research Engine

Agent-Hub records local routing telemetry to turn normal usage into
experimental data. The default local output is:

```text
.agent-hub/research/runs.jsonl
```

Each route start and provider outcome appends a JSONL row with task/model,
token, context, latency, cost, retry, validation, and feedback fields.

## Modules

- `agent_hub.research.telemetry`: route and outcome JSONL recording.
- `agent_hub.research.metrics`: local run loading and summary metrics.
- `agent_hub.research.pareto`: quality/cost/latency Pareto frontier.
- `agent_hub.research.bayesian_router`: Beta-distribution success estimates by
  model, task type, and context level.
- `agent_hub.research.information_context`: information-density context file
  selection under a token budget.
- `agent_hub.research.experiments`: context ablation runner for 0%, 25%, 50%,
  75%, and 100% context.
- `agent_hub.research.rl_router`: epsilon-greedy bandit routing primitive.
- `agent_hub.research.report`: Markdown and CSV report generation.
- `agent_hub.research.analysis`: aggregate mathematical metrics and
  Pareto-optimal run detection.
- `agent_hub.research.information_density`: per-file information-density
  estimates.
- `agent_hub.research.context_curve`: context efficiency curve generation from
  dataset and ablation artifacts.
- `agent_hub.research.math_summary`: concise research summary for offline
  interpretation.
- `agent_hub.research.analyze`: one-shot orchestration for all research
  analysis artifacts.

`ContextPlanner.plan(..., research_mode=True)` can use information-density
selection directly. This is optional and keeps the default heuristic planner
unchanged.

## Report Artifacts

`generate_research_report(state_dir)` writes:

```text
.agent-hub/research/report.md
.agent-hub/research/pareto_frontier.csv
.agent-hub/research/context_efficiency.csv
.agent-hub/research/model_success_rates.csv
```

The report covers best models by task type, Pareto frontier, token efficiency,
context vs success, Bayesian success estimates, and routing policy comparison.
Model success CSV rows include Wilson confidence intervals, and the Markdown
report includes a text chart for context-token buckets versus success.

## Ablation Datasets

Use `write_context_ablation_dataset()` to expand benchmark tasks into 0%, 25%,
50%, 75%, and 100% context variants. Each row includes `context_percent`,
`ablation_parent_task_id`, and `research_experiment="context_ablation"`.

## Mathematical Analysis

Run the offline analyzer without changing routing behavior:

```sh
agent-hub research analyze
```

It reads the existing local research artifacts and writes:

```text
.agent-hub/research/analysis.json
.agent-hub/research/pareto_frontier.json
.agent-hub/research/information_density.json
.agent-hub/research/context_efficiency_curve.json
.agent-hub/research/context_efficiency_curve.md
.agent-hub/research/math_research_summary.md
```

Context buckets are fixed at `0 tokens`, `1-2k`, `2k-5k`, `5k-10k`,
`10k-25k`, and `25k+`. The summary highlights best models by success and
efficiency, best context bucket by success per token, diminishing-return
signals, high-density files, Pareto-optimal runs, and known data limitations.
