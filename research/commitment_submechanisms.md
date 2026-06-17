# Commitment Submechanisms

Scope: cloud models only. This file searches within Branch Commitment for sub-mechanisms without introducing external theory or new primitives.

## Candidate Submechanisms

| submechanism | source components | status |
| --- | --- | --- |
| evidence-action conversion | evidence accumulation + grounding + action linkage | strongest submechanism |
| branch dominance formation | confidence accumulation + option elimination | strong inferred submechanism |
| irreversibility formation | action lock-in + low effective reversal | strong submechanism |
| false terminalization | premature lock-in + weak verification reopening | strong failure submechanism |
| recovery reopening | reversibility + late evidence-action repair | rare but important |
| search-to-selection transition | search exhaustion + option elimination | moderate submechanism |

## Evidence-Action Conversion

This is the deepest observed submechanism under useful commitment.

Prior trajectory evidence shows that successful trajectories do not merely discover or recognize evidence. They connect it to execution:

- `discovered>recognized>accepted>connected>executed` has success rate 0.885714.
- `discovered>recognized>accepted` has success rate 0.423729.
- Successful runs have much higher grounded-action ratio than failures: 0.496622 versus 0.098376.

Interpretation: the decisive precommitment work is not evidence presence. It is converting accepted evidence into action constraints.

## Branch Dominance Formation

Branch dominance forms when the run stops treating alternatives as equally live. This appears through grounded/converging state transitions and branch stability. It contains:

1. confidence accumulation,
2. option elimination,
3. search exhaustion.

This submechanism is partly inferred because direct confidence is not separately observed. The observable signature is movement out of exploring into grounded/converging or stuck/stable states.

## Irreversibility Formation

Irreversibility forms when branch dominance controls action and later evidence no longer redirects the run. It contains:

1. action lock-in,
2. reduced effective reversal,
3. terminal verification or finalization.

This submechanism explains why failed commitments can be highly stable. Stability and correctness are different. Irreversibility amplifies whichever branch has already won.

## False Terminalization

False terminalization is the failure submechanism where a wrong or weakly grounded branch passes through finalization without reopening.

Observed indicators:

- false commitment is much higher in failures than successes,
- premature commitment is higher in failures,
- stuck trajectories are stable and failure-prone,
- commitment without grounding is often just lock-in.

## Recovery Reopening

Recovery reopening is the rare case where a run reverses or repairs a bad branch before terminalization. It appears in trajectories such as:

- `stuck>stuck>recovered>recovered`, success rate 1.0 in the observed table but only 11 rows.
- `stuck -> recovered`, also rare.

Recovery does not dominate the aggregate mechanism, but it proves that commitment is not always immediately irreversible.

## Deeper Mechanism Test

Question: is there a deeper mechanism beneath Branch Commitment?

Result: yes, partially.

The deepest observed submechanism is:

`evidence-action conversion before irreversibility`

This explains why commitment can be correct, false, premature, or delayed:

- correct commitment: conversion precedes irreversibility,
- false commitment: irreversibility occurs without conversion,
- premature commitment: irreversibility occurs before conversion is mature,
- delayed commitment: conversion occurs but irreversibility arrives too late.

## Determination

Branch Commitment decomposes into submechanisms, but it does not disappear. The deeper mechanism is not a replacement primitive; it is a composite control relation:

`conversion quality x irreversibility timing`

Commitment remains the observable bottleneck because conversion only affects outcome once it is locked into an action branch.

