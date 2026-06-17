# Commitment Lock-In Analysis

Scope: cloud models only. This file isolates action lock-in, onset, acceleration, lock-in, and irreversibility within Branch Commitment.

## Definitions

| measure | definition |
| --- | --- |
| commitment onset | first branch-dominant action state |
| commitment acceleration | speed of movement from open alternatives to branch dominance |
| commitment lock-in | selected branch persists and controls action |
| commitment irreversibility | branch cannot be meaningfully redirected before terminal outcome |

## Onset

Measured onset is anchored at the 50% execution prefix:

- Aggregate commitment point: 0.499469.
- Standard deviation: 0.041656.
- First robust uncertainty collapse appears at 50%.
- First prospective predictability signal appears at 50%.

Onset should therefore be treated as a mid-execution window, not a universal timestamp.

## Acceleration

The acceleration window is 25% to 50%.

| prefix movement | holdout R2 delta | uncertainty movement | reading |
| --- | ---: | --- | --- |
| 10% -> 25% | +0.081447 | uncertainty remains high | evidence enters but does not yet commit |
| 25% -> 50% | +0.208362 | uncertainty sharply falls | commitment acceleration |
| 50% -> 75% | -0.019172 | uncertainty remains lower | post-commitment stabilization |
| 75% -> 90% | +0.011753 | little change | terminalization |

## Lock-In Quality

Lock-in quality is the key distinction.

| lock-in type | precondition | effect |
| --- | --- | --- |
| grounded lock-in | evidence is connected to action | success probability rises |
| stuck lock-in | run is stable but ungrounded/misgrounded | failure probability rises |
| premature lock-in | branch is selected before adequate evidence-action conversion | later correction becomes costly |
| delayed lock-in | evidence exists but branch does not stabilize | final action may be weak or late |

## Irreversibility

Irreversibility has two forms:

| form | description | outcome tendency |
| --- | --- | --- |
| productive irreversibility | correct branch becomes hard to redirect after grounding | successful commitment |
| destructive irreversibility | wrong branch becomes hard to redirect before or despite grounding | failed commitment |

The V2 metrics show why irreversibility alone is not a success mechanism:

- Branch lock-in is high for successes: 0.842402.
- Branch lock-in is even higher for failures: 0.981818.
- False commitment is much higher in failures: 0.348052 versus 0.093809.
- Premature commitment is higher in failures: 0.353247 versus 0.243902.

## Trigger Analysis

The trigger is not evidence accumulation by itself. It is not uncertainty collapse by itself. It is not verification completion by itself.

The immediate trigger is:

`action lock-in after option elimination`

The correctness gate is:

`whether the locked action remains connected to grounded evidence`

## Comparison

| class | onset | acceleration | lock-in | irreversibility |
| --- | --- | --- | --- | --- |
| successful commitment | mid-execution after grounding | strong 25%-50% conversion | high but grounded | productive |
| failed commitment | can be mid or early | may accelerate into stuckness | very high | destructive |
| premature commitment | early relative to evidence-action conversion | too steep | high | blocks correction |
| delayed commitment | late after evidence appears | too shallow | low until terminal stage | may miss execution window |

## Determination

Branch Commitment is best measured as the crossing of two curves:

1. Branch dominance rises through evidence, confidence, and option elimination.
2. Branch reversibility falls through action lock-in and terminalization.

Commitment begins when dominance rises. It becomes decisive when reversibility falls. It becomes successful only when the dominant branch is grounded.

