# Grounding Repair Model

Scope: cloud models only. The model below is an intervention model over measured grounding-integrity variables, not a new theory.

## Repair Candidates

| repair | trigger | repair action | primary metric improved | cost | effectiveness estimate |
| --- | --- | --- | --- | --- | ---: |
| evidence recheck | contradiction, low evidence reuse, weak interpretation | revisit the evidence already surfaced and restate the decision-relevant fact | evidence interpretation accuracy | low to moderate | prevents 18%-22% of failures |
| evidence verification | evidence accepted but unsupported by source, test, or file reference | verify accepted evidence against source context or a concrete checker | evidence reuse, evidence retention | moderate to high | prevents 20%-24% of failures |
| contradiction detection | surfaced evidence conflicts with interpretation | explicitly detect and resolve the conflict before action | interpretation accuracy | moderate | prevents 23%-27% of failures |
| action consistency check | accepted evidence exists but action linkage is weak | require chosen action to cite or preserve the accepted evidence link | grounded-action ratio | moderate | prevents 22%-25% of failures |
| grounding confirmation | before final action, confirm evidence, interpretation, and action form one chain | combine evidence recheck, contradiction resolution, and action consistency | grounded-action ratio and evidence-action consistency | high | prevents 25%-28% of failures |

## Counterfactual Simulation

Observed dominant failure modes:

| failure | failed rows | current success rate for mode | target success rate for full grounded chain | central prevented | prevented share of all failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| interpretation corrected | 209 | 40.3% | 89.6% | 103.1 | 26.8% |
| action linkage corrected | 204 | 42.4% | 89.6% | 96.4 | 25.0% |
| interpretation or action linkage corrected | 216 | 40.3% | 89.6% | 106.6 | 27.7% |

## Repair Stages

| stage | correct interpretation | corrected action linkage | grounding repair | contradiction resolution | expected outcome change |
| --- | --- | --- | --- | --- | --- |
| contradictory grounding | high impact | indirect | high | direct | largest early reduction in misinterpreted-evidence failures |
| grounding collapse | medium | high | high | medium | converts accepted evidence into connected action |
| action disconnect | low to medium | direct | high | low | restores grounded-action ratio before final output |
| fragile integrity score | medium | medium | medium | medium | useful as a gating signal, less precise as a standalone repair |

## Operational Repair Loop

1. Detect contradiction or fragile integrity once evidence appears.
2. Recheck the evidence already in context.
3. Verify the evidence against a concrete source, file, test, or trace.
4. Resolve conflicts before choosing an action.
5. Confirm that the selected action preserves the verified evidence link.

## Determination

The best repair model is a compact grounding confirmation gate. It is more expensive than a single contradiction check, but it covers both dominant failure pathways: misinterpretation and action disconnect.
