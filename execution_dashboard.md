# Execution Dashboard

## Current State

Agent-Hub has local observability streams and a Grafana dashboard stub:

- `agent_hub.observability.metrics_snapshot()` reports provider totals, available/degraded counts, token usage, provider failures, routing fallbacks, stream failures, context truncations, tool executions, recent failures, routing decisions, request traces, and internal events.
- `agent_hub.observability_export.prometheus_lines()` exports generic `agent_hub_counter{name="..."}` counters.
- `deploy/grafana/agent-hub-dashboard.json` includes basic panels for provider health, tokens, latency, failures, agent success, and token savings.

## Requirement Coverage

| Requirement | Current Status | Gap |
| --- | --- | --- |
| Provider health | Partial | Dashboard references metric names that are not emitted by `prometheus_lines()` |
| Experiment progress | Missing | No panel-level row state metrics |
| Failure rates | Partial | Provider failure counters exist in snapshots; dashboard needs rate panels |
| Instrumentation coverage | Missing | No GAR/commitment/intervention coverage metrics |

## Required Metrics

Provider metrics:

```text
agent_hub_provider_available{agent,provider,model}
agent_hub_provider_degraded{agent,provider,model}
agent_hub_provider_latency_ms{agent,provider,model}
agent_hub_provider_failures_total{agent,provider,model,error_type}
agent_hub_provider_failover_total{from_agent,to_agent,error_type}
agent_hub_provider_cost_estimate_usd_total{agent,provider,model}
```

Experiment metrics:

```text
agent_hub_experiment_rows_total{experiment_id,panel}
agent_hub_experiment_rows_completed{experiment_id,panel}
agent_hub_experiment_rows_failed{experiment_id,panel}
agent_hub_experiment_rows_quarantined{experiment_id,panel}
agent_hub_experiment_progress_ratio{experiment_id,panel}
```

Instrumentation metrics:

```text
agent_hub_instrumentation_gar_valid_rows{experiment_id,panel}
agent_hub_instrumentation_commitment_valid_rows{experiment_id,panel}
agent_hub_instrumentation_intervention_valid_rows{experiment_id,panel}
agent_hub_instrumentation_coverage_ratio{experiment_id,panel,event_type}
agent_hub_malformed_output_total{experiment_id,panel,provider,model,phase}
```

## Dashboard Layout

1. Provider Health
   - available providers
   - degraded providers
   - current cooldowns
   - quota/rate-limit failures

2. Experiment Progress
   - completed / total rows
   - running rows
   - failed rows
   - quarantined rows
   - estimated time remaining

3. Failure Rates
   - failures by provider
   - failures by error type
   - malformed output by phase
   - failover chain frequency

4. Instrumentation Coverage
   - GAR-valid row count
   - commitment-valid row count
   - intervention-valid row count
   - missing event types by row

5. Cost and Quota
   - estimated cost by provider
   - input/output tokens by provider
   - quota exhausted/rate-limited events

## Readiness Decision

The current dashboard is operations-adjacent but not execution-ready. It tracks general runtime health, not panel progress or instrumentation coverage. The immediate blocker is exporter/dashboard metric mismatch.

