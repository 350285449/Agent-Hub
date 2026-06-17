# Control Science Assessment

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. This final report answers whether Grounding Integrity can be maintained and which interventions should be implemented in Agent-Hub.

## Direct Answers

1. Can Grounding Integrity be maintained?

Yes. It can be actively maintained after evidence begins to appear by monitoring contradiction, grounded-action ratio, evidence-action consistency, evidence reuse, and grounding collapse. Maintenance is strongest when the system intervenes before final output rather than only predicting risk.

2. Which intervention is best?

Grounding confirmation is the strongest single intervention, with an estimated 25%-28% failure reduction. Contradiction resolution is the best early intervention. Action consistency is the best direct control over grounded-action ratio.

3. What is the optimal trigger?

The optimal trigger is one unresolved decision-relevant contradiction in the 25%-50% execution window. The second-best trigger is evidence-action mismatch after a planned action exists.

4. How many failures are recoverable?

The central recoverable estimate is 106.6 of 385 failures, or 27.7%. The detectable warning set is 226 of 385 failures, or 58.7%.

5. What is the recovery ceiling?

The practical central ceiling is 27.7% of failures. The optimistic practical ceiling is 50.3%. The theoretical warning ceiling is 58.7%, but it assumes perfect repair of all detectable warning-bearing failures.

6. What control policy wins?

The staged combined policy wins. It uses contradiction detection early, evidence recheck or verification when support is weak, action consistency when action changes, and grounding confirmation for severe warnings or the pre-final gate.

7. What should be implemented in Agent-Hub?

Agent-Hub should implement a real-time Grounding Integrity control system with an integrity monitor, contradiction detector, intervention engine, and recovery engine.

## Ranked Interventions

| rank | intervention | estimated failure reduction | best role |
| ---: | --- | ---: | --- |
| 1 | grounding confirmation | 25%-28% | strongest single intervention and final gate |
| 2 | contradiction resolution | 23%-27% | earliest high-impact repair |
| 3 | action consistency check | 22%-25% | strongest action-link repair |
| 4 | evidence verification | 20%-24% | repairs unsupported accepted evidence |
| 5 | evidence recheck | 18%-22% | cheapest useful repair |

## Ranked Trigger Mechanisms

| rank | trigger | timing | repair |
| ---: | --- | --- | --- |
| 1 | contradictory grounding | 25%-50% | contradiction resolution |
| 2 | evidence-action mismatch | 50%-75% and pre-final | action consistency check |
| 3 | grounded-action ratio decline | 50%-75% | action consistency check |
| 4 | grounding collapse | 50%-75% | grounding confirmation |
| 5 | low evidence reuse | 25%-50% | evidence recheck |
| 6 | unsupported accepted evidence | 25%-50% | evidence verification |

## Ranked Control Policies

| rank | policy | failure rate | success rate | cost | verdict |
| ---: | --- | ---: | ---: | --- | --- |
| 1 | combined staged policy | 30.3% central | 69.7% central | medium-high | winner |
| 2 | grounding confirmation | 30.2%-31.5% | 68.5%-69.8% | high | best single policy |
| 3 | contradiction detection | 30.6%-32.3% | 67.7%-69.4% | moderate | best early policy |
| 4 | action consistency | 31.5%-32.7% | 67.3%-68.5% | moderate | best action-link policy |
| 5 | no intervention | 41.9% | 58.1% | none | loses |

## Implementation Roadmap

| phase | work | priority |
| ---: | --- | --- |
| 1 | instrument evidence recognition, accepted evidence, verification, action proposals, and final actions | highest |
| 2 | compute live grounded-action ratio and evidence-action consistency | highest |
| 3 | trigger contradiction resolution on first decision-relevant contradiction | highest |
| 4 | add action consistency gate for every material action change | high |
| 5 | add evidence verification for unsupported accepted evidence | high |
| 6 | add grounding confirmation before final output and after severe warnings | high |
| 7 | log intervention type, timing, cost, repair result, and final outcome | high |
| 8 | run online policy tournament with shadow no-intervention baseline | medium |

## Final Determination

Grounding Integrity is controllable but not fully controllable. The program can change outcomes by repairing warning-bearing failures after evidence appears. The best implementation is a staged control loop that treats contradiction as the first trigger, grounded-action ratio as the primary metric, and grounding confirmation as the final repair gate.
