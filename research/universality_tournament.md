# Universality Tournament

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Candidates are ranked by stability, transferability, predictive value, and robustness. The ranking score is used only for the tournament requested here; it is not promoted as a new execution invariant.

## Rankings

| rank | candidate | stability | transferability | predictive value | robustness | status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | grounded-action ratio | 0.528814 | 0.661377 | 0.296901 | 0.733498 | survives as weak candidate |
| 2 | state-transition count | 0.898626 | 0.819013 | 0.032176 | 0.592399 | diagnostic only |
| 3 | grounding latency | 0.562157 | 0.352192 | 0.092177 | 0.494589 | diagnostic only |
| 4 | recovery event | 0.0 | 0.934857 | 0.008551 | 0.389008 | diagnostic only |
| 5 | branch collapse | 0.0 | 0.862579 | 0.028865 | 0.287639 | diagnostic only |
| 6 | evidence-to-action latency | 0.186773 | 0.486419 | 0.024073 | 0.235369 | diagnostic only |
| 7 | verification success | 1.0 | 1.0 | 0.0 | 0.0 | diagnostic only |

## Determination

`grounded-action ratio` wins the tournament, with grounding latency and evidence-to-action latency as supporting quantities. The result is weaker than an execution law because cross-family validation is incomplete, prospective rows are reconstructed, and benchmark dependence remains visible.
