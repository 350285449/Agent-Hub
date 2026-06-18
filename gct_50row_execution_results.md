# GCT 50-Row Execution Results

Command: `python scripts/frozen_panel_executor.py --execute --limit 50`.
Execution mode: `execute`.
Rows requested: `50`.
Rows completed: `48`.
Rows quarantined: `2`.
Malformed outputs ingested: `0`.

All completed rows were live cloud-routed through the configured Ollama cloud endpoint; no local, synthetic, or replay rows were accepted.

| row | provider | model | GAR | pre-commit GAR | post-commit GAR | commitment timing | strength | quality | uncertainty collapse | intervention delivery | intervention timing | outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gct-v2-agentic-025 | ollama-gemma-cloud | gemma4:31b | 0.55 | 0.641667 | 0.0 | seq 12 (2 after first branch) | 0.95 | valid_lock_in | 0.1 | delivered | pre_commit_before_commit | success |
| gct-v2-coding-023 | ollama-gemma-cloud | gemma4:31b | 0.525 | 0.63 | 0.0 | seq 11 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-agentic-006 | ollama-gemma-cloud | gemma4:31b | 0.566667 | 0.68 | 0.0 | seq 9 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-coding-027 | ollama-gemma-cloud | gemma4:31b | 0.575 | 0.69 | 0.0 | seq 10 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-research-026 | ollama-gemma-cloud | gemma4:31b | 0.585714 | 0.683333 | 0.0 | seq 11 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-agentic-043 | ollama-gemma-cloud | gemma4:31b | 0.6 | 0.7 | 0.0 | seq 14 (2 after first branch) | 0.95 | valid_lock_in | 0.4 | delivered | pre_commit_before_commit | success |
| gct-v2-reasoning-015 | ollama-gemma-cloud | gemma4:31b | 0.61875 | 0.707143 | 0.0 | seq 14 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-coding-045 | ollama-gemma-cloud | gemma4:31b | 0.635714 | 0.741667 | 0.0 | seq 10 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-research-044 | ollama-gemma-cloud | gemma4:31b | 0.564286 | 0.658333 | 0.0 | seq 11 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-reasoning-044 | ollama-gemma-cloud | gemma4:31b | 0.691667 | 0.83 | 0.0 | seq 12 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-coding-036 | ollama-gemma-cloud | gemma4:31b | 0.671429 | 0.783333 | 0.0 | seq 11 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-agentic-030 | ollama-gemma-cloud | gemma4:31b | 0.416667 | 0.5 | 0.0 | seq 9 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-reasoning-029 | ollama-gemma-cloud | gemma4:31b | 0.575 | 0.657143 | 0.0 | seq 14 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-reasoning-025 | ollama-gemma-cloud | gemma4:31b | 0.558333 | 0.67 | 0.0 | seq 10 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | failure |
| gct-v2-research-045 | ollama-gemma-cloud | gemma4:31b | 0.5 | 0.6 | 0.0 | seq 9 (2 after first branch) | 0.9 | valid_lock_in | -0.3 | not_assigned_control | not_applicable_control | success |
| gct-v2-coding-018 | ollama-gemma-cloud | gemma4:31b | 0.641667 | 0.77 | 0.0 | seq 11 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-reasoning-041 | ollama-gemma-cloud | gemma4:31b | 0.757143 | 0.716667 | 1.0 | seq 13 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-agentic-014 | ollama-gemma-cloud | gemma4:31b | 0.616667 | 0.74 | 0.0 | seq 10 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-agentic-019 | ollama-gemma-cloud | gemma4:31b | 0.63125 | 0.721429 | 0.0 | seq 14 (2 after first branch) | 0.95 | valid_lock_in | 0.3 | delivered | pre_commit_before_commit | success |
| gct-v2-coding-039 | ollama-gemma-cloud | gemma4:31b | 0.633333 | 0.76 | 0.0 | seq 10 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-reasoning-033 | ollama-gemma-cloud | gemma4:31b | 0.608333 | 0.73 | 0.0 | seq 12 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-agentic-040 | ollama-gemma-cloud | gemma4:31b | 0.75 | 0.7 | 1.0 | seq 12 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-reasoning-047 | ollama-gemma-cloud | gemma4:31b | 0.4875 | 0.557143 | 0.0 | seq 14 (2 after first branch) | 1.0 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-research-036 | ollama-gemma-cloud | gemma4:31b | 0.607143 | 0.708333 | 0.0 | seq 11 (2 after first branch) | 0.85 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-research-021 | ollama-gemma-cloud | gemma4:31b | 0.566667 | 0.68 | 0.0 | seq 9 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-research-050 | ollama-gemma-cloud | gemma4:31b | 0.571429 | 0.666667 | 0.0 | seq 11 (1 after first branch) | 0.9 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-reasoning-004 | ollama-gemma-cloud | gemma4:31b | 0.561111 | 0.673333 | 0.0 | seq 11 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-research-047 | ollama-gemma-cloud | gemma4:31b | 0.541667 | 0.65 | 0.0 | seq 12 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-research-037 | ollama-gemma-cloud | gemma4:31b | 0.575 | 0.69 | 0.0 | seq 12 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-research-042 | ollama-gemma-cloud | gemma4:31b | 0.6 | 0.7 | 0.0 | seq 11 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-research-024 | ollama-gemma-cloud | gemma4:31b | 0.469444 | 0.563333 | 0.0 | seq 10 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-coding-004 | ollama-gemma-cloud | gemma4:31b | 0.633333 | 0.76 | 0.0 | seq 10 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | failure |
| gct-v2-reasoning-022 | ollama-gemma-cloud | gemma4:31b | 0.583333 | 0.7 | 0.0 | seq 12 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-reasoning-040 | ollama-gemma-cloud | gemma4:31b | 0.35 | 0.42 | 0.0 | seq 11 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-reasoning-012 | ollama-gemma-cloud | gemma4:31b | 0.716667 | 0.86 | 0.0 | seq 12 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-reasoning-032 | ollama-gemma-cloud | gemma4:31b | 0.65 | 0.78 | 0.0 | seq 10 (2 after first branch) | 1.0 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | failure |
| gct-v2-coding-012 | ollama-gemma-cloud | gemma4:31b | 0.4625 | 0.528571 | 0.0 | seq 13 (2 after first branch) | 0.8 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-reasoning-046 | ollama-gemma-cloud | gemma4:31b | 0.666667 | 0.8 | 0.0 | seq 10 (2 after first branch) | 1.0 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-agentic-020 | ollama-gemma-cloud | gemma4:31b | 0.483333 | 0.58 | 0.0 | seq 11 (2 after first branch) | 0.8 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-research-020 | ollama-gemma-cloud | gemma4:31b | 0.585714 | 0.683333 | 0.0 | seq 11 (2 after first branch) | 0.88 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-agentic-036 | ollama-gemma-cloud | gemma4:31b | 0.575 | 0.69 | 0.0 | seq 10 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | success |
| gct-v2-agentic-039 | ollama-gemma-cloud | gemma4:31b | 0.483333 | 0.552381 | 0.0 | seq 12 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-research-002 | ollama-gemma-cloud | gemma4:31b | 0.571429 | 0.666667 | 0.0 | seq 11 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-research-048 | ollama-gemma-cloud | gemma4:31b | 0.607143 | 0.708333 | 0.0 | seq 11 (2 after first branch) | 0.85 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-agentic-041 | ollama-gemma-cloud | gemma4:31b | 0.597619 | 0.697222 | 0.0 | seq 14 (2 after first branch) | 0.98 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-research-004 | ollama-gemma-cloud | gemma4:31b | 0.571429 | 0.666667 | 0.0 | seq 11 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
| gct-v2-agentic-046 | ollama-gemma-cloud | gemma4:31b | 0.425 | 0.51 | 0.0 | seq 9 (2 after first branch) | 0.9 | valid_lock_in | 0.0 | not_assigned_control | not_applicable_control | failure |
| gct-v2-coding-032 | ollama-gemma-cloud | gemma4:31b | 0.557143 | 0.65 | 0.0 | seq 14 (2 after first branch) | 0.95 | valid_lock_in | 0.0 | delivered | pre_commit_before_commit | success |
