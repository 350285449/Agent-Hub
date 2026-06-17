# Intervention Rankings

Scope: cloud models only. Rankings use measured warning coverage, the existing counterfactual estimates, and cost/robustness judgments tied to the observed grounding metrics.

## Ranked Interventions

| rank | intervention | main trigger | failure reduction | success increase over all rows | robustness | cost | rationale |
| ---: | --- | --- | ---: | ---: | --- | --- | --- |
| 1 | grounding confirmation | fragile or collapsing integrity before final action | 25%-28% | 10.5-11.6 pp | high | high | covers both interpretation failure and action disconnect |
| 2 | contradiction detection and resolution | contradictory grounding at 25%-50% | 23%-27% | 9.6-11.2 pp | high | moderate | earliest high-coverage warning and strongest prevention point |
| 3 | action consistency check | grounding collapse or low grounded-action ratio at 50%-75% | 22%-25% | 9.2-10.5 pp | high | moderate | directly repairs the accepted-evidence-to-action failure |
| 4 | evidence verification | accepted evidence without verifier, source, or test link | 20%-24% | 8.4-10.1 pp | medium-high | moderate-high | reduces false acceptance and improves retention, but costs more |
| 5 | evidence recheck | low evidence reuse or weak interpretation | 18%-22% | 7.5-9.2 pp | medium | low-moderate | cheap early repair, but weaker than explicit contradiction resolution |

## Failure Reduction Basis

| measured pathway | central prevented rows | share of all failures |
| --- | ---: | ---: |
| interpretation corrected | 103.1 | 26.8% |
| action linkage corrected | 96.4 | 25.0% |
| interpretation or action linkage corrected | 106.6 | 27.7% |

## Cost Reading

Evidence recheck is cheapest because it uses evidence already surfaced. Contradiction detection is slightly more expensive because it needs explicit comparison between evidence and interpretation. Action consistency checks require a second pass over the planned action. Grounding confirmation is highest cost because it combines the full chain check.

## Final Ranked List With Preventable Percentages

| rank | intervention | estimated preventable failures |
| ---: | --- | ---: |
| 1 | grounding confirmation | 25%-28% |
| 2 | contradiction detection and resolution | 23%-27% |
| 3 | action consistency check | 22%-25% |
| 4 | evidence verification | 20%-24% |
| 5 | evidence recheck | 18%-22% |

## Determination

The best single intervention is grounding confirmation. The best early intervention is contradiction detection and resolution. The best low-cost intervention is evidence recheck.
