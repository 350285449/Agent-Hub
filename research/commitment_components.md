# Commitment Components

Scope: cloud models only. This file defines the components of Branch Commitment using only established Agent-Hub research variables and trajectory states.

## Component Catalog

| component | operational definition | measurable proxy | expected success pattern | expected failure pattern |
| --- | --- | --- | --- | --- |
| evidence accumulation | relevant task evidence enters the run | retrieval/evidence events; decisive evidence timing | earlier decisive evidence; higher grounding rate | late, absent, or unused evidence |
| confidence accumulation | the run increasingly prefers one branch | lower switch rate; stable grounded/converging state | stable branch after grounding | stable branch while stuck or wrong |
| uncertainty collapse | predicted outcome variance falls | prefix uncertainty p(1-p); R2 jump | collapse after grounded action | collapse after wrong lock-in |
| search exhaustion | exploration stops finding viable alternatives | transition out of exploring; persistent convergence | exploration yields grounded/converging path | exploration ends because the run is stuck |
| option elimination | competing branches are discarded | branch collapse; movement toward converging | wrong branches removed after evidence | alternatives removed before evidence is adequate |
| action lock-in | selected branch becomes hard to redirect | branch lock-in; low reversibility; terminal state | lock-in after evidence-action link | lock-in without evidence-action link |
| verification completion | final checks either validate or fail to reopen the branch | late confirmation, recovery, or terminalization proxy | verification preserves grounded action | verification rubber-stamps wrong branch |

## Component Ordering

The most supported ordering is:

1. Evidence accumulation.
2. Evidence interpretation and grounding.
3. Confidence accumulation.
4. Option elimination.
5. Action lock-in.
6. Uncertainty collapse becomes visible.
7. Verification completion or terminalization.

Uncertainty collapse is placed after lock-in because it is a measurement signature: the outcome becomes predictable once the branch has become hard to redirect. It can appear as a consequence of correct commitment or incorrect commitment.

## Component Strength

| component | strength as decomposition element | notes |
| --- | --- | --- |
| evidence accumulation | high | strong upstream role, but not enough without grounding |
| confidence accumulation | medium | useful, but direct confidence is not separately observed |
| uncertainty collapse | high as measurement, medium as mechanism | strongest visible onset signal |
| search exhaustion | low-medium | can describe both good convergence and bad stuckness |
| option elimination | high | close predecessor to lock-in |
| action lock-in | high | best immediate trigger component |
| verification completion | low-medium | important for terminalization, weakly measured in current corpus |

## Minimal Component Set

The smallest useful decomposition is:

`evidence-action conversion + option elimination + action lock-in`

Evidence-action conversion determines whether commitment is likely to be correct. Option elimination makes one branch dominant. Action lock-in turns dominance into commitment.

## Component Failure Modes

| failed component | visible failure |
| --- | --- |
| weak evidence accumulation | run stays prior-driven or exploratory |
| weak confidence accumulation | delayed commitment or repeated branch switching |
| early uncertainty collapse | premature false confidence |
| false search exhaustion | run stops searching while evidence remains unresolved |
| bad option elimination | correct branch discarded |
| bad action lock-in | stuck/wrong branch becomes irreversible |
| weak verification completion | final answer does not reopen an invalid branch |

## Determination

Commitment decomposes most cleanly into **selection pressure** and **irreversibility pressure**.

Selection pressure is produced by evidence accumulation, confidence accumulation, search exhaustion, and option elimination. Irreversibility pressure is produced by action lock-in and terminal verification. Branch Commitment occurs when these pressures cross: one branch becomes dominant and the run stops meaningfully revising it.

