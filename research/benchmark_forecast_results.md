# Benchmark Forecast Results

Scope: Cloud-only aligned rows: 918 of 1091. Aligned exclusions: 173 rows by model {'gpt-5.5': 143, 'gemma4:31b-cloud': 10, 'nemotron-3-super:cloud': 10, 'kimi-k2.6:cloud': 10} and provider {'codex-cli': 143, 'ollama-cloud': 30}. Upstream strict audit additionally reported 11280 local deterministic rows, 2 timeout-only rows, and exclusion reasons {'duplicate task/model/context tuple': 5, 'local Ollama or otherwise disallowed model': 771, 'local deterministic proof row': 11280, 'provider failure/auth/subscription': 18, 'synthetic or derived benchmark row without allowed model provenance': 1380, 'timeout-only row with no usable output': 2, 'unsuccessful execution or unusable validation result': 4}.

These are frozen v2 forecasts for future execution. They are not outcomes.

## Forecast Set Summary

| set | forecast rows | mean p(success) | min p | max p | mean uncertainty p(1-p) |
| --- | --- | --- | --- | --- | --- |
| calibration_grid | 120 | 0.32 | 0.025 | 1.0 | 0.103 |
| hard_generalization | 135 | 0.314 | 0.025 | 1.0 | 0.094 |
| accessibility_stress | 90 | 0.311 | 0.067 | 1.0 | 0.099 |

## First Frozen Forecast Rows

| set | model | repository | category | context | p(success) | 95% CI | uncertainty sd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| calibration_grid | gemma4:31b-cloud | Agent-Hub | bug_fix | 0 | 0.889 | [0.864, 0.913] | 0.012 |
| calibration_grid | gemma4:31b-cloud | Agent-Hub | bug_fix | 25 | 0.889 | [0.864, 0.913] | 0.012 |
| calibration_grid | gemma4:31b-cloud | Agent-Hub | testing | 0 | 1.0 | [0.996, 1.0] | 0.001 |
| calibration_grid | gemma4:31b-cloud | Agent-Hub | testing | 25 | 1.0 | [0.996, 1.0] | 0.001 |
| calibration_grid | gemma4:31b-cloud | Agent-Hub | refactor | 0 | 0.972 | [0.952, 0.995] | 0.012 |
| calibration_grid | gemma4:31b-cloud | Agent-Hub | refactor | 25 | 0.972 | [0.952, 0.995] | 0.012 |
| calibration_grid | gemma4:31b-cloud | Agent-Hub | analysis | 0 | 1.0 | [0.995, 1.0] | 0.002 |
| calibration_grid | gemma4:31b-cloud | Agent-Hub | analysis | 25 | 1.0 | [0.995, 1.0] | 0.002 |
| calibration_grid | gemma4:31b-cloud | face | bug_fix | 0 | 0.877 | [0.848, 0.897] | 0.015 |
| calibration_grid | gemma4:31b-cloud | face | bug_fix | 25 | 0.877 | [0.848, 0.897] | 0.015 |
| calibration_grid | gemma4:31b-cloud | face | testing | 0 | 1.0 | [1.0, 1.0] | 0.0 |
| calibration_grid | gemma4:31b-cloud | face | testing | 25 | 1.0 | [1.0, 1.0] | 0.0 |
| calibration_grid | gemma4:31b-cloud | face | refactor | 0 | 0.978 | [0.959, 0.995] | 0.01 |
| calibration_grid | gemma4:31b-cloud | face | refactor | 25 | 0.978 | [0.959, 0.995] | 0.01 |
| calibration_grid | gemma4:31b-cloud | face | analysis | 0 | 1.0 | [0.999, 1.0] | 0.001 |
| calibration_grid | gemma4:31b-cloud | face | analysis | 25 | 1.0 | [0.999, 1.0] | 0.001 |
| calibration_grid | gemma4:31b-cloud | ytdl_site | bug_fix | 0 | 0.903 | [0.882, 0.927] | 0.011 |
| calibration_grid | gemma4:31b-cloud | ytdl_site | bug_fix | 25 | 0.903 | [0.882, 0.927] | 0.011 |
| calibration_grid | gemma4:31b-cloud | ytdl_site | testing | 0 | 1.0 | [1.0, 1.0] | 0.0 |
| calibration_grid | gemma4:31b-cloud | ytdl_site | testing | 25 | 1.0 | [1.0, 1.0] | 0.0 |
| calibration_grid | gemma4:31b-cloud | ytdl_site | refactor | 0 | 0.994 | [0.977, 1.0] | 0.007 |
| calibration_grid | gemma4:31b-cloud | ytdl_site | refactor | 25 | 0.994 | [0.977, 1.0] | 0.007 |
| calibration_grid | gemma4:31b-cloud | ytdl_site | analysis | 0 | 1.0 | [1.0, 1.0] | 0.0 |
| calibration_grid | gemma4:31b-cloud | ytdl_site | analysis | 25 | 1.0 | [1.0, 1.0] | 0.0 |
| calibration_grid | glm-5.1:cloud | Agent-Hub | bug_fix | 0 | 0.102 | [0.025, 0.175] | 0.044 |
| calibration_grid | glm-5.1:cloud | Agent-Hub | bug_fix | 25 | 0.102 | [0.025, 0.175] | 0.044 |
| calibration_grid | glm-5.1:cloud | Agent-Hub | testing | 0 | 0.077 | [0.0, 0.161] | 0.045 |
| calibration_grid | glm-5.1:cloud | Agent-Hub | testing | 25 | 0.077 | [0.0, 0.161] | 0.045 |
| calibration_grid | glm-5.1:cloud | Agent-Hub | refactor | 0 | 0.105 | [0.027, 0.177] | 0.044 |
| calibration_grid | glm-5.1:cloud | Agent-Hub | refactor | 25 | 0.105 | [0.027, 0.177] | 0.044 |
| calibration_grid | glm-5.1:cloud | Agent-Hub | analysis | 0 | 0.094 | [0.013, 0.171] | 0.045 |
| calibration_grid | glm-5.1:cloud | Agent-Hub | analysis | 25 | 0.094 | [0.013, 0.171] | 0.045 |
| calibration_grid | glm-5.1:cloud | face | bug_fix | 0 | 0.086 | [0.0, 0.167] | 0.045 |
| calibration_grid | glm-5.1:cloud | face | bug_fix | 25 | 0.086 | [0.0, 0.167] | 0.045 |
| calibration_grid | glm-5.1:cloud | face | testing | 0 | 0.104 | [0.026, 0.176] | 0.044 |
| calibration_grid | glm-5.1:cloud | face | testing | 25 | 0.104 | [0.026, 0.176] | 0.044 |

## Execution Rule

Run rows in the listed frozen sets without editing K, rho, A, probabilities, intervals, or benchmark membership. Append outcomes in a new result artifact after execution.
