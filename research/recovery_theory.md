# Recovery Theory

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Falsification stance: assume recovery is just capability in disguise and contributes nothing after K, rho, and Accessibility.

## Recovery Variables

- `contradiction_detection`
- `correction_speed`
- `retry_success`
- `recovery_loops`
- `branch_repair`

## Incremental Test Over K+rho+A1-A3

| metric | value |
| --- | ---: |
| baseline holdout R2 | 0.416094 |
| recovery holdout R2 | 0.411572 |
| holdout gain | -0.004522 |
| baseline prospective R2 | 0.006192 |
| recovery prospective R2 | 0 |
| prospective gain | -0.006192 |
| prospective Brier gain | -0.009258 |

## Determination

Recovery capacity is measurable in this corpus mostly as late trajectory repair, not as an independently observed retry log. In this consolidated test it does not improve over K, rho, and Accessibility, so the theory fails strict promotion even though recovery remains a plausible measurement target.

Verdict: fails strict falsification. Current measurement is too indirect for a strong recovery-mechanism claim.
