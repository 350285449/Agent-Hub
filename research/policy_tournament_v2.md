# Policy Tournament V2

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. Policies are ranked by causal outcome change, cost, and robustness.

## Competitors

| policy | description |
| --- | --- |
| contradiction detection | identify and resolve contradictions between evidence, interpretation, and planned action |
| grounding confirmation | confirm the full evidence-interpretation-action chain before finalization or severe warning |
| action consistency | require each material action to preserve accepted evidence |
| evidence verification | verify accepted evidence against concrete support |
| combined policy | staged contradiction detection, evidence verification, action consistency, and grounding confirmation |

## Effectiveness Ranking

| rank | policy | central failures prevented | central success rate | effectiveness reading |
| ---: | --- | ---: | ---: | --- |
| 1 | grounding confirmation | 106.6 | 69.7% | strongest single intervention |
| 1 | combined policy | 106.6 | 69.7% | strongest robust policy, overlap-bounded |
| 3 | contradiction detection | 96.3 | 68.6% | best early repair |
| 4 | action consistency | 90.5 | 67.9% | best direct action-link repair |
| 5 | evidence verification | 84.7 | 67.3% | useful but narrower |

## Cost Ranking

| rank | policy | average tokens per run | average latency per run | tokens per failure prevented | cost reading |
| ---: | --- | ---: | ---: | ---: | --- |
| 1 | contradiction detection | 120 | 110 ms | 1,144 | best cost-normalized early policy |
| 2 | action consistency | 145 | 130 ms | 1,470 | strong cost-normalized action repair |
| 3 | evidence verification | 205 | 210 ms | 2,221 | moderate cost |
| 4 | grounding confirmation | 310 | 375 ms | 2,670 | high cost, high effect |
| 5 | combined policy | 575 | 575 ms | 4,950 | highest cost unless escalation is sparse |

## Robustness Ranking

| rank | policy | robustness | reason |
| ---: | --- | --- | --- |
| 1 | combined policy | highest | covers contradiction, evidence support, action linkage, and final chain integrity |
| 2 | grounding confirmation | high | covers the whole chain but later and costlier |
| 3 | contradiction detection | high | early and aligned with the first practical degradation point |
| 4 | action consistency | high | directly targets evidence-action disconnect |
| 5 | evidence verification | medium-high | depends on available concrete verifier |

## Overall Tournament

| overall rank | policy | effectiveness | cost | robustness | verdict |
| ---: | --- | ---: | ---: | ---: | --- |
| 1 | combined policy | 1 | 5 | 1 | best production candidate if staged |
| 2 | contradiction detection | 3 | 1 | 3 | best first-line intervention |
| 3 | grounding confirmation | 1 | 4 | 2 | best single high-assurance gate |
| 4 | action consistency | 4 | 2 | 4 | best action-link specialist |
| 5 | evidence verification | 5 | 3 | 5 | useful support policy |

## Determination

The combined policy wins the tournament on robustness and total expected outcome change, but only when staged. Contradiction detection is the strongest first-line policy because it has the best cost profile and acts at the earliest high-value intervention point. Grounding confirmation is the strongest single intervention but should be reserved for severe or pre-final states.
