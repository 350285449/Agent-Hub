# Signal Emergence Theory

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Falsification stance: assume signal exists before execution and dynamic windows add nothing. Each prefix is strict: a 10% model cannot see 25%, 50%, 75%, or post-run-derived fields.

## Prefix Results

| window | feature count | retrospective R2 | holdout R2 | holdout Brier gain | prospective R2 | prospective Brier gain |
| --- | --- | --- | --- | --- | --- | --- |
| pre-run | 7 | 0.507582 | 0.406068 | 0.090805 | 0.0 | -0.005365 |
| 10% execution | 8 | 0.507601 | 0.395159 | 0.088365 | 0.0 | -0.006355 |
| 25% execution | 11 | 0.517519 | 0.428657 | 0.095856 | 0.0096 | 0.001745 |
| 50% execution | 16 | 0.597636 | 0.601184 | 0.134437 | 0.07067 | 0.012846 |
| 75% execution | 25 | 0.644897 | 0.422823 | 0.094552 | 0.0 | -0.008697 |

## Determination

Predictive signal first appears before execution in holdout, but not in prospective reconstruction. Material execution signal first clears the robustness gate at `50% execution`.

Verdict: partially survives. The strong hypothesis that no signal exists before execution is falsified by holdout R2. The weaker execution-science claim survives: stable future-oriented signal becomes materially better only after execution observables are admitted.
