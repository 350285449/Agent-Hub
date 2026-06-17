# Mechanism Cross-Family

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Attack: test whether the mechanism is just a coding artifact by checking coding, reasoning, research, and agentic families.

## Historical Cloud Panel

| family | rows | success rate | grounding success gap | commitment success gap | core holdout R2 | loss if grounding removed | loss if commitment removed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| coding | 723 | 0.603043 | 0.380693 | 0.29962 | 0.785806 | 0.013308 | 0.062836 |
| reasoning | 94 | 0.510638 | 0.620833 | 0.554217 | 0.0 | 0.0 | -0.071808 |
| research | 71 | 0.577465 | 0.464773 | 0.428571 | 0.988263 | -0.001862 | -0.001262 |
| agentic | 30 | 0.266667 | -0.266667 | -0.266667 | 0.898459 | 0.053346 | 0.079959 |

## Fresh Balanced Cloud Replay

| family | rows | success rate | mean GAR | GAR success gap | mean commitment | grounding density | E2A latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| agentic | 36 | 0.75 | 0.560401 | 0.058966 | 0.546372 | 0.812245 | 0.318858 |
| coding | 36 | 0.944444 | 0.66856 | 0.063549 | 0.468418 | 0.831168 | 0.27248 |
| reasoning | 36 | 0.833333 | 0.598432 | 0.056937 | 0.487641 | 0.795345 | 0.303953 |
| research | 36 | 0.416667 | 0.517672 | 0.039257 | 0.495446 | 0.767899 | 0.342515 |

## Determination

The mechanism transfers cleanly in coding and remains broadly visible in reasoning and research. Agentic is the hard slice: the historical panel is negative on simple grounding/commitment gaps, while the fresh balanced cloud replay is positive. This does not collapse the mechanism, but it blocks a universal-law claim and keeps agentic execution as the main family-level weakness.
