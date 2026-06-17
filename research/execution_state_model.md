# Execution State Model

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

States are exclusive at each sampled execution window, but a run can visit multiple states over time.

## State Definitions

| state | definition |
| --- | --- |
| exploring | Evidence has been retrieved or surfaced, but no stable grounded action path exists yet. |
| grounded | Decisive evidence has appeared and is tied to an actionable context before final convergence. |
| converging | The run has collapsed to a single solution path: evidence is understood and linked to action. |
| stuck | Evidence retrieval and action linkage are both weak; the trajectory lacks a usable path. |
| recovered | The run had contradiction/confusion and then repaired the path into action or verification. |

## Ranked States

| rank | state | visited rows | final rows | success if visited | success if final | success if absent | holdout R2 gain | prospective R2 gain | contribution |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | stuck | 280 | 184 | 0.496429 | 0.271739 | 0.617555 | 0.08747 | -0.006192 | 0.043853 |
| 2 | converging | 257 | 257 | 0.898833 | 0.898833 | 0.456884 | 0.012624 | 0.002178 | 0.007745 |
| 3 | grounded | 249 | 16 | 0.88755 | 0.875 | 0.466368 | 0.006325 | 0.00465 | 0.005191 |
| 4 | exploring | 512 | 448 | 0.548828 | 0.502232 | 0.62069 | 0.004197 | 0.0048 | 0.004076 |
| 5 | recovered | 13 | 13 | 1.0 | 1.0 | 0.574586 | 0.002056 | 0.000397 | 0.001277 |

## Frequent State Sequences

| 10>25>50>75 sequence | rows | success rate |
| --- | --- | --- |
| exploring>exploring>exploring>exploring | 368 | 0.413043 |
| grounded>grounded>converging>converging | 193 | 0.906736 |
| stuck>stuck>stuck>stuck | 184 | 0.271739 |
| stuck>stuck>exploring>exploring | 71 | 0.971831 |
| exploring>grounded>converging>converging | 38 | 0.789474 |
| exploring>exploring>converging>converging | 21 | 1.0 |
| grounded>grounded>grounded>grounded | 16 | 0.875 |
| stuck>stuck>recovered>recovered | 11 | 1.0 |
| exploring>stuck>exploring>exploring | 9 | 0.444444 |
| exploring>stuck>converging>converging | 5 | 1.0 |
| grounded>grounded>recovered>recovered | 2 | 1.0 |
