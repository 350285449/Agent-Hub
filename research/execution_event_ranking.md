# Execution Event Ranking

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Baseline for incremental contribution: `K+rho+A1-A3`. Contribution is a blended score from holdout R2 gain, prospective R2 gain, and prospective Brier-gain delta. No local, Codex, Ollama, self-hosted, or edge rows are admitted.

## Ranked Events

| rank | event | triggered rows | success if present | success if absent | probability jump | holdout R2 gain | prospective R2 gain | Brier gain delta | contribution |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | first grounding event | 556 | 0.67446 | 0.436464 | 0.237996 | 0.196774 | 0.098626 | 0.017928 | 0.144538 |
| 2 | first decisive evidence | 918 | 0.58061 | n/a | timing-only | 0.044026 | 0.035104 | 0.006381 | 0.037139 |
| 3 | first recovery event | 13 | 1.0 | 0.574586 | 0.425414 | 0.00029 | 0.000296 | 5.3e-05 | 0.000268 |
| 4 | first successful tool call | 0 | n/a | 0.58061 | n/a | 0.0 | 0.0 | 0.0 | 0.0 |
| 5 | first verification attempt | 0 | n/a | 0.58061 | n/a | 0.0 | 0.0 | 0.0 | 0.0 |
| 6 | first verification success | 0 | n/a | 0.58061 | n/a | 0.0 | 0.0 | 0.0 | 0.0 |
| 7 | first retrieval | 513 | 0.623782 | 0.525926 | 0.097856 | -0.001354 | 0.001313 | 0.000238 | -0.000261 |
| 8 | first branch collapse | 83 | 0.891566 | 0.549701 | 0.341866 | -0.001769 | -0.005883 | -0.00107 | -0.003139 |

## Definitions

| event | operational definition |
| --- | --- |
| first grounding event | Decisive evidence is converted into a grounded action context. |
| first decisive evidence | Evidence is strong enough to identify the likely solution path. |
| first recovery event | The run detects a bad path and repairs it. |
| first successful tool call | A nontrivial edit/test tool path becomes available in the trace. |
| first verification attempt | The run attempts a verifier/test/equivalent check. |
| first verification success | The verifier/test signal is strong enough to count as successful verification in this corpus. |
| first retrieval | A2/retrieval signal first becomes nonzero; the run has touched task evidence. |
| first branch collapse | The trajectory collapses from exploration into one actionable solution branch. |

## First Predictive Event

The first execution event that increases predictive power under the robustness rule is `first decisive evidence`. In this corpus decisive evidence is present in every accepted run by the sampled windows, so its signal comes from timing/latency rather than a present-versus-absent split. It is not necessarily the strongest event; it is the earliest event in execution order with positive holdout gain and nonnegative future-oriented signal.
