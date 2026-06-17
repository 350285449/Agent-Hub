# Benchmark Generalization

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Leave-One-Benchmark-Out

| held-out benchmark | rows | baseline R2 | combined R2 | delta | combined AUC | combined Brier gain |
| --- | --- | --- | --- | --- | --- | --- |
| live_matrix.jsonl:prospective:Agent-Hub | 28 | 0.052627 | 0.004892 | -0.047735 | 0.643939 | 0.000824 |
| live_matrix.jsonl:historical:ytdl_site | 158 | 0.60803 | 0.645909 | 0.037879 | 0.976942 | 0.154854 |
| live_matrix.jsonl:historical:face | 134 | 0.481305 | 0.534277 | 0.052972 | 0.943071 | 0.119168 |
| live_matrix.jsonl:deconfounded_phase1:Agent-Hub | 30 | 0.866542 | 0.947359 | 0.080817 | 1.0 | 0.210524 |
| live_matrix.jsonl:historical:Agent-Hub | 469 | 0.428888 | 0.5222 | 0.093312 | 0.926066 | 0.121571 |
| live_matrix.jsonl:prospective:ytdl_site | 18 | 0.0 | 0.101527 | 0.101527 | 0.958333 | 0.022562 |
| live_matrix.jsonl:deconfounded_phase1:face | 20 | 0.644289 | 0.7741 | 0.129811 | 1.0 | 0.185784 |
| real_model_validation_results.jsonl:unmatched_evidence_acces | 30 | 0.339602 | 0.640967 | 0.301365 | 0.954545 | 0.125345 |
| live_matrix.jsonl:prospective:face | 21 | 0.0 | 0.450038 | 0.450038 | 1.0 | 0.069394 |

## Dataset Holdout Tests

| held-out dataset | rows | baseline R2 | combined R2 | delta | combined AUC | combined Brier gain |
| --- | --- | --- | --- | --- | --- | --- |
| historical | 761 | 0.46087 | 0.049835 | -0.411035 | 0.821449 | 0.011607 |
| deconfounded_phase1 | 50 | 0.786279 | 0.879692 | 0.093413 | 1.0 | 0.216756 |
| prospective | 67 | 0.003318 | 0.187919 | 0.184601 | 0.8125 | 0.034159 |
| unmatched_evidence_access | 40 | 0.438956 | 0.667344 | 0.228388 | 0.957333 | 0.156409 |

## Determination

Benchmark shifts are the harshest test in this run. Positive deltas under leave-one-benchmark-out support generalization; negative deltas mark benchmark dependence and should cap deployment claims.
