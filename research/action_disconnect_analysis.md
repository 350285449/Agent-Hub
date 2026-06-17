# Action Disconnect Analysis

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Accepted Evidence vs Action

| group | rows | success rate | mean A4 understood | mean A5 linked | mean grounded-action ratio | mean evidence-to-action latency |
| --- | --- | --- | --- | --- | --- | --- |
| accepted/understood and connected | 275 | 0.898182 | 0.945455 | 0.597273 | 0.719359 | 0.369455 |
| accepted/understood but disconnected | 354 | 0.423729 | 0.079096 | 0.087571 | 0.092332 | 0.815113 |

## Action Mismatch Classes

| action chosen / mismatch | rows | failure rate | mean A4 understood | mean A5 linked | mean grounded-action ratio |
| --- | --- | --- | --- | --- | --- |
| switched path and lost linkage | 251 | 0.553785 | 0.083665 | 0.090305 | 0.105753 |
| no concrete grounded action | 103 | 0.631068 | 0.067961 | 0.080906 | 0.059628 |

## Representative Failed Rows

| row | model | repo | category | A2 | A3 | A4 | A5 | trajectory |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8108f870aedf | nemotron-3-super:cloud | Agent-Hub | bug_fix | 0.333 | 1.0 | 0.0 | 0.0 | discovered>recognized>accepted |
| a23ef0871628 | nemotron-3-super:cloud | Agent-Hub | bug_fix | 0.333 | 1.0 | 0.0 | 0.0 | discovered>recognized>accepted |
| 2a378b536970 | nemotron-3-super:cloud | Agent-Hub | bug_fix | 0.333 | 1.0 | 0.0 | 0.0 | discovered>recognized>accepted |
| 1dbaf7b426b8 | nemotron-3-super:cloud | Agent-Hub | bug_fix | 0.333 | 1.0 | 0.0 | 0.0 | discovered>recognized>accepted |
| fc37d55143c8 | gemma4:31b-cloud | Agent-Hub | bug_fix | 0.333 | 1.0 | 0.0 | 0.0 | discovered>recognized>accepted |
| d6f164b0a08d | nemotron-3-super:cloud | Agent-Hub | bug_fix | 0.333 | 1.0 | 0.0 | 0.0 | discovered>recognized>accepted |
| 2669246e0999 | nemotron-3-super:cloud | Agent-Hub | bug_fix | 0.333 | 1.0 | 0.0 | 0.0 | discovered>recognized>accepted |
| 5c81537e07ec | nemotron-3-super:cloud | Agent-Hub | bug_fix | 0.333 | 1.0 | 0.0 | 0.0 | discovered>recognized>accepted |
| fa39f1cc8f1e | nemotron-3-super:cloud | Agent-Hub | bug_fix | 0.333 | 1.0 | 0.0 | 0.0 | discovered>recognized>accepted |
| e969bf6bb618 | nemotron-3-super:cloud | Agent-Hub | bug_fix | 0.333 | 1.0 | 0.0 | 0.0 | discovered>recognized>accepted |
| 319a29ea0ac7 | gemma4:31b-cloud | Agent-Hub | bug_fix | 0.333 | 1.0 | 0.0 | 0.0 | discovered>recognized>accepted |
| 970353455235 | nemotron-3-super:cloud | Agent-Hub | bug_fix | 0.333 | 1.0 | 0.0 | 0.0 | discovered>recognized>accepted |

## Determination

The disconnect class crosses the accepted-evidence threshold, but the chosen action does not preserve the evidence link. In this dataset acceptance can come from the decisive-evidence signal even when the generated-output `A4_understood` marker remains low. The mismatch is visible as low `A5_linked_to_action`, low grounded-action ratio, high evidence-to-action latency, and often path-switching execution.
