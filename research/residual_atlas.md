# Residual Atlas

Residual = Actual - Predicted from K+rho+A.

## Largest False Positives

| model | repository | category | predicted | residual |
| --- | --- | --- | --- | --- |
| gemma4:31b-cloud | Agent-Hub | code_generation | 1.0 | -1.0 |
| gemma4:31b-cloud | Agent-Hub | coding | 1.0 | -1.0 |
| gemma4:31b-cloud | Agent-Hub | code_generation | 0.986 | -0.986 |
| gpt-5.5 | face | testing | 0.981 | -0.981 |
| gemma4:31b-cloud | ytdl_site | bug_fix | 0.967 | -0.967 |
| gemma4:31b-cloud | Agent-Hub | bug_fix | 0.913 | -0.913 |
| gemma4:31b-cloud | Agent-Hub | bug_fix | 0.913 | -0.913 |
| gemma4:31b-cloud | Agent-Hub | bug_fix | 0.912 | -0.912 |
| gemma4:31b-cloud | Agent-Hub | bug_fix | 0.911 | -0.911 |
| gemma4:31b-cloud | Agent-Hub | bug_fix | 0.91 | -0.91 |

## Largest False Negatives

| model | repository | category | predicted | residual |
| --- | --- | --- | --- | --- |
| nemotron-3-super:cloud | face | code_generation | 0.093 | 0.907 |
| nemotron-3-super:cloud | Agent-Hub | code_generation | 0.098 | 0.902 |
| nemotron-3-super:cloud | face | documentation | 0.151 | 0.849 |
| nemotron-3-super:cloud | face | architecture | 0.152 | 0.848 |
| nemotron-3-super:cloud | face | documentation | 0.154 | 0.846 |
| nemotron-3-super:cloud | ytdl_site | architecture | 0.164 | 0.836 |
| nemotron-3-super:cloud | face | testing | 0.196 | 0.804 |
| nemotron-3-super:cloud | face | testing | 0.201 | 0.799 |
| nemotron-3-super:cloud | face | testing | 0.201 | 0.799 |
| nemotron-3-super:cloud | ytdl_site | testing | 0.201 | 0.799 |

## Residual Clusters

| axis | cluster | rows | mean residual | residual sd |
| --- | --- | --- | --- | --- |
| dataset | unmatched_evidence_access | 52 | -0.094808 | 0.404629 |
| dataset | deconfounded_phase2 | 50 | 0.078989 | 0.234931 |
| category | code_generation | 183 | -0.061295 | 0.272526 |
| category | bug_fix | 384 | 0.050097 | 0.394048 |
| category | coding | 36 | -0.047685 | 0.353183 |
| dataset | deconfounded_phase1 | 50 | -0.038818 | 0.201391 |
| category | architecture | 92 | -0.027806 | 0.290276 |
| model | qwen3.5:cloud | 16 | -0.027712 | 0.055279 |
| model | kimi-k2.6:cloud | 16 | -0.027712 | 0.055279 |
| category | refactor | 106 | 0.026305 | 0.343655 |
| provider | ollama-cloud | 30 | 0.024642 | 0.290817 |
| model | gemma4:31b-cloud | 423 | 0.017219 | 0.202603 |
| category | analysis | 88 | 0.017008 | 0.397592 |
| category | testing | 135 | -0.01477 | 0.30296 |
| dataset | historical | 862 | 0.010054 | 0.35159 |
| repository | face | 244 | 0.006904 | 0.369949 |
| model | gpt-5.5 | 143 | 0.006391 | 0.385128 |
| provider | codex-cli | 143 | 0.006391 | 0.385128 |
| repository | Agent-Hub | 630 | 0.006363 | 0.351188 |
| provider | openai-compatible | 918 | 0.004804 | 0.345538 |

Interpretation: residual clusters concentrate around model families, repository/task cells, and dataset provenance. That pattern is more consistent with under-measured K/rho/A and benchmark/evaluator effects than with one clean new primitive.
