# Control Loop Design

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. This report converts the existing Grounding Integrity findings into an active control loop.

## Control Loop

Grounding Integrity Monitor -> Warning Detection -> Intervention Trigger -> Repair Action -> Continue Execution

| loop stage | input | decision | output |
| --- | --- | --- | --- |
| Grounding Integrity Monitor | evidence recognition, interpretation trace, planned action, verification trace | measure grounded-action ratio, evidence reuse, evidence-action consistency, contradiction state | current integrity state |
| Warning Detection | current integrity state | detect contradiction, collapse, low grounded-action ratio, or evidence-action mismatch | warning class and severity |
| Intervention Trigger | warning class and timing window | decide whether to pause execution for repair | intervention request |
| Repair Action | warning class plus current evidence | confirm grounding, resolve contradiction, check action consistency, verify or recheck evidence | repaired chain |
| Continue Execution | repaired chain | continue only when action preserves verified evidence | updated action trace |

## Trigger Points

| trigger | timing window | primary intervention | reason |
| --- | --- | --- | --- |
| contradictory grounding | 25%-50% | contradiction resolution | earliest high-coverage warning; covers 209 failed rows and 54.3% of failures |
| accepted evidence without verification | 25%-50% | evidence verification | prevents false acceptance before action selection hardens |
| low evidence reuse | 25%-50% | evidence recheck | cheap early correction when evidence appears once but is not reused |
| grounding collapse | 50%-75% | grounding confirmation | repairs evidence that was recognized but no longer controls action |
| grounded-action ratio decline | 50%-75% | action consistency check | strongest metric; failed rows with low metric cover 91.4% of failures |
| evidence-action mismatch | 50%-75% and pre-final | action consistency check plus grounding confirmation | direct repair for accepted evidence disconnected from action |

## Intervention Timing

| timing | intervention stance | expected effect |
| --- | --- | --- |
| 0%-25% | observe only unless evidence is already available | avoid premature intervention before grounding material exists |
| 25%-50% | trigger on contradiction, unsupported acceptance, and low reuse | best early window for preventing misinterpretation from becoming action |
| 50%-75% | trigger on collapse, action disconnect, and grounded-action decline | best window for repairing accepted evidence before final output |
| 75%-100% | final grounding confirmation gate | catches remaining fragile chains but has higher cost and lower timing margin |

## Intervention Frequency

| frequency rule | setting | rationale |
| --- | --- | --- |
| contradiction scan | every evidence update after first recognition | contradiction is the earliest warning sign |
| evidence verification | once per accepted decision-relevant evidence item, repeated only after conflict | controls cost |
| action consistency check | every material action change | the action can drift after evidence is accepted |
| grounding confirmation | at pre-final gate and after severe contradiction | highest coverage, highest cost |
| evidence recheck | at first low-reuse warning, then only if the same evidence remains decision-relevant | low-cost repair without excessive loops |

## Operating Policy

The loop should not try to predict failure before execution. It should maintain Grounding Integrity after evidence begins to appear. The primary control target is grounded-action ratio, with contradiction detection as the earliest trigger and grounding confirmation as the strongest repair.

## Determination

Grounding Integrity can be actively maintained if the system intervenes at the first contradiction, checks action consistency whenever plans change, and runs a grounding confirmation gate before final output. The best timing is early contradiction resolution at 25%-50% plus pre-final grounding confirmation.
