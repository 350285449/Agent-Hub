# Scientific Assessment v2

Scope: Cloud-only aligned rows: 918 of 1091. Aligned exclusions: 173 rows by model {'gpt-5.5': 143, 'gemma4:31b-cloud': 10, 'nemotron-3-super:cloud': 10, 'kimi-k2.6:cloud': 10} and provider {'codex-cli': 143, 'ollama-cloud': 30}. Upstream strict audit additionally reported 11280 local deterministic rows, 2 timeout-only rows, and exclusion reasons {'duplicate task/model/context tuple': 5, 'local Ollama or otherwise disallowed model': 771, 'local deterministic proof row': 11280, 'provider failure/auth/subscription': 18, 'synthetic or derived benchmark row without allowed model provenance': 1380, 'timeout-only row with no usable output': 2, 'unsuccessful execution or unusable validation result': 4}.

## Conclusion

Success condition A remains the working conclusion, but weakened: better measurement raises explanatory power only when full evidence-use diagnostics are included, and no fourth primitive survives deconfounding. Condition B is not met. Condition C is not met, but prospective cloud-only evidence applies real pressure.

## Evidence

- Cloud-only K+rho+A R2: 0.50962.
- Cloud-only K+rho+A1-A5 R2: 0.609926.
- Reliability-corrected R2: 0.815391.
- Ceiling estimate after cloud-only recomputation: 0.865391.
- Clean candidate additions after K+rho+A are near zero; only post-output traces add material residual signal.

## Counter-Evidence

- Strict pre-run accessibility A1-A3 does not improve R2 (0.506963).
- Frozen prospective cloud-only tournament has R2 0 after excluding 10 non-cloud rows.
- K and rho are still outcome-derived and may be over-crediting historical fit.

## Uncertainty

The strongest uncertainty is measurement timing. A4/A5 may be diagnostics of successful reasoning rather than causes available to a router. The second uncertainty is prospective scope: the cloud-only future set is narrow and model-imbalanced.

## Falsification Attempt

The program tried to falsify A by excluding Codex CLI rows, banning local/Ollama/self-hosted rows, testing pre-run-only A, adding candidate fourth primitives after K+rho+A, and re-reading prospective evidence cloud-only. Those tests reject any strong fourth-primitive claim and reject any claim of clean prospective validation, but they do not falsify K+rho+A as a useful measurement family.

## Updated Scientific Position

Keep K+rho+A, but rename the current achievement carefully: it is a cloud-only explanatory measurement framework with retrospective strength and prospective fragility. Next work should freeze rho-vector and A1-A3 before collection; A4/A5 should remain diagnostics until independently pre-measured.
