# Breakthrough Measurement Assessment

Date: 2026-06-19

## 1. What Does Agent Research Systematically Fail To Measure?

It fails to measure the local effect of each transition on the remaining reachable success space.

Modern agent work is rich in:

- terminal success rates;
- pass@1 / resolved rates;
- benchmark scores;
- step counts, rounds, tokens, cost, tool calls;
- action traces;
- final functional correctness;
- human intervention and autonomy proxies.

It is poor at measuring:

- whether a transition increased or decreased viable futures;
- whether mistakes were reversible;
- whether feedback was assimilated into future action;
- where the trajectory first entered a dead end;
- whether search breadth produced viable alternatives or decorative alternatives;
- whether resource use bought progress or merely burned budget.

## 2. Which Missing Observable Has The Highest Scientific Upside?

**Viable Reachability Delta (VRD).**

Definition:

```text
Per-transition change in the number, probability mass, or cost of task-completing futures reachable under remaining resources.
```

This is the highest-upside observable because it sits below success, uncertainty, grounding, commitment, repair, and regimes.

## 3. Could This Observable Generate Current Theories?

Yes.

VRD can generate:

- uncertainty as dispersion over reachable futures;
- commitment as valid or invalid compression of reachable futures plus rising reversal cost;
- grounding as evidence-constrained action that preserves or increases viability;
- regimes as recurring VRD curve types;
- success as reaching a viable terminal state before reachability collapses or resources exhaust.

## 4. Could This Observable Kill CSSD?

Yes, in the useful scientific sense.

CSSD is vulnerable if VRD is:

- unmeasurable;
- nonvarying;
- unrelated to success or repair;
- fully reducible to trivial controls like step count/task family;
- not determined by CSSD primitives such as transition, coupling, resource pressure, and branch/reversal structure.

CSSD is strengthened, not killed, if VRD works. But the measurement is capable of killing CSSD because it attacks the framework's core claim: that execution outcome is governed by constrained movement through state-space.

## 5. Is This A Plausible Path To A Major Discovery?

Yes, but only if measured ruthlessly.

A weak version becomes another subjective trace score. A strong version would be a real measurement breakthrough:

```text
not "did the agent succeed?"
but "when did success become reachable, expensive, fragile, impossible, or locked in?"
```

If VRD can be measured prospectively and predicts success/repair/commitment before outcome scoring, it could reorganize agent evaluation around transition science rather than leaderboard endpoints.

## Final Verdict

**D. Candidate breakthrough measurement discovered.**

Ruthless caveat: this is not yet a discovery result. It is a discovery target. The first 20-50 row experiment must prove that VRD is measurable, nontrivial, and predictive without outcome leakage.

## Generated Files

- `research/agent_measurement_blindspots.md`
- `research/missing_observables.md`
- `research/observable_breakthrough_scores.md`
- `research/observable_generative_power.md`
- `research/top10_missing_observables.md`
- `research/highest_upside_observable.md`
- `research/highest_upside_observable_experiment.md`
- `research/breakthrough_measurement_assessment.md`
