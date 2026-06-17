# Grounding Control Framework

Scope: cloud models only. This framework maps measured warning signs to interventions and expected improvement.

## Control Map

| warning sign | detection window | intervention | expected improvement |
| --- | ---: | --- | ---: |
| contradictory grounding | 25%-50% | contradiction detection and resolution | prevents 23%-27% of failures |
| low evidence reuse | 25%-50% | evidence recheck | prevents 18%-22% of failures |
| weak interpretation accuracy | 25%-50% | evidence recheck plus verification | prevents 20%-24% of failures |
| grounding collapse | 50%-75% | grounding confirmation | prevents 25%-28% of failures |
| low grounded-action ratio | 50%-75% | action consistency check | prevents 22%-25% of failures |
| accepted evidence without action linkage | 50%-75% | corrected action linkage | prevents about 25% of failures |
| fragile integrity band | 25%-75% | full grounding confirmation gate | prevents 25%-28% of failures |

## Control Policy

| stage | condition | action |
| --- | --- | --- |
| evidence recognition | evidence appears but interpretation conflicts | pause action selection and resolve contradiction |
| evidence acceptance | accepted evidence lacks verification | verify source, file, test, or trace before using it |
| action planning | action does not cite or preserve accepted evidence | revise action until evidence-action consistency is restored |
| pre-final answer | integrity is fragile or collapsed | run grounding confirmation before final output |

## Active Maintenance

Grounding Integrity can be actively maintained if the system measures it online. The maintainable variables are grounded-action ratio, evidence reuse, evidence-action consistency, evidence retention, and grounding latency. The strongest control target is grounded-action ratio because it had the strongest incremental holdout gain among individual metrics.

## Intervention Versus Prediction

Intervention outperforms prediction as an operational strategy. Pre-run prediction remains weak prospectively, while live grounding warnings hit 58.7% of all failures and the central intervention estimate prevents 27.7%. The useful strategy is not to predict every failure before execution; it is to detect deterioration once evidence appears and repair the grounding chain before final action.

## Direct Answers

Can Grounding Integrity be actively maintained: yes, through online contradiction checks, verification, action consistency checks, and grounding confirmation.

Does intervention outperform prediction: yes operationally. Prediction identifies risk, but intervention changes the trajectory while the run is still recoverable.
