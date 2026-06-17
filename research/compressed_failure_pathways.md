# Compressed Failure Pathways

Scope: cloud models only. Failure pathways are ranked inside the compressed mechanism without adding new primitives.

## Ranked Pathways

| rank | pathway | empirical signature | observed support | recoverability |
| ---: | --- | --- | --- | --- |
| 1 | evidence-action disconnect | accepted/understood evidence is not preserved in action | accepted/connected success 0.898182 versus accepted/disconnected success 0.423729 | high |
| 2 | evidence misinterpreted | evidence retrieved/surfaced, but `A4_understood` remains low | 209 failed rows; 54.3% of failures in recovery model | high |
| 3 | false commitment | commitment lands on stuck/wrong branch after weak grounding | branch collapse diagnostic-only after controls; stuck states predict failure | medium |
| 4 | premature commitment | branch collapses before adequate grounding/action linkage | commitment around 50%, agentic rows drift later | medium |
| 5 | irreversible wrong branch | late lock-in after wrong action path | recovery lower after final output and after late commitment | low-medium |
| 6 | evidence unavailable | relevant evidence not found or no usable grounding exists | 24 failed rows, 6.2% of failures; no usable grounding 21 rows, 5.5% | low |

## Failure Pathway Details

### Evidence Unavailable

This is not the dominant failure class. The recovery model finds evidence not found/no grounding in 24 failed rows, or 6.2% of failures. These failures are low recoverability under the compressed mechanism because repair would require better retrieval or expanded evidence access, which is outside the current no-new-primitive program.

### Evidence Misinterpreted

This is a dominant failure pathway. Failed misinterpretation rows usually have nontrivial `A2_retrieved` and `A3_surfaced`, but very low `A4_understood` and `A5_linked`.

Key contrast:

- Successful runs with retrieved evidence: mean grounded-action ratio 0.537873.
- Failed misinterpretation rows: mean grounded-action ratio 0.035067.

The issue is usually not zero evidence. It is failed conversion from evidence to understanding and action.

### Evidence-Action Disconnect

This is the strongest practical failure pathway. The run accepts or recognizes evidence, then chooses an action that does not preserve the evidence link.

Key contrast:

- Accepted/understood and connected: 275 rows, success 0.898182, mean grounded-action ratio 0.719359.
- Accepted/understood but disconnected: 354 rows, success 0.423729, mean grounded-action ratio 0.092332.

This pathway is highly recoverable because the warning appears before final output: accepted evidence exists, but action consistency fails.

### Premature Commitment

Premature commitment occurs when branch collapse happens before enough grounded evidence is converted into action. It is most visible in families requiring longer tool sequencing or recovery. The commitment point is near 50% in aggregate, but not stable enough across families to be called universal.

### False Commitment

False commitment occurs when the branch becomes confident/convergent but the grounded-action link is wrong. This is more important than raw commitment timing: commitment quality matters more than commitment existence.

### Irreversible Wrong Branch

Irreversibility is a late-stage failure. Once the run has committed to a wrong branch and emitted final output, repair probability falls. This is why the highest recovery windows are 25%-50% for misinterpretation and 50%-75% for action disconnect.

## Ranking Determination

The compressed mechanism ranks failures by preventable signal:

1. Evidence-action disconnect.
2. Evidence misinterpretation.
3. False commitment.
4. Premature commitment.
5. Irreversible wrong branch.
6. Evidence unavailable.

The dominant Agent-Hub failure is not lack of evidence. It is failure to convert recognized evidence into grounded action before commitment.
