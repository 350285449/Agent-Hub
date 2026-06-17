# Grounding Integrity Implementation Roadmap

Scope: exact implementation order for Agent-Hub, prioritized by ROI and deployment dependency.

## ROI Ranking

| ROI rank | component | reason | expected failure reduction if deployed alone |
| ---: | --- | --- | ---: |
| 1 | contradiction detector and resolution | earliest high-coverage trigger, moderate cost | 23%-27% |
| 2 | action consistency system | directly protects strongest metric, moderate cost | 22%-25% |
| 3 | grounding confirmation gate | largest single effect, but highest cost | 25%-28% |
| 4 | evidence verification system | prevents unsupported acceptance, moderate-high cost | 20%-24% |
| 5 | evidence recheck | cheapest repair, weaker standalone effect | 18%-22% |
| 6 | metric monitor and event schema | required dependency; low direct repair effect | 2%-4% from visibility and final warning surfacing |

Implementation order differs from pure ROI because event schema and metric monitor are prerequisites.

## Exact Implementation Order

| order | component | build scope | incremental expected failure reduction | cumulative central reduction |
| ---: | --- | --- | ---: | ---: |
| 1 | grounding event schema | typed events for evidence, interpretation, verification, action, warning, intervention | 0%-1% | 0%-1% |
| 2 | integrity monitor metrics | live `grounded_action_ratio`, `evidence_reuse`, `evidence_action_consistency`, `evidence_retention`, latency integrity | 1%-3% | 2%-4% |
| 3 | warning classifier and thresholds | warning levels 0-4, execution windows, trigger rules | 2%-4% | 4%-6% |
| 4 | contradiction detector | detect decision-relevant evidence vs interpretation conflicts | 8%-11% | 12%-16% |
| 5 | contradiction resolution intervention | targeted repair prompt/control action and outcome logging | 4%-7% | 17%-21% |
| 6 | action consistency system | action-evidence implication, citation/linkage, drift, finalization checks | 5%-7% | 21%-24% |
| 7 | evidence recheck | low-cost repair for low reuse or weak interpretation | 1%-2% | 22%-25% |
| 8 | evidence verification system | source/file/test/tool/trace verifier checks | 2%-3% | 24%-26% |
| 9 | grounding confirmation gate | full evidence -> interpretation -> action confirmation before finalization or after severe warning | 2%-4% | 27%-28% |
| 10 | intervention engine escalation | cheapest sufficient repair, escalation ladder, block decisions | 0.5%-1.5% | 27.5%-29% |
| 11 | observability dashboards and reports | warning rates, repair outcomes, latency/tokens, false interventions | measurement enabler | 27.5%-29% |
| 12 | online policy tournament | shadow policy, threshold calibration, provider/task-family tuning | 2%-8% upside | 30%-35% plausible production target |

The cumulative central target should be treated as approximately 27.7%, not the sum of single-policy reductions. Later increments shrink because components repair overlapping failure pathways.

## Phase Plan

| phase | orders | deployable outcome | exit criteria |
| ---: | --- | --- | --- |
| 1 | 1-3 | passive integrity telemetry | 95% of cloud requests with grounding events and metric vectors |
| 2 | 4-5 | earliest active repair | contradiction warnings produce repair decisions and outcome logs |
| 3 | 6-7 | action preservation loop | material action changes are checked against accepted evidence |
| 4 | 8-9 | verified pre-final gate | unresolved severe warnings block finalization or run confirmation |
| 5 | 10-12 | production optimization | calibrated thresholds, cost reporting, policy comparison |

## Engineering Tasks

| task | files/modules |
| --- | --- |
| define event dataclasses | `agent_hub/grounding/events.py` |
| write monitor | `agent_hub/grounding/monitor.py` |
| add observability stream | `agent_hub/observability.py` stream map: `grounding_integrity` |
| integrate request session ids | provider attempt executor, workflow engine, tool loop |
| implement warning classifier | `agent_hub/grounding/interventions.py` |
| implement contradiction detector | `agent_hub/grounding/contradiction.py` |
| implement action checks | `agent_hub/grounding/action_consistency.py` |
| implement verification checks | `agent_hub/grounding/verification.py` |
| implement confirmation gate | `agent_hub/grounding/confirmation.py` |
| expose metrics | metrics snapshot and dashboard/report route |
| add tests | unit tests for thresholds, detectors, escalation, and pre-final block behavior |

## Test Plan

| test class | required coverage |
| --- | --- |
| metric calculation | ratios update correctly from event sequences |
| warning thresholds | each warning level fires at intended boundary |
| contradiction detection | direct negation, incompatible value, unsupported inference, stale assumption |
| action consistency | accepted evidence mismatch, action drift, final claim overreach |
| verification | source/file/test/tool/trace support pass/fail |
| intervention policy | cheapest sufficient repair, escalation, pre-final blocking |
| observability | grounding events are compacted and persisted safely |
| integration | provider attempt and workflow sessions emit grounding data |

## Rollout Strategy

| rollout | mode | purpose |
| --- | --- | --- |
| alpha | shadow telemetry only | calibrate metrics without changing behavior |
| beta | warn and repair contradictions only | validate earliest intervention |
| controlled | action consistency and verification enabled for high-risk tasks | measure cost and false interventions |
| general | staged policy with pre-final confirmation | central failure-reduction target |
| optimized | policy tournament and task-family calibration | production upside |

## Final Requirement: Exact Build Order And Expected Reduction

1. Grounding event schema: 0%-1%.
2. Integrity monitor metrics: +1%-3%, cumulative 2%-4%.
3. Warning classifier and thresholds: +2%-4%, cumulative 4%-6%.
4. Contradiction detector: +8%-11%, cumulative 12%-16%.
5. Contradiction resolution intervention: +4%-7%, cumulative 17%-21%.
6. Action consistency system: +5%-7%, cumulative 21%-24%.
7. Evidence recheck: +1%-2%, cumulative 22%-25%.
8. Evidence verification system: +2%-3%, cumulative 24%-26%.
9. Grounding confirmation gate: +2%-4%, cumulative 27%-28%.
10. Intervention engine escalation and blocking: +0.5%-1.5%, cumulative 27.5%-29%.
11. Observability dashboards and reports: measurement enabler, no independent reduction assigned.
12. Online policy tournament and calibration: +2%-8% additional production upside, plausible target 30%-35%.

Central expected failure reduction after orders 1-10: 27.7% of baseline failures, about 106.6 fewer failures in the 918-row cloud panel.
