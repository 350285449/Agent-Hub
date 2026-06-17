# GCT Necessity v2

## Counterexample Classes

| class | definition | frequency field |
| --- | --- | --- |
| low grounding + success | GAR and interpretation below frozen low threshold, outcome succeeds | n_low_grounding_success |
| poor commitment + success | commitment timing/quality below threshold, outcome succeeds | n_poor_commitment_success |
| high grounding + failure | GAR above high threshold, outcome fails | n_high_grounding_failure |
| high commitment + failure | commitment quality above high threshold, outcome fails | n_high_commitment_failure |

## Thresholds

- Low grounding: GAR < 0.40 or evidence interpretation < 0.40.
- High grounding: GAR >= 0.75 and evidence interpretation >= 0.75.
- Poor commitment: commitment quality < 0.40 or commitment opens before first interpretation.
- High commitment: commitment quality >= 0.75 with non-pathological uncertainty collapse.

## Current Frequency

Frequency is not yet estimable because v2 execution is frozen but incomplete. A valid frequency table requires 200 completed cloud rows.
