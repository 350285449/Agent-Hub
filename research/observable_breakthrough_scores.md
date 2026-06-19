# Observable Breakthrough Scores

Date: 2026-06-19

Scale: 1 low, 5 high.

| Observable | Novelty | Measurability | Scientific value | Explanatory scope | Likely ignored | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Viable Reachability Delta | 5 | 3 | 5 | 5 | 5 | 23 |
| Transition Reversibility | 4 | 4 | 5 | 5 | 4 | 22 |
| Repair Efficiency | 4 | 5 | 5 | 4 | 4 | 22 |
| Feedback Assimilation Rate | 4 | 4 | 5 | 4 | 4 | 21 |
| State-Space Compression | 5 | 3 | 5 | 5 | 3 | 21 |
| Dead-End Entry Rate | 4 | 4 | 5 | 4 | 4 | 21 |
| Branch Topology | 3 | 4 | 4 | 4 | 3 | 18 |
| Resource Burn Rate | 3 | 5 | 4 | 4 | 2 | 18 |
| Exploration Yield | 4 | 3 | 4 | 4 | 3 | 18 |
| Trajectory Curvature | 4 | 3 | 4 | 4 | 3 | 18 |
| Coupling Validity | 3 | 4 | 4 | 4 | 2 | 17 |
| Irreversible Commitment Point | 3 | 3 | 4 | 4 | 3 | 17 |
| Transition Velocity | 3 | 3 | 4 | 4 | 3 | 17 |
| State-Transition Graph Structure | 3 | 3 | 4 | 4 | 2 | 16 |
| Recovery Horizon | 3 | 4 | 4 | 3 | 2 | 16 |

## Interpretation

The highest scoring candidate is **Viable Reachability Delta**.

Reason: it is not just another trace feature. It measures whether the agent's current transition changes the existence, cost, and density of still-possible successful futures. This could generate several familiar measurements instead of sitting beside them:

- success: viable reachability eventually reaches a terminal satisfying state;
- failure: viable reachability collapses to zero or becomes too expensive;
- uncertainty: dispersion over reachable futures;
- commitment: low branch entropy plus high reversal cost;
- grounding: action constrained by a valid transition toward viable reachability;
- regimes: recurring patterns of reachability change.

## Ruthless Filter

The lower-ranked observables are still useful, but most are subcomponents or symptoms. If only one new measurement can be collected, collect VRD first and derive the others where possible.
