# Causal Validation

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. This file answers whether the interventions change outcomes, using the frozen protocol and the existing counterfactual recovery estimates.

## Causal Question

Does assignment to a Grounding Integrity intervention increase final task success relative to normal execution?

The current evidence is counterfactual, not yet a completed randomized live trial. Therefore the correct status is: causal validation is provisionally positive by modeled intervention contrast, but not yet conclusively proven by live randomized assignment.

## Outcome Contrast

Baseline:

| condition | successes | failures | success rate | failure rate |
| --- | ---: | ---: | ---: | ---: |
| control / no intervention | 533.0 | 385.0 | 58.1% | 41.9% |

Central intervention estimates:

| condition | recovered failures | successes | failures | success rate | failure rate | success lift | failure reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Treatment A: contradiction detection | 96.3 | 629.3 | 288.7 | 68.6% | 31.4% | +10.5 pp | 25.0% |
| Treatment B: grounding confirmation | 106.6 | 639.6 | 278.4 | 69.7% | 30.3% | +11.6 pp | 27.7% |
| Treatment C: action consistency checks | 90.5 | 623.5 | 294.5 | 67.9% | 32.1% | +9.9 pp | 23.5% |
| Treatment D: evidence verification | 84.7 | 617.7 | 300.3 | 67.3% | 32.7% | +9.2 pp | 22.0% |
| Treatment E: combined policy | 106.6 | 639.6 | 278.4 | 69.7% | 30.3% | +11.6 pp | 27.7% |

## Recovery Rate

| policy | recovery rate among baseline failures | interpretation |
| --- | ---: | --- |
| contradiction detection | 25.0% | strong early repair of contradiction-mediated failures |
| grounding confirmation | 27.7% | strongest single-policy modeled recovery |
| action consistency checks | 23.5% | direct repair of evidence-action disconnect |
| evidence verification | 22.0% | useful but somewhat narrower than full-chain confirmation |
| combined policy | 27.7% central | matches union estimate because single-policy effects overlap |

## Causal Identification

The evidence supports causality only to the extent that the comparison is an intervention contrast over matched failure paths. It is stronger than correlation because the modeled treatment changes the execution state that generated the failure: contradiction, unsupported evidence, or action inconsistency.

It remains weaker than a completed randomized trial because the treatment outcomes are estimated rather than observed under frozen assignment.

| requirement | status |
| --- | --- |
| Grounding Integrity signal established | satisfied by prior cloud-only validation |
| intervention target occurs before final failure | satisfied for warning-bearing failures |
| counterfactual repair path specified | satisfied by frozen treatment policies |
| randomized live assignment | not yet completed |
| blinded final outcome evaluation | required for final validation |

## Does Intervention Change Outcomes?

Yes, under the current counterfactual model. The estimated change is large enough to matter: central success rate rises from 58.1% to 69.7%, and failure rate falls from 41.9% to 30.3%.

The causal claim should be phrased carefully:

Grounding Integrity interventions are estimated to cause recovery in the subset of failures where the failure path contains an actionable contradiction, unsupported evidence claim, or evidence-action disconnect before finalization. The causal effect is not expected for failures with no usable grounding material or no timely warning.

## Determination

The current causal validation result is provisionally positive. Interventions likely change outcomes, with a central recovery rate of 27.7% of failures. The claim should remain below "core production subsystem" until a frozen randomized intervention trial observes the recovery effect directly.
