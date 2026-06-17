# Final Agent-Hub Recommendation

Scope: final cloud-only recommendation for converting Grounding Integrity research into deployable Agent-Hub architecture.

## Recommendation

Agent-Hub should implement Grounding Integrity as a staged runtime control subsystem with four active controls:

1. contradiction detector,
2. action consistency system,
3. evidence verification system,
4. grounding confirmation system.

The subsystem should run after evidence begins to appear, not as a heavy pre-run predictor. Its primary control target is `grounded_action_ratio`; its earliest high-value trigger is decision-relevant contradictory grounding in the 25%-50% execution window; its strongest final gate is grounding confirmation before finalization when severe warnings remain.

## Expected Impact

| outcome | estimate |
| --- | ---: |
| baseline failures | 385 of 918 |
| baseline success rate | 58.1% |
| central prevented failures | 106.6 |
| central failure reduction | 27.7% of failures |
| central success-rate increase | +11.6 percentage points |
| simulated post-deployment success rate | 69.7% |
| conservative success rate | 66.3% |
| optimistic practical success rate | 79.2% |
| theoretical warning ceiling | 82.7% success rate |

## Exact Implementation Order

| order | component | expected failure reduction from component | cumulative expected reduction |
| ---: | --- | ---: | ---: |
| 1 | grounding event schema | 0%-1% | 0%-1% |
| 2 | integrity monitor metrics | +1%-3% | 2%-4% |
| 3 | warning classifier and thresholds | +2%-4% | 4%-6% |
| 4 | contradiction detector | +8%-11% | 12%-16% |
| 5 | contradiction resolution intervention | +4%-7% | 17%-21% |
| 6 | action consistency system | +5%-7% | 21%-24% |
| 7 | evidence recheck | +1%-2% | 22%-25% |
| 8 | evidence verification system | +2%-3% | 24%-26% |
| 9 | grounding confirmation gate | +2%-4% | 27%-28% |
| 10 | intervention engine escalation and blocking | +0.5%-1.5% | 27.5%-29% |
| 11 | observability dashboards and reports | measurement enabler | 27.5%-29% |
| 12 | online policy tournament and calibration | +2%-8% production upside | 30%-35% plausible target |

This is the implementation order Agent-Hub should use. The apparent lower priority of grounding confirmation is intentional: confirmation has the highest standalone effect, but it depends on event schema, metrics, warning classification, and enough chain state to avoid becoming an expensive always-on second pass.

## Required Architecture

| subsystem | deploy first? | reason |
| --- | --- | --- |
| event schema | yes | all later controls require evidence, interpretation, verification, action, and intervention events |
| integrity monitor | yes | produces the live metrics and deltas |
| contradiction detector | yes | earliest high-value warning |
| action consistency | yes | protects the strongest measured integrity metric |
| evidence verification | after action consistency | useful but higher cost and partly overlapping |
| grounding confirmation | after targeted detectors | strongest gate, highest cost |
| intervention engine | incremental | begins as simple rules, then adds escalation and blocking |
| policy tournament | last | requires production intervention logs |

## Cost Recommendation

Use staged triggering:

| control | when to run |
| --- | --- |
| monitor | always after request/session starts |
| contradiction scan | every decision-relevant evidence or interpretation update |
| evidence recheck | first low-reuse warning |
| action consistency | every material action change after evidence acceptance |
| evidence verification | accepted evidence without concrete support |
| grounding confirmation | severe warning, failed targeted repair, or pre-final unresolved warning |

Expected full-policy cost after calibration: average token overhead below 8%, average latency overhead roughly +250-900 ms, median latency overhead below 5%, and p95 below 15% for normal cloud requests.

## Deployment Verdict

Proceed. The program has enough cloud-only evidence to justify deployment as runtime control, not enough to overclaim clean pre-run prediction. The central expected result is a 27.7% reduction in failures, equal to about 106.6 fewer failures in the measured 918-row cloud panel. The first production milestone should be passive telemetry plus contradiction detection; the first broad reliability milestone should be staged control with action consistency and pre-final grounding confirmation.
