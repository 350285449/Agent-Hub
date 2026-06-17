# Intervention Engine Design

Scope: deployable Agent-Hub intervention engine for Grounding Integrity warnings.

## Objective

The intervention engine selects the cheapest sufficient repair for a live grounding warning. It should be deterministic, auditable, configurable, and conservative near finalization or external action.

## Inputs

| input | description |
| --- | --- |
| integrity metrics | current and previous metric vector |
| warning class | contradiction, collapse, mismatch, low reuse, unsupported evidence, delayed grounding |
| warning level | 0 clean, 1 watch, 2 caution, 3 intervention, 4 block |
| execution window | 0%-25%, 25%-50%, 50%-75%, 75%-100% |
| decision relevance | whether the evidence affects the selected action or final answer |
| prior repairs | interventions already attempted in the session |
| task risk | coding, shell/tool use, security-sensitive action, provider cost, user-visible final answer |
| cost budget | max additional tokens and latency for the request |

## Outputs

| output | description |
| --- | --- |
| intervention | selected repair command |
| reason | trigger and metric basis |
| severity | effective warning level after policy adjustment |
| continuation decision | continue, pause-and-repair, block, or allow with warning |
| audit event | persisted intervention event with costs and outcome |

## Intervention Catalog

| intervention | cost units | expected failure reduction | primary use |
| --- | ---: | ---: | --- |
| evidence recheck | 1 | 18%-22% | low evidence reuse or weak interpretation |
| contradiction resolution | 2 | 23%-27% | decision-relevant contradiction after evidence recognition |
| action consistency check | 2 | 22%-25% | grounded-action decline or evidence-action mismatch |
| evidence verification | 3 | 20%-24% | unsupported accepted evidence |
| grounding confirmation | 4 | 25%-28% | collapse, severe warning, or pre-final gate |

The estimates are single-policy effects and overlap. They must not be summed linearly.

## Policy

| condition | action |
| --- | --- |
| no decision-relevant evidence exists | observe only |
| low reuse and no contradiction | evidence recheck |
| unsupported accepted evidence | evidence verification |
| one unresolved decision-relevant contradiction | contradiction resolution |
| accepted evidence implies different action | action consistency check |
| grounded-action ratio declines materially with weak linkage | action consistency check |
| accepted evidence disappears from action plan | grounding confirmation |
| same warning persists after one targeted repair | escalate one cost tier |
| level 3 warning remains in 75%-100% window | grounding confirmation |
| level 4 warning remains after confirmation | block finalization or external action |

## Pseudocode

```text
if not evidence_is_decision_relevant:
    return continue_or_watch()

warning = classify_warning(metrics, events)
level = assign_warning_level(warning, metrics, execution_window)

if level <= 1:
    return continue_with_logging()

if warning == "contradictory_grounding":
    intervention = "contradiction_resolution"
elif warning == "evidence_action_mismatch":
    intervention = "action_consistency_check"
elif warning == "grounded_action_ratio_decline":
    intervention = "action_consistency_check"
elif warning == "unsupported_accepted_evidence":
    intervention = "evidence_verification"
elif warning == "low_evidence_reuse":
    intervention = "evidence_recheck"
elif warning == "grounding_collapse":
    intervention = "grounding_confirmation"
else:
    intervention = "evidence_recheck"

if prior_targeted_repair_failed(warning):
    intervention = escalate(intervention)

if execution_window == "75_100" and level >= 3:
    intervention = "grounding_confirmation"

result = run_repair(intervention)

if result.clears_warning:
    return continue_repaired()
if result.downgrades_warning and level < 4:
    return continue_with_warning()
if execution_window == "75_100" or action_is_external:
    return block()
return continue_with_warning_and_audit()
```

## Component Designs

### Contradiction Detector

Detects conflicts between surfaced evidence and current interpretation.

| step | behavior |
| --- | --- |
| normalize evidence | extract decision-relevant claims from file, tool, test, provider, or user evidence |
| normalize interpretation | extract accepted facts and action assumptions |
| compare | classify conflict as direct negation, incompatible value, unsupported inference, stale assumption, or missing qualifier |
| score relevance | raise severity only when conflict affects planned action or final answer |
| emit warning | include evidence id, conflicting claim, interpretation claim, relevance, and suggested repair |

Trigger: one unresolved decision-relevant contradiction after evidence recognition.

### Grounding Confirmation System

Confirms that the full chain remains intact.

| check | pass condition |
| --- | --- |
| evidence exists | decision-relevant claims point to source/file/test/tool/user input |
| evidence interpreted | accepted facts follow from evidence without unresolved contradiction |
| action linked | planned or final action explicitly preserves accepted evidence |
| evidence retained | no accepted evidence disappears from final action unless superseded |
| verification sufficient | high-risk evidence has a concrete verifier |

Trigger: grounding collapse, severe warning, or unresolved pre-final warning.

### Evidence Verification System

Prevents unsupported evidence acceptance.

| verifier | examples |
| --- | --- |
| source verifier | cited URL, provider result, API response, user-provided fact |
| file verifier | local file path and line/section reference |
| test verifier | passing/failing test result or benchmark artifact |
| tool verifier | structured tool output id |
| trace verifier | prior event in same grounding session |

Trigger: accepted evidence lacks source, file, test, tool, or trace support.

### Action Consistency System

Checks whether the selected action follows accepted evidence.

| check | fail condition |
| --- | --- |
| implication check | accepted evidence implies a different action |
| citation/linkage check | action does not preserve or reference decision-relevant evidence |
| drift check | action changes after evidence acceptance without revalidation |
| finalization check | final answer claims exceed verified evidence |

Trigger: evidence-action mismatch, grounded-action ratio decline, or material action change.

## Escalation Ladder

| current repair | escalate to |
| --- | --- |
| evidence recheck | evidence verification |
| evidence verification | contradiction resolution or action consistency check, depending on warning |
| contradiction resolution | grounding confirmation |
| action consistency check | grounding confirmation |
| grounding confirmation | block finalization or require manual/user-visible caveat |

## Observability

Each intervention should write:

| field | meaning |
| --- | --- |
| `trigger` | warning that fired |
| `selected_intervention` | repair selected by engine |
| `cost_units` | 1-4 relative cost |
| `tokens_in_delta` and `tokens_out_delta` | measured incremental tokens |
| `latency_ms_delta` | measured incremental latency |
| `pre_warning_level` and `post_warning_level` | repair effect |
| `continuation_decision` | continued, blocked, overridden, failed |
| `outcome_success` | whether warning cleared or downgraded |

## Determination

The engine should start as a rule-based staged policy. A learned policy can be considered only after production logs contain enough intervention outcomes to compare repairs fairly. The highest-ROI behavior is immediate contradiction resolution, action consistency checks on material action changes, and pre-final grounding confirmation for unresolved warnings.
