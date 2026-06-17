# Agent-Hub Control Architecture

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. This design specifies a real-time Grounding Integrity system for Agent-Hub.

## Architecture

| component | responsibility | inputs | outputs |
| --- | --- | --- | --- |
| integrity monitor | track Grounding Integrity during execution | evidence events, interpretation notes, action proposals, verification events | integrity state and metric deltas |
| contradiction detector | detect conflicts between surfaced evidence and interpretation | evidence text, accepted facts, current reasoning summary | contradiction warning |
| intervention engine | select the cheapest sufficient repair | warning class, severity, timing window, prior repairs | repair command |
| recovery engine | execute repair and decide whether execution may continue | repair command, evidence chain, action proposal | repaired chain or escalation |

## Runtime Flow

1. Evidence appears.
2. Integrity monitor records evidence recognition, reuse, verification, and action linkage.
3. Contradiction detector compares evidence against the current interpretation.
4. Intervention engine triggers the lowest-cost sufficient repair.
5. Recovery engine performs evidence recheck, verification, contradiction resolution, action consistency, or grounding confirmation.
6. Execution continues only if the action remains linked to verified evidence.

## Component Contracts

| component | must expose | minimum decision rule |
| --- | --- | --- |
| integrity monitor | grounded-action ratio, evidence reuse, evidence-action consistency, evidence retention, latency | flag decline after evidence has appeared |
| contradiction detector | contradiction class, evidence item, conflicting interpretation | trigger on one decision-relevant unresolved contradiction |
| intervention engine | selected intervention, cost tier, reason | escalate from recheck to confirmation only when needed |
| recovery engine | repair result, residual warning state, continuation decision | block finalization if severe warning remains unresolved |

## Trigger-To-Repair Map

| trigger | repair |
| --- | --- |
| contradictory grounding | contradiction resolution |
| low evidence reuse | evidence recheck |
| unsupported accepted evidence | evidence verification |
| grounded-action ratio decline | action consistency check |
| evidence-action mismatch | action consistency check |
| grounding collapse | grounding confirmation |
| unresolved warning before final output | grounding confirmation |

## Implementation Roadmap

| phase | implementation item | outcome |
| ---: | --- | --- |
| 1 | add execution event schema for evidence, interpretation, verification, and action linkage | monitor has the raw material needed for control |
| 2 | implement integrity monitor metrics | grounded-action ratio and evidence-action consistency become live signals |
| 3 | implement contradiction detector | earliest warning becomes actionable |
| 4 | implement action consistency gate | accepted evidence must survive into action |
| 5 | implement grounding confirmation gate | full-chain repair before final output |
| 6 | log intervention cost and outcome | recovery estimates become measurable in production |
| 7 | run policy tournament online | compare no-op shadow policy against staged combined policy |

## Determination

Agent-Hub should implement a staged real-time Grounding Integrity system. The monitor should run continuously after evidence appears, the contradiction detector should trigger early, the intervention engine should choose the cheapest sufficient repair, and the recovery engine should block finalization when the evidence-interpretation-action chain remains broken.
