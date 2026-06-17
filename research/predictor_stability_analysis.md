# Predictor Stability Analysis

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Predictor Stability

| predictor | rows | global corr | AUC | split corr sd | eligible split cells | timing |
| --- | --- | --- | --- | --- | --- | --- |
| K | 918 | 0.692927 | 0.723925 | 0.665459 | 17 | pre-run if frozen from past rows |
| rho | 918 | 0.685836 | 0.860247 | 0.244863 | 17 | pre-run if frozen from past rows |
| A1_exists | 918 | 0.083662 | 0.517098 | 0.051605 | 17 | pre-run |
| A2_retrieved | 918 | 0.101447 | 0.554238 | 0.082291 | 17 | during-run pre-generation |
| A3_surfaced | 918 | 0.024211 | 0.536968 | 0.074544 | 17 | during-run pre-generation |
| A4_understood | 918 | 0.436311 | 0.725416 | 0.203089 | 17 | post-run |
| A5_linked_to_action | 918 | 0.634746 | 0.893358 | 0.168393 | 17 | post-run |
| A | 918 | 0.22231 | 0.659465 | 0.132317 | 17 | mixed |
| Actionability | 918 | 0.17363 | 0.600375 | 0.095678 | 17 | mixed/post-run in current aligned data |
| E9 | 918 | 0.634746 | 0.893358 | 0.168393 | 17 | post-run |
| context_budget | 918 | 0.093394 | 0.555369 | 0.099498 | 17 | pre-run |

## Findings

- `K` is the most useful clean prior, but it is an outcome-derived memory of past performance.
- `rho` is unstable under prospective transfer because its model/category cells are coarse and family-sensitive.
- `A1` is clean but too weak alone.
- `A2/A3` are cleaner than `A4/A5`, but only available after retrieval/context assembly.
- `A4/A5`, `E9`, and generated-reference fields are strong because they observe the run itself.

## Stability Verdict

The clean predictors are not stable enough to carry the retrospective ceiling into a narrow future benchmark. Predictor instability and model-family imbalance are sufficient to explain the prospective collapse without inventing a fourth primitive.
