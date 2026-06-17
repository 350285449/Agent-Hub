# Frozen Randomized Grounding Integrity Intervention Trial

Scope: cloud models only. No new theories. No new primitives. No simulation was used for outcome estimation.

## Frozen Evaluation Set

| field | value |
| --- | ---: |
| trial id | grounding-integrity-rct-2026-06-17-v1 |
| frozen date | 2026-06-17 |
| assignment seed | 20260617 |
| frozen cloud rows | 918 |
| baseline successes | 533 |
| baseline failures | 385 |
| baseline success rate | 58.1% [54.8%, 61.2%] |

Machine-readable frozen set: `research/frozen_intervention_trial_set.jsonl`.

## Arms

| arm | runs | policy |
| --- | ---: | --- |
| Control | 466 | no intervention |
| Treatment | 452 | Grounding Integrity intervention policy |

## Treatment Trigger Rule

Treatment may trigger only when one of these existing Grounding Integrity warnings is present:

| trigger | frozen rows | failed rows | failure rate |
| --- | ---: | ---: | ---: |
| contradictory_grounding | 350 | 209 | 59.7% |
| grounding_collapse | 354 | 204 | 57.6% |
| action_consistency_failure | 368 | 216 | 58.7% |
| trigger_eligible | 368 | 216 | 58.7% |

## Applied Policy

The frozen treatment policy is: grounding confirmation, evidence verification, and action consistency checks. The policy is allowed to inspect only current execution evidence, interpretation, planned action, and tool output.

## Execution Status

The evaluation set and random assignment are frozen. The historical corpus does not contain delivered treatment replays, so `intervention_delivered=false` for every randomized row. The causal verdict below is therefore based only on randomized intervention evidence actually present in the corpus, not on prior modeled recovery estimates.
