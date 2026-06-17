# Top 10 Overlap Matrix

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Overlap is Jaccard overlap across predeclared measured variables. High overlap is treated as evidence for collapse, not as support.

## Matrix

| theory | Runtime Integrity Theory | Decisive Evidence Theory | Runtime Control Theory | Branch Collapse Theory | State Reachability Theory | Information Flow Theory | Decisive Information Event Theory | Uncertainty Collapse Theory | Execution Lock-In Theory | Error Recovery Theory |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Runtime Integrity Theory | 1.0 | 0.154 | 0.133 | 0.143 | 0.111 | 0.455 | 0.25 | 0.231 | 0.231 | 0.2 |
| Decisive Evidence Theory | 0.154 | 1.0 | 0.0 | 0.0 | 0.0 | 0.3 | 0.2 | 0.083 | 0.0 | 0.0 |
| Runtime Control Theory | 0.133 | 0.0 | 1.0 | 0.0 | 0.118 | 0.071 | 0.167 | 0.0 | 0.25 | 0.889 |
| Branch Collapse Theory | 0.143 | 0.0 | 0.0 | 1.0 | 0.125 | 0.0 | 0.083 | 0.4 | 0.167 | 0.0 |
| State Reachability Theory | 0.111 | 0.0 | 0.118 | 0.125 | 1.0 | 0.0 | 0.0 | 0.125 | 0.2 | 0.176 |
| Information Flow Theory | 0.455 | 0.3 | 0.071 | 0.0 | 0.0 | 1.0 | 0.444 | 0.0 | 0.0 | 0.067 |
| Decisive Information Event Theory | 0.25 | 0.2 | 0.167 | 0.083 | 0.0 | 0.444 | 1.0 | 0.083 | 0.182 | 0.154 |
| Uncertainty Collapse Theory | 0.231 | 0.083 | 0.0 | 0.4 | 0.125 | 0.0 | 0.083 | 1.0 | 0.273 | 0.067 |
| Execution Lock-In Theory | 0.231 | 0.0 | 0.25 | 0.167 | 0.2 | 0.0 | 0.182 | 0.273 | 1.0 | 0.333 |
| Error Recovery Theory | 0.2 | 0.0 | 0.889 | 0.0 | 0.176 | 0.067 | 0.154 | 0.067 | 0.333 | 1.0 |

## Highest Pairwise Overlaps

| theory A | theory B | shared variables | union variables | Jaccard | shared fields |
| --- | --- | --- | --- | --- | --- |
| Runtime Control Theory | Error Recovery Theory | 8 | 9 | 0.888889 | branch_repair, correction_speed, first_recovery_event, first_verification_attempt, first_verification_success, retry_success, v3_final_recovered, v3_state_recovered |
| Runtime Integrity Theory | Information Flow Theory | 5 | 11 | 0.454545 | evidence_to_action_latency, first_grounding_event, first_successful_tool_call, first_verification_success, grounded_action_ratio |
| Information Flow Theory | Decisive Information Event Theory | 4 | 9 | 0.444444 | first_decisive_evidence, first_grounding_event, first_retrieval_event, first_verification_success |
| Branch Collapse Theory | Uncertainty Collapse Theory | 4 | 10 | 0.4 | dyn_signal_50, dyn_signal_75, first_branch_collapse, v3_final_converging |
| Execution Lock-In Theory | Error Recovery Theory | 4 | 12 | 0.333333 | correction_speed, first_recovery_event, retry_success, v3_final_stuck |
| Decisive Evidence Theory | Information Flow Theory | 3 | 10 | 0.3 | evidence_to_action_latency, first_decisive_evidence, first_grounding_event |
| Uncertainty Collapse Theory | Execution Lock-In Theory | 3 | 11 | 0.272727 | first_branch_collapse, v3_final_converging, v3_final_stuck |
| Runtime Integrity Theory | Decisive Information Event Theory | 3 | 12 | 0.25 | first_branch_collapse, first_grounding_event, first_verification_success |
| Runtime Control Theory | Execution Lock-In Theory | 3 | 12 | 0.25 | correction_speed, first_recovery_event, retry_success |
| Runtime Integrity Theory | Uncertainty Collapse Theory | 3 | 13 | 0.230769 | first_branch_collapse, v3_final_converging, v3_final_stuck |
| Runtime Integrity Theory | Execution Lock-In Theory | 3 | 13 | 0.230769 | first_branch_collapse, v3_final_converging, v3_final_stuck |
| Runtime Integrity Theory | Error Recovery Theory | 3 | 15 | 0.2 | first_verification_attempt, first_verification_success, v3_final_stuck |
| Decisive Evidence Theory | Decisive Information Event Theory | 2 | 10 | 0.2 | first_decisive_evidence, first_grounding_event |
| State Reachability Theory | Execution Lock-In Theory | 3 | 15 | 0.2 | state_switches, v3_final_converging, v3_final_stuck |
| Decisive Information Event Theory | Execution Lock-In Theory | 2 | 11 | 0.181818 | first_branch_collapse, first_recovery_event |
| State Reachability Theory | Error Recovery Theory | 3 | 17 | 0.176471 | v3_final_recovered, v3_final_stuck, v3_state_recovered |
| Runtime Control Theory | Decisive Information Event Theory | 2 | 12 | 0.166667 | first_recovery_event, first_verification_success |
| Branch Collapse Theory | Execution Lock-In Theory | 2 | 12 | 0.166667 | first_branch_collapse, v3_final_converging |
| Runtime Integrity Theory | Decisive Evidence Theory | 2 | 13 | 0.153846 | evidence_to_action_latency, first_grounding_event |
| Decisive Information Event Theory | Error Recovery Theory | 2 | 13 | 0.153846 | first_recovery_event, first_verification_success |
