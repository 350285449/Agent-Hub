# Top 10 Deconfounding

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Deconfounding adds task family, model family, and benchmark one-hot controls after the core mechanisms. A theory fails this section when its signal vanishes or reverses after these controls.

| theory | all-core holdout gain | all-core prospective gain | all-core blended | family-control holdout gain | family-control prospective gain | family-control blended | collapse target |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Branch Collapse Theory | -0.029887 | -0.000955 | -0.016789 | -0.003151 | -0.012929 | -0.006493 | Execution Trajectories |
| Uncertainty Collapse Theory | 0 | 0 | 0 | 0 | 0 | 0 | Execution Trajectories |
| Runtime Integrity Theory | 0 | 0 | 0 | 0 | 0 | 0 | Execution Trajectories |
| State Reachability Theory | 0 | 0 | 0 | 0 | 0 | 0 | Execution Trajectories |
| Execution Lock-In Theory | -0.037976 | 0.000789 | -0.020596 | -0.010547 | -0.007489 | -0.008558 | Execution Trajectories |
| Information Flow Theory | 0 | 0 | 0 | 0 | 0 | 0 | Execution Trajectories |
| Decisive Evidence Theory | 0 | 0 | 0 | 0 | 0 | 0 | Grounding Integrity |
| Runtime Control Theory | -0.037976 | 0.000789 | -0.020596 | -0.010547 | -0.007489 | -0.008558 | Execution Trajectories |
| Decisive Information Event Theory | 0 | 0 | 0 | 0 | 0 | 0 | Execution Trajectories |
| Error Recovery Theory | -0.037976 | 0.000789 | -0.020596 | -0.010547 | -0.007489 | -0.008558 | Execution Trajectories |

## Determination

The top-10 theories mostly lose independent status once Grounding Integrity, execution trajectory, and family/benchmark controls are present. Surviving signal is weak and diagnostic-heavy rather than a clean new mechanism.
