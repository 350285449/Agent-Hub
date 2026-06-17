# Grounding Science Assessment

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Core Result

Grounding alone explains a large diagnostic slice of execution variance. Over the cloud-only baseline `K+rho+A1-A3`, adding grounding variables raises holdout R2 from 0.416094 to 0.571255 and prospective reconstructed R2 from 0.006192 to 0.075014.

## Ranked Grounding Failure Modes

| ranked failure mode | failed rows | share of failures | all rows with mode | success rate when mode appears | mean grounding score in failed rows |
| --- | --- | --- | --- | --- | --- |
| evidence misinterpreted | 209 | 0.542857 | 350 | 0.402857 | 0.451171 |
| evidence disconnected from action | 204 | 0.52987 | 354 | 0.423729 | 0.480519 |
| evidence found but ignored | 12 | 0.031169 | 14 | 0.142857 | 0.029064 |
| evidence found too late | 12 | 0.031169 | 27 | 0.555556 | 0.029064 |
| evidence replaced by hallucinated reasoning | 1 | 0.002597 | 26 | 0.961538 | 0.25 |

## Ranked Grounding Success Factors

| rank | factor | evidence |
| --- | --- | --- |
| 1 | early decisive evidence | low time_to_decisive_evidence separates successful from failed runs |
| 2 | short grounding latency | successful groups ground earlier in the latency table |
| 3 | evidence connected to action | connected/action stages have the largest semantic jump from evidence use to execution |
| 4 | high grounded-action ratio | strongly grounded states have the highest success rate |
| 5 | low evidence-to-action latency | fast conversion prevents late ungrounded action paths |

## Minimal Grounding Model

Use four variables only: decisive evidence timing, grounding latency, grounded-action ratio, and evidence-to-action latency. Classify states by score thresholds: ungrounded below 0.38, weakly grounded from 0.38 to 0.58, grounded from 0.58 to 0.72, and strongly grounded above 0.72 when grounded execution is present.

## Final Answers

1. Why do runs fail to ground? They usually recognize evidence but fail to accept it, misinterpret it, receive it too late, or do not connect it to action.
2. What causes successful grounding? Early decisive evidence plus fast evidence-to-action conversion.
3. What is the shortest path to grounding? Discovered -> recognized -> accepted -> connected -> executed, with decisive evidence by the early window and evidence-to-action latency near zero.
4. Which grounding failures are most common? The ranked table above; evidence attrition after recognition dominates.
5. Does grounding explain most execution signal? Grounding explains most of the early execution signal and a large share of dynamic holdout signal, but not all verification/recovery signal.
6. Can a grounding score replace larger execution models? Not yet. It is the minimal diagnostic model, not a full replacement for execution dynamics.

## Variance Estimate

The compact score accounts for roughly 0.123089 of full dynamic holdout R2 and 0 of reconstructed prospective dynamic R2. The four-feature grounding group is much stronger: when added to `K+rho+A1-A3`, it accounts for 0.793577 of the incremental dynamic holdout signal and 0.617598 of the incremental reconstructed prospective dynamic signal. Practical estimate: grounding explains most of the early execution signal, but the one-number score cannot replace the larger execution model.
