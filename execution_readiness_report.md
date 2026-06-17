# Execution Readiness Report

Date: 2026-06-17

## Certification Inputs

- Provider audit: `research/provider_audit.md`
- Prior readiness certification: `research/readiness_certification.md`
- Provider adapter code: `agent_hub/providers/*`
- Provider attempt/failover code: `agent_hub/core/provider_attempts.py`
- Frozen panel runner: `scripts/frozen_panel_executor.py`
- Instrumentation: `agent_hub/research/gct_instrumentation.py`
- Readiness utilities: `agent_hub/research/gct_readiness.py`
- Dashboard stub: `deploy/grafana/agent-hub-dashboard.json`

Validation run:

```text
pytest tests/test_gct_instrumentation.py tests/test_grounding_integrity_randomized_trial.py tests/test_provider_sdk.py tests/test_provider_compatibility.py -q
19 passed, 4 subtests passed

python scripts/frozen_panel_executor.py --limit 2 --allow-incomplete
ready=false
```

The dry-run result is expected to be `ready=false` because execution certification requires live execute mode and full row count.

## Readiness Classification

| Area | Classification | Reason |
| --- | --- | --- |
| Provider readiness | Blocked | Direct cloud credentials are missing, quota/cost probes are incomplete, schema enforcement is not provider-neutral |
| Instrumentation readiness | Partially ready | GAR, commitment, and intervention validators exist; one numeric parsing bug was fixed; external truth linkage still required |
| Experiment readiness | Blocked | Frozen sequential runner exists, but distributed execution and resume support are missing |

## Prioritized Blocker List

| Order | Blocker | Severity | Estimated Effort | Expected Impact |
| --- | --- | --- | --- | --- |
| 1 | Configure and certify at least two live cloud providers with credentials, quota probes, and model availability checks | Critical | 1-2 days after credentials exist | Enables real multi-provider cloud execution |
| 2 | Add provider-neutral structured output/schema enforcement to the adapter contract | Critical | 3-5 days | Prevents malformed JSON from entering experiments and makes retries/failover deterministic |
| 3 | Add resumable frozen-panel row state and avoid deleting prior ledgers on resume | Critical | 1-2 days | Allows long experiments to recover from interruption |
| 4 | Add distributed worker leases and shard execution | High | 3-5 days | Enables large-scale cloud panels instead of sequential local runs |
| 5 | Add immutable experiment manifests with dataset/config/schema/code hashes | High | 1-2 days | Makes panel outputs auditable and reproducible |
| 6 | Add provider-attempt ledger with request id, provider, model, schema hash, retry reason, failover reason, usage, latency, and cost | High | 2-3 days | Makes failure recovery and cost accounting reliable |
| 7 | Add real cost tables or configured rates for every enabled cloud provider | High | 1 day | Prevents runaway spend and supports preflight budget approval |
| 8 | Add quota/budget preflight before panel execution | High | 1-2 days | Fails early when provider accounts cannot complete the run |
| 9 | Export experiment progress and instrumentation coverage metrics | Medium | 2-3 days | Makes large runs observable while in flight |
| 10 | Replace dashboard stub metrics with emitted Prometheus metrics | Medium | 1-2 days | Makes the dashboard operational instead of illustrative |

## Implementation Order

1. Provider certification: credentials, reachability, quota, cost, minimum two live cloud providers.
2. Schema enforcement: common structured output spec, JSON Schema validation, provider-native translation, retry/failover on schema failure.
3. Runner durability: row state machine, resume, append-only logs, immutable manifests.
4. Distributed execution: local file leases first, then Redis/Postgres/S3 backend if needed.
5. Observability: provider-attempt ledger, experiment metrics, instrumentation coverage, dashboard update.
6. Full certification: execute exactly 200 frozen rows live, no replay/synthetic rows, no accepted malformed outputs, at least two cloud providers, all instrumentation gates valid.

## Final Verdict

B. Engineering blocked.

The infrastructure is beyond research-only scaffolding: provider adapters, failover, instrumentation, validation, quarantine, and frozen-panel dry-run mechanics exist. It is not execution-ready because large-scale live cloud execution still lacks certified cloud credentials/quota/costs, provider-neutral schema enforcement, distributed/resumable execution, and an operational dashboard for experiment/instrumentation coverage.

