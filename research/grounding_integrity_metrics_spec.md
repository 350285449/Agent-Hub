# Grounding Integrity Metrics Specification

Scope: metrics, thresholds, warning levels, and intervention triggers for Agent-Hub cloud-only runtime deployment.

Baseline panel: 918 aligned cloud rows, 385 failures, 533 successes. The strongest individual metric is `grounded_action_ratio`; the earliest high-value warning is decision-relevant contradictory grounding in the 25%-50% execution window.

## Metric Definitions

| metric | definition | range | direction | primary use |
| --- | --- | ---: | --- | --- |
| `grounded_action_ratio` | share of material action steps linked to accepted evidence | 0.0-1.0 | higher is better | strongest control metric |
| `evidence_reuse` | share of decision-relevant evidence reused in interpretation, action, verification, or final claims | 0.0-1.0 | higher is better | low-cost early drift signal |
| `evidence_action_consistency` | share of accepted evidence whose implication matches the planned or final action | 0.0-1.0 | higher is better | action consistency gate |
| `grounding_latency_integrity` | inverse delay between evidence recognition and decisive grounding | 0.0-1.0 | higher is better | timing risk signal |
| `evidence_interpretation_accuracy` | share of surfaced evidence interpreted without contradiction or unsupported inference | 0.0-1.0 | higher is better | contradiction and interpretation repair |
| `evidence_retention` | share of accepted evidence retained through action planning and finalization | 0.0-1.0 | higher is better | collapse detection |
| `contradiction_count` | unresolved conflicts between evidence and interpretation | integer | lower is better | earliest intervention trigger |
| `unsupported_evidence_count` | accepted evidence without source, file, test, trace, or tool support | integer | lower is better | verification trigger |

## Metric Priority

| rank | metric | measured support |
| ---: | --- | --- |
| 1 | `grounded_action_ratio` | AUC 0.888536; holdout R2 gain 0.139998; low metric covered 91.4% of failures |
| 2 | `evidence_reuse` | AUC 0.893960; holdout R2 gain 0.124376; low metric covered 92.7% of failures |
| 3 | `evidence_action_consistency` | AUC 0.812736; directly maps to action repair |
| 4 | `grounding_latency_integrity` | weaker single metric, useful for timing gates |
| 5 | `evidence_retention` | lower holdout gain but useful for collapse detection |
| 6 | `evidence_interpretation_accuracy` | weak as a broad scalar, important when paired with contradiction events |

## Thresholds

Initial thresholds should be configurable because production calibration will vary by task family and provider. These defaults are conservative enough for staged deployment.

| signal | watch | caution | intervention | block |
| --- | ---: | ---: | ---: | ---: |
| `grounded_action_ratio` | `< 0.80` | `< 0.70` or decline `>= 0.15` | `< 0.60` plus action link weakness | `< 0.50` pre-final |
| `evidence_reuse` | `< 0.70` | `< 0.55` | `< 0.45` for decision-relevant evidence | `< 0.35` pre-final with unresolved warning |
| `evidence_action_consistency` | `< 0.85` | `< 0.75` | `< 0.65` or any direct mismatch | any severe mismatch pre-final |
| `grounding_latency_integrity` | `< 0.65` | `< 0.50` | `< 0.40` with contradiction or mismatch | late grounding plus unresolved severe warning |
| `evidence_retention` | `< 0.80` | `< 0.65` | accepted evidence drops from action plan | accepted evidence absent from final action |
| `contradiction_count` | `>= 1` low relevance | `>= 1` decision-relevant but resolved | `>= 1` unresolved and decision-relevant | unresolved pre-final |
| `unsupported_evidence_count` | `>= 1` non-critical | `>= 1` decision-relevant | `>= 2` or supports action choice | unresolved pre-final for critical action |

## Warning Classes

| warning | definition | earliest window | measured failure rate | intervention |
| --- | --- | --- | ---: | --- |
| contradictory grounding | surfaced evidence conflicts with interpretation trace | 25%-50% | 59.7% | contradiction resolution |
| grounding collapse | accepted evidence no longer linked to action | 50%-75% | 57.6% | grounding confirmation |
| unstable grounding | state switches or retention loss after partial grounding | 50%-75% | 50.7% | evidence recheck or confirmation |
| delayed grounding | recognized evidence exists but decisive grounding waits late | 25%-50% | 44.4% | evidence recheck |
| evidence-action mismatch | accepted evidence supports a different action | 50%-75% | not isolated in prior table; treated as high severity | action consistency check |
| unsupported accepted evidence | accepted evidence lacks concrete verifier | 25%-50% | verification-dependent | evidence verification |

## Trigger Rules

| rank | trigger | exact initial rule | selected intervention |
| ---: | --- | --- | --- |
| 1 | contradiction | one unresolved decision-relevant contradiction after evidence recognition, especially in 25%-50% | contradiction resolution |
| 2 | evidence-action mismatch | any accepted evidence whose implication conflicts with planned action | action consistency check |
| 3 | grounded-action decline | decline `>= 0.15` from prior grounded step plus weak action citation/linkage | action consistency check |
| 4 | collapse | accepted evidence present but absent from action planning | grounding confirmation |
| 5 | low evidence reuse | decision-relevant evidence appears once and is not reused before action | evidence recheck |
| 6 | unsupported evidence | accepted evidence lacks source, file, test, or trace support | evidence verification |
| 7 | unresolved pre-final warning | any level 3 warning remains unresolved at 75%-100% | grounding confirmation and block if still unresolved |

## Event Schema

Minimum event fields:

| field | type | meaning |
| --- | --- | --- |
| `grounding_session_id` | string | stable id across request/workflow |
| `event_type` | string | `evidence`, `interpretation`, `verification`, `action`, `metric`, `warning`, `intervention` |
| `execution_window` | string | `0_25`, `25_50`, `50_75`, `75_100` |
| `evidence_id` | string or null | id for source/tool/file/test evidence |
| `decision_relevance` | float | relevance to selected action |
| `metric_name` | string or null | populated for metric events |
| `metric_value` | float or null | populated for metric events |
| `warning_level` | integer or null | 0-4 |
| `trigger` | string or null | trigger that fired |
| `intervention` | string or null | selected repair |
| `token_cost_estimate` | integer or null | incremental intervention tokens |
| `latency_ms_estimate` | integer or null | incremental intervention latency |
| `outcome` | string or null | `continued`, `repaired`, `blocked`, `overridden`, `failed` |

## Success Metrics For Deployment

| production metric | target after staged rollout |
| --- | --- |
| severe warning capture rate | capture at least 80% of contradiction, mismatch, and collapse events emitted by instrumentation |
| unresolved severe pre-final warnings | below 5% of grounded sessions |
| intervention success rate | at least 50% of level 3 repairs clear or downgrade warning |
| false intervention rate | below 15% after calibration |
| net failure reduction | central target 20%-28% of baseline failures after full rollout |
| latency overhead | below 5% median, below 15% p95 for normal requests |
| token overhead | below 8% average, below 20% for intervention-triggered requests |
