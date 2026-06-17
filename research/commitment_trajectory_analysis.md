# Commitment Trajectory Analysis

Scope: cloud models only. This file builds commitment trajectories from existing prefix, state-transition, and success/failure trajectory analyses.

## Measurement Anchors

| measure | observed anchor |
| --- | --- |
| commitment onset | near 50% execution prefix in aggregate |
| aggregate commitment point | 0.499469 |
| commitment point standard deviation | 0.041656 |
| first material holdout R2 jump | 25% to 50%, from 0.423852 to 0.632214 |
| first material prospective R2 signal | 50%, prospective R2 0.109202 |
| uncertainty collapse | 0.400294 collapse at 50% prefix |

## Trajectory Types

| trajectory | component sequence | commitment reading |
| --- | --- | --- |
| successful standard | evidence accumulates -> grounding -> option elimination -> action lock-in -> convergence | correct commitment |
| successful recovery | stuck/exploring -> evidence-action repair -> late option elimination -> action lock-in | delayed but corrected commitment |
| failed stuck | weak or disconnected evidence -> stuck state persists -> action lock-in | false commitment |
| failed exploratory | evidence remains unresolved -> options do not collapse -> final action selected weakly | delayed or absent commitment |
| premature | early option elimination -> early action lock-in -> later evidence cannot redirect | premature commitment |
| delayed | evidence and grounding appear, but branch switching remains high until late | late commitment |

## Prefix Trajectory

| prefix | trajectory interpretation |
| --- | --- |
| 0% | prior and task features set starting conditions; no branch commitment yet |
| 10% | exploration begins; uncertainty can increase because options are still open |
| 25% | evidence and grounding signals are visible but not yet consistently decisive |
| 50% | branch dominance and action lock-in become visible; outcome predictability rises |
| 75% | successful runs maintain convergence; failed runs often remain stuck or falsely locked |
| 90% | terminalization; residual recovery is possible but less common |

## Commitment Onset

Commitment onset is the first point where branch dominance becomes action-dominant. The best measured aggregate onset remains the 50% prefix. Earlier signals exist, but the prior analyses show that the 10% and 25% prefixes do not produce stable prospective predictability.

Operational onset rule:

`onset = first prefix where a selected branch is grounded/converging or locked while reversibility begins to fall`

## Commitment Acceleration

Commitment acceleration is the rate at which a run moves from open exploration to low-reversibility branch dominance.

The strongest observed acceleration window is 25% to 50%:

- Holdout R2 rises from 0.423852 to 0.632214.
- Uncertainty p(1-p) falls from 0.154735 to 0.088636.
- Uncertainty collapse moves from -0.046928 to 0.400294.

Interpretation: commitment accelerates when evidence-action conversion begins eliminating alternatives and pushing the run into a grounded/converging or stuck/locked path.

## Commitment Lock-In

Lock-in is the point where branch switching or recovery becomes unlikely. In V2 measurement, branch lock-in is high for both successes and failures:

| outcome | branch lock-in | branch reversibility |
| --- | ---: | ---: |
| success | 0.842402 | 0.358349 |
| failure | 0.981818 | 0.545455 |

Failures have higher measured lock-in because stuck trajectories can be extremely stable. This means lock-in is not inherently good. Lock-in quality depends on whether the locked path is grounded.

## Commitment Irreversibility

Irreversibility is not simply low reversibility. A run can be reversible because it is still searching, or because it is repeatedly failing to stabilize. The useful irreversibility signal is:

`low reversal after grounding + convergence`

The damaging irreversibility signal is:

`low or ineffective reversal while stuck / misgrounded`

## Determination

The dominant commitment trajectory is not a single event at exactly 50%. It is an acceleration window centered on mid-execution. The 50% point is where the composite becomes measurable: evidence-action conversion has either produced a grounded branch or failed to prevent stuck/wrong lock-in.

