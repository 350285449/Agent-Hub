# Grounding Integrity Intervention Trial Design

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. Grounding Integrity is assumed real; this protocol tests whether interventions cause outcome improvement.

## Objective

Determine whether Grounding Integrity interventions change final task outcomes relative to normal execution.

The estimand is the causal effect of assigned intervention policy on task success:

`E[outcome | assigned intervention] - E[outcome | assigned control]`

The trial does not test whether Grounding Integrity exists. It tests whether acting on it improves outcomes.

## Frozen Groups

| group | policy | intervention rule | allowed action |
| --- | --- | --- | --- |
| Control | normal execution | no Grounding Integrity repair policy is injected | execute normally |
| Treatment A | contradiction detection | check whether accepted evidence, interpretation, and planned action conflict | pause, resolve contradiction, continue |
| Treatment B | grounding confirmation | confirm the evidence-interpretation-action chain before finalization or severe warning | revise unsupported interpretation or action |
| Treatment C | action consistency checks | verify that each material action preserves accepted evidence | revise action when it breaks grounding |
| Treatment D | evidence verification | verify accepted evidence against concrete source, file, test, or tool output | discard or replace unsupported evidence |
| Treatment E | combined policy | staged A, D, C, then B at severe/pre-final gate | use cheapest applicable repair first |

## Assignment

Randomize cloud-model runs at the run level after task selection and before execution. Stratify by model family, benchmark, task family, and baseline difficulty controls already used in the research program.

Each task receives exactly one assigned policy. No crossover is allowed within the same run. Replays of the same task must preserve seed, model, prompt, tool budget, and evaluation rubric except for the assigned intervention policy.

## Execution Constraints

| constraint | frozen rule |
| --- | --- |
| model scope | cloud models only |
| search scope | no primitive searches, no interaction searches |
| theory scope | no new theory construction during the trial |
| metric scope | use existing success, failure, recovery, token, latency, and intervention-frequency measurements |
| intervention scope | interventions may inspect current execution evidence, interpretation, planned action, and tool output only |
| evaluator scope | outcome evaluator must be blind to treatment assignment where possible |

## Trigger Rules

| intervention | trigger | repair completion criterion |
| --- | --- | --- |
| contradiction detection | accepted evidence conflicts with interpretation or planned action | contradiction is either resolved or explicitly marked non-decision-relevant |
| grounding confirmation | final answer/action is imminent, or Grounding Integrity is fragile/collapsed | evidence, interpretation, and action are mutually consistent |
| action consistency | a material action is proposed after evidence acceptance | action preserves the accepted evidence and stated task objective |
| evidence verification | evidence is accepted without concrete support | evidence is verified or removed from the reasoning chain |
| combined policy | any above trigger | staged repair completes without invoking higher-cost checks unless needed |

## Outcomes

Primary outcome: final task success.

Secondary outcomes:

| measure | definition |
| --- | --- |
| failure rate | failed runs divided by assigned runs |
| recovery rate | failures in matched no-intervention counterfactual that become successes under intervention |
| intervention frequency | intervention triggers divided by assigned runs |
| token cost | treatment token delta relative to matched control |
| latency cost | treatment latency delta relative to matched control |
| regression rate | control-success counterfactuals that fail under intervention |

## Counterfactual Pairing

For every failure in the control or reconstructed no-intervention condition, estimate a paired intervention outcome using the frozen policy assigned to the matched treatment arm.

Pairing priority:

1. Same task, same model, same benchmark, same prompt, same seed.
2. Same task, same model family, same benchmark, matched difficulty controls.
3. Same failure pathway and warning state when exact replay is unavailable.

Only tier 1 and tier 2 pairs count as direct causal evidence. Tier 3 pairs are sensitivity estimates.

## Analysis Plan

| analysis | rule |
| --- | --- |
| intention-to-treat | every assigned run remains in its assigned group |
| per-protocol | secondary only; excludes protocol violations |
| effect estimate | treatment success rate minus control success rate |
| recovery estimate | treatment successes among matched control failures |
| uncertainty | binomial or bootstrap interval over randomized units |
| multiple policies | compare A-E against control and against each other |
| overlap | combined policy effects are not added linearly from single-policy effects |

## Stop Conditions

Stop the trial only for evaluator failure, protocol contamination, cloud-model outage, or budget exhaustion. Do not stop early because interim results look favorable unless a pre-registered sequential stopping rule is used.

## Causal Claim Standard

The program may claim effective intervention only if:

1. At least one treatment arm improves success rate over control.
2. The improvement survives stratified analysis by model family, benchmark, and task family.
3. Recovery is concentrated among runs with the targeted Grounding Integrity failure pathway.
4. Regression and cost do not erase the utility of the recovered successes.

Until then, intervention results remain counterfactual estimates, not proven causal recovery.
