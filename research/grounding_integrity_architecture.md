# Grounding Integrity Architecture

Scope: Agent-Hub cloud-only deployment architecture. Inputs are the established Grounding Integrity findings from the aligned cloud panel: 918 rows, 385 failures, 533 successes.

## Design Goal

Grounding Integrity is a runtime control subsystem that keeps the evidence -> interpretation -> action chain intact after evidence begins to appear. It is not a pre-run prediction feature. It is an online safety and reliability layer that detects degraded grounding, triggers the cheapest sufficient repair, and blocks finalization when decision-relevant evidence remains disconnected from the action.

## Placement In Agent-Hub

| layer | integration point | responsibility |
| --- | --- | --- |
| request/runtime | provider attempt execution and workflow stages | attach a `grounding_session_id` and execution window clock |
| context/evidence | repository context, tool results, web/provider evidence, user-provided facts | emit evidence recognition, acceptance, verification, reuse, and retention events |
| reasoning/action | planner, coder, reviewer, tool loop, final response assembly | emit interpretation summaries, planned actions, action changes, and final claims |
| observability | JSONL event streams and metrics snapshots | persist integrity state, warnings, interventions, costs, and outcomes |
| control | new Grounding Integrity subsystem | detect warnings, trigger repair, gate finalization |

Recommended package layout:

| module | purpose |
| --- | --- |
| `agent_hub.grounding.events` | typed execution events for evidence, interpretation, action, verification, and intervention |
| `agent_hub.grounding.monitor` | live metric calculation and state tracking |
| `agent_hub.grounding.contradiction` | contradiction detection and resolution request generation |
| `agent_hub.grounding.verification` | verifier selection and evidence support checks |
| `agent_hub.grounding.action_consistency` | planned-action and final-action consistency checks |
| `agent_hub.grounding.confirmation` | full-chain confirmation gate |
| `agent_hub.grounding.interventions` | warning severity, intervention selection, escalation, and outcome logging |

## Runtime Flow

1. Start a grounding session when a cloud provider request or workflow execution begins.
2. Observe only during the 0%-25% execution window unless evidence is already decision-relevant.
3. When evidence appears, record recognized evidence, accepted evidence, interpretation, verifier, and action-link events.
4. Run contradiction scans after each decision-relevant evidence or interpretation update.
5. Run metric updates after every action proposal, tool result, material plan change, and pre-final draft.
6. Trigger intervention when a warning crosses threshold.
7. Continue only when the repair result clears the warning or downgrades it below the active gate.
8. Run mandatory pre-final confirmation when any earlier warning remains unresolved or the request is high-risk.
9. Log integrity metrics, triggered intervention, token cost, latency cost, and outcome.

## Core Components

| component | input | output | deployment role |
| --- | --- | --- | --- |
| integrity monitor | evidence events, interpretation summaries, action proposals, verification events | metric vector, warning candidates, integrity state | low-latency always-on telemetry |
| contradiction detector | accepted facts, raw evidence snippets, current interpretation | contradiction warning with evidence ids and conflict class | earliest high-value trigger |
| grounding confirmation system | evidence chain, interpretation chain, planned/final action | pass, repair-needed, or block-finalization decision | strongest single intervention |
| evidence verification system | accepted evidence, source/file/test/tool references | verifier status and support confidence | prevents unsupported evidence acceptance |
| action consistency system | accepted evidence, action proposal, final answer or tool call | action-evidence consistency result | preserves the strongest operational metric |
| intervention engine | warning class, severity, timing window, prior repairs, cost budget | selected repair, escalation state, continuation decision | staged control policy |

## State Model

| state | meaning | allowed next states |
| --- | --- | --- |
| `observing` | no decision-relevant evidence yet | `evidence_recognized`, `complete` |
| `evidence_recognized` | evidence exists but may not be accepted | `evidence_accepted`, `contradicted`, `unsupported`, `complete` |
| `evidence_accepted` | evidence is used by interpretation | `action_linked`, `contradicted`, `unsupported`, `collapsed` |
| `action_linked` | planned action preserves accepted evidence | `verified`, `mismatched`, `collapsed`, `complete` |
| `verified` | evidence has concrete source, file, test, trace, or tool support | `complete`, `mismatched`, `collapsed` |
| `contradicted` | evidence conflicts with interpretation | `repairing`, `blocked`, `complete_with_warning` |
| `mismatched` | accepted evidence implies a different action than selected | `repairing`, `blocked`, `complete_with_warning` |
| `collapsed` | evidence was accepted but no longer controls action | `repairing`, `blocked`, `complete_with_warning` |
| `repairing` | intervention is active | `evidence_accepted`, `action_linked`, `verified`, `blocked` |
| `blocked` | severe unresolved warning prevents finalization | manual override or failed request |

## Warning Levels

| level | name | meaning | default behavior |
| ---: | --- | --- | --- |
| 0 | clean | evidence, interpretation, and action are aligned | continue |
| 1 | watch | weak signal, low decision relevance, or early incomplete chain | record and continue |
| 2 | caution | decision-relevant evidence is weakly reused, unsupported, or drifting | run low/moderate repair |
| 3 | intervention | contradiction, mismatch, or grounded-action decline is decision-relevant | pause and repair |
| 4 | block | unresolved severe warning before final answer or external action | block finalization/action |

## Non-Goals

The subsystem should not invent new task primitives, replace provider routing, or run expensive confirmation on every minor exploratory statement. Its job is staged control: detect the first meaningful integrity break, repair the chain, and preserve measurable runtime evidence.

## Deployment Determination

Agent-Hub should deploy Grounding Integrity as a staged runtime control loop. The first deployable slice is event schema plus metric monitor. The first high-impact detector is contradiction detection. The highest-value gate is pre-final grounding confirmation, but it should be cost-controlled by warning severity and timing window.
