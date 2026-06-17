# Evidence Misinterpretation

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Available Evidence vs Interpretation

| category | rows | failed rows | failure rate | mean A2 retrieved | mean A3 surfaced | mean A4 understood | success rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bug_fix | 166 | 69 | 0.415663 | 0.692771 | 0.637034 | 0.094377 | 0.584337 |
| code_generation | 53 | 50 | 0.943396 | 0.836478 | 0.597328 | 0.025157 | 0.056604 |
| refactor | 42 | 24 | 0.571429 | 0.730159 | 0.451296 | 0.0 | 0.428571 |
| testing | 26 | 22 | 0.846154 | 1.0 | 0.550801 | 0.012821 | 0.153846 |
| analysis | 31 | 17 | 0.548387 | 0.903226 | 0.635393 | 0.010753 | 0.451613 |
| architecture | 19 | 16 | 0.842105 | 0.964912 | 0.690072 | 0.052632 | 0.157895 |
| documentation | 13 | 11 | 0.846154 | 1.0 | 0.220564 | 0.0 | 0.153846 |

## Difference From Successful Runs

| group | rows | mean A2 retrieved | mean A3 surfaced | mean A4 understood | mean A5 linked | mean grounded-action ratio |
| --- | --- | --- | --- | --- | --- | --- |
| successful runs with retrieved evidence | 320 | 0.899479 | 0.362814 | 0.680208 | 0.465365 | 0.537873 |
| failed misinterpretation rows | 209 | 0.803828 | 0.554238 | 0.022329 | 0.023923 | 0.035067 |

## Representative Failed Rows

| row | model | repo | category | A2 | A3 | A4 | A5 | trajectory |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 70bbebf54d77 | nemotron-3-super:cloud | face | refactor | 0.5 | 0.05 | 0.0 | 0.0 | discovered>recognized |
| e6c99b0caa32 | nemotron-3-super:cloud | face | refactor | 0.5 | 0.043 | 0.0 | 0.0 | discovered>recognized |
| efe5490301a0 | nemotron-3-super:cloud | face | refactor | 0.5 | 0.05 | 0.0 | 0.0 | discovered>recognized |
| 1f245c4d51e7 | nemotron-3-super:cloud | face | refactor | 0.5 | 0.043 | 0.0 | 0.0 | discovered>recognized |
| 0b4d61b2a6fc | nemotron-3-super:cloud | face | refactor | 0.5 | 0.05 | 0.0 | 0.0 | discovered>recognized |
| 6209bf230256 | nemotron-3-super:cloud | face | refactor | 0.5 | 0.05 | 0.0 | 0.0 | discovered>recognized |
| a54054f87628 | nemotron-3-super:cloud | face | refactor | 0.5 | 0.05 | 0.0 | 0.0 | discovered>recognized |
| 694df97e77a5 | nemotron-3-super:cloud | face | refactor | 0.5 | 0.043 | 0.0 | 0.0 | discovered>recognized |
| 49f3a29f7130 | nemotron-3-super:cloud | face | refactor | 0.5 | 0.043 | 0.0 | 0.083 | discovered>recognized |
| 30814e23aaf3 | nemotron-3-super:cloud | face | refactor | 0.5 | 0.043 | 0.0 | 0.083 | discovered>recognized |
| 0b1a1f506c48 | nemotron-3-super:cloud | face | refactor | 0.5 | 0.043 | 0.0 | 0.083 | discovered>recognized |
| a1278906650c | nemotron-3-super:cloud | face | refactor | 0.5 | 0.043 | 0.0 | 0.083 | discovered>recognized |

## Determination

The available evidence was usually retrieved or surfaced: the failure signature is not zero access, but low `A4_understood` after nontrivial `A2/A3`. Successful rows with retrieved evidence convert that same evidence into higher understanding, higher action linkage, and a much higher grounded-action ratio.
