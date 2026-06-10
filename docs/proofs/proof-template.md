# Agent-Hub Proof: <repo or workflow>

## Summary

- Baseline:
- Tasks:
- Repository Size:
- Workflow:
- Dataset:
- Dataset Fingerprint:
- Date:

## Results

- Cost Reduction:
- Latency Reduction:
- Success Rate:

## Route Replay

Request ID:

```text
agent-hub replay-route <request-id>
```

Selected:

Alternatives:

Reason:

## Reproduction

```sh
agent-hub benchmark --dataset coding-100 --baseline <baseline-model> --route coding --export results.json
agent-hub benchmark verify results.json --dataset coding-100
agent-hub generate-proof
agent-hub benchmark-card --variant markdown
agent-hub generate-case-study --output docs/proofs/<proof-name>.md
```

## Notes

Remove secrets, private paths, customer data, and proprietary prompt text before
submitting proof publicly.
