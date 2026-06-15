# Architecture Modernization Phase 19

## Scope

Phase 19 adds the Agent-Hub research engine: local experimental telemetry,
multi-objective routing primitives, Bayesian success estimation,
information-density context selection, context ablation experiments,
epsilon-greedy reinforcement learning, and report artifact generation.

## Changes

- Added the `agent_hub.research` package.
- Appended route-start and route-outcome telemetry to
  `.agent-hub/research/runs.jsonl`.
- Added Pareto frontier utilities for quality/cost/latency comparisons.
- Added a Beta-distribution Bayesian success router keyed by model, task type,
  and context level.
- Added information-density context file selection under token budgets.
- Added context ablation experiment runner for 0%, 25%, 50%, 75%, and 100%
  context levels.
- Added epsilon-greedy bandit routing and reward calculation.
- Added Markdown and CSV research report generation.

## Compatibility

The research engine is additive. Telemetry writes are failure-isolated and do
not change routing decisions, provider payloads, endpoint schemas, or existing
state files.

## Verification

- `python -m pytest tests/test_research_engine.py`
- `python -m unittest tests.test_router tests.test_architecture_guardrails`
