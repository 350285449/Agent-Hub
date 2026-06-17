# Live Trial Execution Log

Machine-readable full log: `research/live_trial_execution_log.jsonl`.

## Trigger And Delivery Summary

| trigger | all rows | treatment rows | delivered rows |
| --- | --- | --- | --- |
| contradictory_grounding | 0 | 0 | 0 |
| evidence_action_mismatch | 5 | 3 | 2 |
| grounding_collapse | 0 | 0 | 0 |
| grounded_action_ratio_below_threshold | 0 | 0 | 0 |

## Run Log

| task | arm | model | trigger event | intervention type | token cost | latency cost ms | final outcome |
| --- | --- | --- | --- | --- | --- | --- | --- |
| e24650a7bf271509 | treatment | nemotron-3-super | evidence_action_mismatch | action consistency check | 823 | 5065 | success |
| ff241980c5321f46 | control | nemotron-3-super | none | none | 0 | 0 | failure |
| cd7042df4ebc8489 | treatment | nemotron-3-super | none | none | 0 | 0 | success |
| 99b555e9983dad04 | treatment | nemotron-3-super | none | none | 0 | 0 | execution_error |
| c230103018ed6a82 | treatment | nemotron-3-super | none | none | 0 | 0 | success |
| a0fe78fb09b46f9e | control | nemotron-3-super | none | none | 0 | 0 | failure |
| c128f9ac1abe87ce | control | nemotron-3-super | none | none | 0 | 0 | success |
| 6bddefbefcc5d2fa | treatment | nemotron-3-super | none | none | 0 | 0 | success |
| 78bb4ec3fb3d0cff | control | nemotron-3-super | none | none | 0 | 0 | success |
| 0781f61f02fa5151 | treatment | nemotron-3-super | none | none | 0 | 0 | success |
| dc950690ece4fcaa | control | nemotron-3-super | none | none | 0 | 0 | success |
| c9b474842f76a134 | treatment | nemotron-3-super | none | none | 0 | 0 | success |
| 1b66bd6fdded4585 | treatment | nemotron-3-super | none | none | 0 | 0 | success |
| 9034b0c69463e099 | treatment | nemotron-3-super | none | none | 0 | 0 | failure |
| 1d1ade464ea04c30 | control | nemotron-3-super | none | none | 0 | 0 | success |
| e549257d0cf1ebb2 | treatment | nemotron-3-super | none | none | 0 | 0 | success |
| 60911a52bde1670a | control | nemotron-3-super | none | none | 0 | 0 | success |
| 60ba4333396e7a83 | treatment | nemotron-3-super | none | none | 0 | 0 | success |
| cbd29dbd8a67e3d3 | treatment | nemotron-3-super | evidence_action_mismatch | action consistency check | 754 | 12414 | failure |
| f54c7aa4ce2364cb | treatment | nemotron-3-super | none | none | 0 | 0 | success |
