# Grounding Integrity Causal Verdict

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. Grounding Integrity is assumed real; this verdict concerns intervention causality.

## Answers

1. Do interventions improve outcomes?

Yes, under the current cloud-only counterfactual intervention model. Baseline success is 533 of 918 runs, or 58.1%. The central staged intervention estimate is 639.6 successes of 918, or 69.7%. That is a +11.6 percentage point success increase and a 27.7% recovery rate over baseline failures.

This is causal evidence because the intervention targets the execution state that precedes the failure: contradiction, unsupported evidence, action inconsistency, or broken evidence-interpretation-action linkage. It is not merely correlation. However, it is not yet final causal proof because the frozen randomized live intervention trial has not been completed.

2. Which intervention is strongest?

The strongest single intervention is grounding confirmation, with an estimated 106.6 recovered failures and a central success rate of 69.7%.

The strongest production policy is the staged combined policy because it has the same central recovery target while adding robustness across contradiction, evidence support, action linkage, and final chain integrity. Its weakness is cost.

3. What is the true recovery ceiling?

The practical central recovery ceiling is 106.6 of 385 failures, or 27.7%.

The optimistic practical ceiling is 193.6 of 385 failures, or 50.3%.

The hard warning ceiling is 226 of 385 failures, or 58.7%. This is not a production promise because it assumes every warning-bearing failure is detected and repaired without regression.

4. What is the cost of intervention?

For the staged combined policy, the central cost estimate is 575 extra tokens per run, 575 ms average latency per run, and 65% intervention frequency. That implies about 116.1 failures prevented per 1000 runs and about 4,950 extra tokens per failure prevented.

Cost-normalized ranking favors contradiction detection first, then action consistency. Grounding confirmation is worth running as a severe/pre-final gate, not as a universal every-step check.

5. Should Grounding Integrity become a production subsystem?

Not yet as a core subsystem. It should become a production warning and staged-intervention subsystem behind measurement, with randomized rollout and telemetry. The evidence is strong enough to justify production experimentation and limited targeted intervention. It is not yet strong enough to mandate full core-subsystem status before live causal validation.

## Causal Evidence Summary

| policy | recovered failures | success rate | failure rate | recovery rate over failures | cost profile |
| --- | ---: | ---: | ---: | ---: | --- |
| control | 0.0 | 58.1% | 41.9% | 0.0% | none |
| contradiction detection | 96.3 | 68.6% | 31.4% | 25.0% | low-moderate |
| grounding confirmation | 106.6 | 69.7% | 30.3% | 27.7% | high |
| action consistency | 90.5 | 67.9% | 32.1% | 23.5% | moderate |
| evidence verification | 84.7 | 67.3% | 32.7% | 22.0% | moderate-high |
| combined policy | 106.6 | 69.7% | 30.3% | 27.7% | highest unless staged |

## Production Impact

| production runs | central failures prevented | success increase | extra tokens at staged policy |
| ---: | ---: | ---: | ---: |
| 1,000 | 116.1 | +116.1 successes | 575,000 |
| 10,000 | 1,161.2 | +1,161.2 successes | 5,750,000 |
| 100,000 | 11,612.2 | +11,612.2 successes | 57,500,000 |

## Final Requirement

Selected verdict: **B. Useful warning signal.**

## Rationale

Grounding Integrity interventions are estimated to improve outcomes, and the mechanism is intervention-relevant rather than purely correlational. But the current evidence is still a counterfactual causal estimate. The frozen randomized intervention trial is designed, not completed.

Therefore the defensible production status is not diagnostic-only and not yet core production subsystem. Grounding Integrity should be treated as a useful warning signal with staged targeted interventions under randomized production validation. If live assignment confirms the modeled +11.6 percentage point success lift without unacceptable regression or cost, the verdict can be upgraded to effective intervention mechanism.
