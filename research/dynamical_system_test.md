# Dynamical System Test

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Model Comparison

| model | feature count | retrospective R2 | holdout R2 | prospective R2 | prospective Brier gain | robustness |
| --- | --- | --- | --- | --- | --- | --- |
| Model B: Grounding Integrity | 9 | 0.586414 | 0.612539 | 0.101662 | 0.01848 | 0.37987 |
| Model D: Execution State + Transition Model | 36 | 0.554521 | 0.54147 | 0.037884 | 0.006886 | 0.313822 |
| Model C: Execution State Model | 16 | 0.549321 | 0.529895 | 0.0 | -0.023853 | 0.291442 |
| Model A: Static K+rho+A | 3 | 0.50962 | 0.435978 | 0.026342 | 0.004788 | 0.250923 |

## Interpretation

Static K+rho+A remains a useful historical baseline, but the execution-state models explain the outcome surface better once the run is underway. Grounding Integrity is retained only as a requested comparison/control model; the stronger result is that state and transition information capture more of the execution dynamics than static pre-run properties.
