# GCT Causal Trial v2

## Arms

Control: standard execution.

Treatment: before any commitment event, the runner requires evidence verification, explicit evidence justification, alternative branch evaluation, and a commitment delay gate.

## Timing Enforcement

The treatment is valid only if `intervention_delivered_at < commitment_opened_at`. If a model commits before the intervention gate, the row is marked timing-invalid for the causal estimand.

## Outcomes

| measure | definition |
| --- | --- |
| GAR change | treatment mean GAR minus control mean GAR |
| commitment quality change | treatment mean commitment quality minus control mean |
| outcome change | treatment success rate minus control success rate |
| pathological uncertainty collapse | pre-interpretation collapse frequency difference |

## Randomization

Arm assignment is frozen at row creation, stratified by task family and cloud model family. Analysis uses intention-to-treat as primary and timing-valid treatment-on-treated as secondary.

## Current Status

No causal effect is claimed. The prior post-draft intervention is invalid for this v2 causal estimand.
