# Residual Atlas v2

Scope: Cloud-only aligned rows: 918 of 1091. Aligned exclusions: 173 rows by model {'gpt-5.5': 143, 'gemma4:31b-cloud': 10, 'nemotron-3-super:cloud': 10, 'kimi-k2.6:cloud': 10} and provider {'codex-cli': 143, 'ollama-cloud': 30}. Upstream strict audit additionally reported 11280 local deterministic rows, 2 timeout-only rows, and exclusion reasons {'duplicate task/model/context tuple': 5, 'local Ollama or otherwise disallowed model': 771, 'local deterministic proof row': 11280, 'provider failure/auth/subscription': 18, 'synthetic or derived benchmark row without allowed model provenance': 1380, 'timeout-only row with no usable output': 2, 'unsuccessful execution or unusable validation result': 4}.

Residual = actual - K+rho+A prediction.

## False Positives

| model | repository | category | predicted | residual |
| --- | --- | --- | --- | --- |
| gemma4:31b-cloud | Agent-Hub | code_generation | 1.0 | -1.0 |
| gemma4:31b-cloud | Agent-Hub | coding | 1.0 | -1.0 |
| gemma4:31b-cloud | Agent-Hub | code_generation | 0.994 | -0.994 |
| gemma4:31b-cloud | ytdl_site | bug_fix | 0.938 | -0.938 |
| gemma4:31b-cloud | ytdl_site | refactor | 0.932 | -0.932 |
| gemma4:31b-cloud | Agent-Hub | code_generation | 0.928 | -0.928 |
| gemma4:31b-cloud | Agent-Hub | code_generation | 0.928 | -0.928 |
| gemma4:31b-cloud | Agent-Hub | bug_fix | 0.904 | -0.904 |

## False Negatives

| model | repository | category | predicted | residual |
| --- | --- | --- | --- | --- |
| nemotron-3-super:cloud | face | code_generation | 0.097 | 0.903 |
| nemotron-3-super:cloud | Agent-Hub | code_generation | 0.1 | 0.9 |
| nemotron-3-super:cloud | face | documentation | 0.113 | 0.887 |
| nemotron-3-super:cloud | face | documentation | 0.116 | 0.884 |
| nemotron-3-super:cloud | face | architecture | 0.171 | 0.829 |
| nemotron-3-super:cloud | Agent-Hub | code_generation | 0.171 | 0.829 |
| nemotron-3-super:cloud | ytdl_site | architecture | 0.179 | 0.821 |
| nemotron-3-super:cloud | Agent-Hub | code_generation | 0.184 | 0.816 |

## Clusters

| axis | cluster | rows | mean residual | residual sd |
| --- | --- | --- | --- | --- |
| source | balanced_live_matrix.jsonl | 9 | 0.084272 | 0.444123 |
| category | architecture | 60 | -0.062605 | 0.256766 |
| category | coding | 30 | -0.059911 | 0.311806 |
| source | real_model_validation_results.jsonl | 30 | -0.059911 | 0.311806 |
| dataset | deconfounded_phase1 | 50 | -0.057933 | 0.202229 |
| category | bug_fix | 368 | 0.053568 | 0.389719 |
| category | code_generation | 169 | -0.053371 | 0.247798 |
| dataset | prospective | 67 | -0.036556 | 0.421121 |
| model | qwen3.5:cloud | 16 | -0.034361 | 0.055717 |
| dataset | unmatched_evidence_access | 40 | -0.033281 | 0.350166 |
| repository | face | 176 | 0.029032 | 0.341208 |
| category | testing | 102 | -0.02669 | 0.316036 |
| category | refactor | 84 | 0.021127 | 0.363068 |
| repository | ytdl_site | 176 | -0.021074 | 0.324062 |
| model | kimi-k2.6:cloud | 6 | -0.018724 | 0.018724 |
| model | glm-5.1:cloud | 6 | -0.018724 | 0.018724 |
| dataset | historical | 761 | 0.015216 | 0.343466 |
| model | gemma4:31b-cloud | 413 | 0.01288 | 0.20444 |

## Evidence

Residuals cluster most by task/source/category cells, not by an obvious new independent mechanism. E9 and referenced-file count explain residuals, but both are post-output traces.

## Counter-Evidence

The `coding` and `code_generation` negative residuals, plus false-negative Nemotron successes, are stable enough to justify continued missing-variable surveillance.

## Uncertainty

Residual labels mix historical, deconfounded, prospective, and unmatched evidence-access rows. Residual structure may be partly collection-protocol structure.

## Falsification Attempt

Candidate additions were tested after K+rho+A. Compatibility v2 adds 0.003652 R2; Route Friction adds about 0.000788. No clean pre-run fourth primitive survives this pass.
