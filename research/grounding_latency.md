# Grounding Latency

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Latency Summary

| group | rows | time to decisive evidence | time to grounding | evidence-to-action latency | grounding score | success rate |
| --- | --- | --- | --- | --- | --- | --- |
| all | 918 | 0.409423 | 0.409423 | 0.425 | 0.438378 | 0.58061 |
| successful | 533 | 0.360225 | 0.360225 | 0.384615 | 0.526595 | 1.0 |
| failed | 385 | 0.477532 | 0.477532 | 0.480909 | 0.31625 | 0.0 |
| grounded execution | 247 | 0.126316 | 0.126316 | 0.379757 | 0.767623 | 0.88664 |
| no grounded execution | 671 | 0.513636 | 0.513636 | 0.441654 | 0.317181 | 0.467958 |

## Findings

Successful runs ground earlier and have lower evidence-to-action latency. The shortest path to grounding is early decisive evidence followed immediately by evidence-to-action conversion. Late evidence can still help, but it often arrives after the trajectory has already spent its action budget on an ungrounded path.
