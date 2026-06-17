# Commitment Point Validation

Aggregate commitment point: 0.499469. Standard deviation: 0.041656.

## Commitment By Task Family

| task family | rows | success rate | mean GAR | GAR success gap | mean commitment | grounding density | E2A latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| agentic | 36 | 0.75 | 0.560401 | 0.058966 | 0.546372 | 0.812245 | 0.318858 |
| coding | 36 | 0.944444 | 0.66856 | 0.063549 | 0.468418 | 0.831168 | 0.27248 |
| reasoning | 36 | 0.833333 | 0.598432 | 0.056937 | 0.487641 | 0.795345 | 0.303953 |
| research | 36 | 0.416667 | 0.517672 | 0.039257 | 0.495446 | 0.767899 | 0.342515 |

## Commitment By Model Family

| model family | rows | success rate | mean GAR | GAR success gap | mean commitment | grounding density | E2A latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| anthropic | 36 | 0.805556 | 0.596525 | 0.104138 | 0.503094 | 0.803033 | 0.305432 |
| google | 36 | 0.611111 | 0.578983 | 0.078931 | 0.50385 | 0.79869 | 0.31668 |
| nvidia | 36 | 0.638889 | 0.564544 | 0.076444 | 0.49962 | 0.788591 | 0.321413 |
| openai | 36 | 0.888889 | 0.605012 | 0.125705 | 0.491314 | 0.816342 | 0.29428 |

## Determination

Commitment remains near 50% in the aggregate, but it is not centered tightly enough across all slices. Agentic rows drift later because tool sequencing and recovery require more execution before branch collapse. Treat commitment-at-50% as a secondary weak candidate, not as a stable law.
