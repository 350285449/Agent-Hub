# Highest-Upside Observable

Date: 2026-06-19

## Chosen Observable

```text
Viable Reachability Delta (VRD)
```

## Definition

VRD is the per-transition change in the set, probability mass, or minimum cost of task-satisfying futures still reachable under remaining resources.

Operationally:

```text
VRD_t = ReachableViableFutureScore(S_{t+1}, R_{t+1})
        - ReachableViableFutureScore(S_t, R_t)
```

Where:

- `S_t` is the observable execution state before transition `t`;
- `R_t` is remaining resource budget;
- `ReachableViableFutureScore` is a pre-outcome score of whether completion remains reachable, how many routes remain, and how expensive the cheapest route is.

## Why This Is The One

VRD is not widely measured. Current benchmarks measure whether the agent eventually succeeds, how many actions it used, and sometimes whether individual actions match a reference. They rarely measure whether each transition increases or decreases the agent's reachable future success set.

VRD is measurable in principle. A small experiment can score each step using:

- state snapshots;
- task constraints;
- remaining resource budget;
- verifier judgment of whether success remains reachable;
- estimated minimum repair/completion cost.

VRD can generate existing theories:

| Existing construct | VRD derivation |
| --- | --- |
| Uncertainty | dispersion over reachable viable futures and uncertainty about which future remains open |
| Commitment | collapse to one/few viable futures plus increased reversal cost |
| Grounding | actions that preserve/increase viability because they are constrained by valid observations |
| Regimes | recurring VRD curves: early expansion, valid compression, premature collapse, repair rebound, terminal drift |
| Success | cumulative trajectory reaches a satisfying terminal state before viability reaches zero or resources exhaust |

## Can It Falsify CSSD?

Yes.

CSSD claims agent execution is constrained state-space dynamics. VRD is the cleanest observable of whether those dynamics matter. CSSD is damaged if:

1. VRD cannot be measured with acceptable inter-rater or verifier agreement.
2. VRD has no nontrivial variance across rows.
3. VRD does not predict success, repair, grounding, or commitment better than task family, model family, step count, and raw feedback presence.
4. CSSD primitives such as transitions, coupling, and resources do not determine VRD.
5. High positive VRD trajectories fail at the same rate as low/negative VRD trajectories under matched task/model conditions.

CSSD is strengthened if VRD predicts outcome and derives commitment/grounding without using those labels.

## Expected Signature

Success:

```text
early neutral/positive VRD -> evidence-supported compression -> low reversal need -> terminal success
```

Failure:

```text
negative VRD or premature compression -> rising repair cost -> dead-end entry -> terminal failure
```

Recovery:

```text
negative VRD -> feedback assimilation -> positive VRD rebound -> repaired trajectory
```

## Final Assessment

VRD is the highest-upside observable because it measures the thing most benchmarks only infer after the fact: whether the agent's next step made success more or less reachable.
