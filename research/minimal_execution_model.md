# Minimal Execution Model

Scope: cloud models only. This file finds the smallest variable set that explains most surviving signal after prior theory collapse.

## Candidate Variables

The requested compressed variables are:

- evidence availability
- evidence recognition
- evidence interpretation
- grounded-action ratio
- branch commitment timing
- branch commitment quality
- outcome

## Smallest Useful Model

The smallest useful model is:

`evidence recognition + grounded-action ratio + branch commitment quality`

In implementation terms:

1. Did the run surface relevant evidence?
2. Did the run convert that evidence into action?
3. Did the run commit to a grounded/converging branch instead of a stuck/wrong branch?

## Why This Is Minimal

The prior greedy subset selected only the grounding group:

| selected group | features | holdout R2 | prospective R2 | share of full dynamic gain |
| --- | --- | ---: | ---: | ---: |
| grounding | first_grounding_event, grounding_latency, grounded_action_ratio, evidence_to_action_latency | 0.612539 | 0.101662 | 1.100047 |

The full dynamic event model was not better on the same summary:

| model | holdout R2 | prospective R2 |
| --- | ---: | ---: |
| full dynamic event model | 0.604526 | 0.078260 |
| minimal grounding group | 0.612539 | 0.101662 |

This means tool, verification, recovery, branch-collapse, and explicit state features can remain useful diagnostics, but they are not required to recover most surviving signal.

## Minimal Variable Set

| variable | keep? | reason |
| --- | --- | --- |
| evidence availability | optional boundary | important for unrecoverable cases, but not the dominant failure signal |
| evidence recognition | keep | necessary to know whether the run had usable evidence |
| evidence interpretation | compress into grounding | important, but measured most effectively through grounded-action conversion |
| grounded-action ratio | keep | strongest single grounding integrity metric |
| branch commitment timing | optional diagnostic | useful around 50%, but less stable across families |
| branch commitment quality | keep | distinguishes useful convergence from wrong lock-in |
| outcome | target | required dependent variable |

## Minimal Model Formula

The smallest useful runtime model can be expressed as:

`P(success) = f(evidence_recognition, grounded_action_ratio, commitment_quality)`

With a practical rule:

`success risk rises sharply when evidence is recognized but grounded_action_ratio is low before branch commitment.`

## What It Leaves Out

This minimal model intentionally leaves out:

- new primitive searches
- interaction-law searches
- large theory families
- full trajectory state graphs unless needed for diagnostics
- delivered causal intervention claims

## Determination

The smallest useful model is a three-variable runtime model:

`recognized evidence -> grounded-action ratio -> commitment quality`

For operational monitoring, add commitment timing as a warning clock. For research sufficiency, the three-variable model captures most surviving signal.
