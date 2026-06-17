# Intervention Economics

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. Cost metrics are included only because intervention evaluation requires token cost, latency cost, and intervention frequency.

## Baseline

| quantity | value |
| --- | ---: |
| runs | 918 |
| failures | 385 |
| successes | 533 |
| central recoverable failures | 106.6 |
| failures prevented per 1000 runs, central | 116.1 |

## Cost Assumptions

These are evaluation constants for comparing interventions, not new Grounding Integrity theory. They should be replaced by measured telemetry in the frozen trial.

| policy | average token delta per run | average latency delta per run | intervention frequency | basis |
| --- | ---: | ---: | ---: | --- |
| contradiction detection | 120 tokens | 110 ms | 45% | compact comparison after evidence appears |
| grounding confirmation | 310 tokens | 375 ms | 35% | full-chain pre-final or severe-warning gate |
| action consistency checks | 145 tokens | 130 ms | 50% | material action changes |
| evidence verification | 205 tokens | 210 ms | 40% | verification against source/file/test/tool output |
| combined policy | 575 tokens | 575 ms | 65% | staged policy with escalation |

## Failure Prevention Economics

| policy | central failures prevented per 918 runs | failures prevented per 1000 runs | tokens per 1000 runs | tokens per failure prevented | latency per run | cost reading |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| contradiction detection | 96.3 | 104.9 | 120,000 | 1,144 | 110 ms | best early return |
| grounding confirmation | 106.6 | 116.1 | 310,000 | 2,670 | 375 ms | strongest single effect, expensive |
| action consistency checks | 90.5 | 98.6 | 145,000 | 1,470 | 130 ms | strong cost-normalized repair |
| evidence verification | 84.7 | 92.3 | 205,000 | 2,221 | 210 ms | useful but costlier per recovery |
| combined policy | 106.6 | 116.1 | 575,000 | 4,950 | 575 ms | best robustness, weaker cost efficiency |

## Frequency Interpretation

| policy | expected interventions per 1000 runs | expected prevented failures per 1000 interventions |
| --- | ---: | ---: |
| contradiction detection | 450 | 233.1 |
| grounding confirmation | 350 | 331.7 |
| action consistency checks | 500 | 197.2 |
| evidence verification | 400 | 230.6 |
| combined policy | 650 | 178.5 |

Grounding confirmation has the best prevented-failure yield per triggered intervention because it is reserved for severe or pre-final states. Contradiction detection is the best low-latency first-line mechanism. The combined policy is not cost-efficient if every stage fires frequently; it is economically attractive only when staged escalation suppresses unnecessary full confirmations.

## Cost Sensitivity

| case | combined failures prevented per 1000 runs | tokens per failure prevented at 575 tokens/run |
| --- | ---: | ---: |
| conservative | 82.4 | 6,978 |
| central | 116.1 | 4,950 |
| optimistic practical | 210.9 | 2,727 |
| theoretical warning ceiling | 246.2 | 2,335 |

## Determination

The economic result is favorable for targeted intervention and unfavorable for blanket intervention. Contradiction detection and action consistency checks have the best cost-normalized profile. Grounding confirmation is worth running as a severe/pre-final gate, not as a universal every-step check. The combined policy should be production-tested only as a staged policy with measured trigger suppression.
