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
