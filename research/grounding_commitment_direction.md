# Grounding Commitment Direction

Scope: cloud models only. This file tests collapse direction inside the compressed mechanism:

1. Grounding causes commitment.
2. Commitment causes grounding.
3. Both are symptoms of a hidden execution process.

## Evidence For Grounding Upstream Of Commitment

Grounding is the earlier enabling event in the current corpus.

- The strongest predictive event is first grounding event, contribution 0.144538.
- First decisive evidence ranks second, contribution 0.037139.
- First branch collapse has negative independent event contribution after controls, -0.003139.
- The minimal selected group is grounding: first grounding event, grounding latency, grounded-action ratio, and evidence-to-action latency.
- Runs that enter grounded/converging trajectories show much higher success than runs that remain exploring or stuck.

The strongest operational reading is that grounding creates the conditions under which a useful commitment can occur. Commitment without grounding is often just lock-in.

## Evidence For Commitment Upstream Of Grounding

The evidence for commitment causing grounding is weak.

Commitment does add diagnostic value because outcome uncertainty collapses around the 50% prefix. However, that collapse appears after evidence and grounding signals have had time to enter the run. The commitment curve does not show strong pre-grounding causal precedence; it shows that once the branch has collapsed, the outcome is easier to predict.

Branch commitment is therefore better treated as a downstream bottleneck than as the generator of grounding.

## Hidden Process Alternative

The hidden-process alternative remains partially plausible. A latent execution-quality process could produce both high grounding and better branch commitment. Evidence:

- State clusters separate success rates.
- `stuck`, `exploring`, `grounded`, `converging`, and `recovered` states have predictive structure.
- Family-specific dynamics remain material.
- Intervention causality has not been delivered and validated.

But the hidden-process account is not needed as a separate theory in the current program. The observable compressed mechanism already captures the main signal: evidence conversion into grounded action before branch commitment.

## Direction Test

| direction | support | weakness | determination |
| --- | --- | --- | --- |
| Grounding -> Commitment | strongest | causality not delivered-intervention proven | best current direction |
| Commitment -> Grounding | weak | commitment appears late and can be wrong | not favored |
| Hidden process -> both | moderate | adds little beyond measured execution states | plausible residual, not primary |

## Determination

Grounding is upstream of useful commitment in the current evidence. Branch commitment is the point where the run becomes hard to redirect, but grounding is the mechanism that makes commitment correct rather than merely irreversible.

The most precise causal language is:

`Evidence recognition and interpretation enable grounded action; grounded action raises the probability that branch commitment lands on a successful path; branch commitment then becomes the final bottleneck for the observed outcome.`
