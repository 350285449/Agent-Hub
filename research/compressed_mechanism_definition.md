# Compressed Mechanism Definition

Scope: cloud models only. This definition compresses the surviving Agent-Hub research families without adding new theories, primitive searches, or theory tournaments.

## Mechanism

The compressed mechanism is:

`Evidence -> Grounding -> Branch Commitment -> Outcome`

A run succeeds when available task-relevant evidence is recognized, interpreted, converted into grounded action, and then committed into the correct execution branch before the run becomes hard to redirect. A run fails when evidence is missing, misunderstood, disconnected from action, or followed by an early/false/irreversible commitment.

This is not a clean pre-run law. It is a runtime execution mechanism. Capability, task difficulty, and retrieval conditions set priors, but the observed outcome is mostly determined by whether the run crosses the evidence-to-grounded-action threshold before commitment.

## Variables

| variable | operational definition | role in mechanism |
| --- | --- | --- |
| evidence availability | whether relevant evidence exists in the accessible context or can be retrieved by the run | upstream boundary condition |
| evidence recognition | whether available evidence is retrieved, surfaced, or marked as relevant (`A2_retrieved`, `A3_surfaced`) | evidence entry into the run |
| evidence interpretation | whether recognized evidence is understood well enough to constrain action (`A4_understood`, interpretation accuracy) | conversion gate from evidence to grounding |
| grounded-action ratio | share/strength of actions linked to the recognized evidence | central grounding variable and strongest minimal signal |
| branch commitment timing | execution prefix where uncertainty falls and the trajectory becomes materially predictive | commitment timing gate, currently near 50% aggregate |
| branch commitment quality | whether commitment lands on a grounded/converging branch or a stuck/wrong branch | final execution bottleneck |
| outcome | task success/failure | terminal result |

## State Sequence

1. Evidence unavailable or not recognized: the run remains prior-driven and weakly controllable.
2. Evidence recognized but misinterpreted: the run sees relevant material but does not transform it into correct constraints.
3. Evidence interpreted but disconnected from action: the run accepts evidence while choosing actions that do not preserve the evidence link.
4. Grounded action achieved: outcome probability rises sharply.
5. Branch commitment occurs: the run converges, collapses, or locks into a branch.
6. Outcome follows from the committed branch unless a late recovery changes the path.

## Empirical Anchors

- Cloud-only aligned rows: 918.
- Reconstructed prior prospective cloud rows: 67.
- Grounding event success rate: 0.817460 with grounding versus 0.062500 without grounding in the execution trajectory panel.
- Success after grounding: 0.887550 versus 0.466368 without grounding in the execution science assessment.
- Material prefix predictability appears at 50% execution: holdout R2 0.632214 and prospective R2 0.109202.
- Aggregate commitment point: 0.499469 with standard deviation 0.041656.
- The strongest single grounding integrity metric is grounded-action ratio.

## Boundary

The mechanism is sufficient only if it explains most surviving signal after `K+rho+A1-A3`, Grounding Integrity, Branch Commitment, and full trajectory controls are compared. It does not claim that all failures are recoverable, that intervention causality is proven, or that branch commitment is universal across every task family.
