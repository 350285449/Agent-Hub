# Grounding Failure Assessment

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Answers

1. Why does grounding fail? Evidence usually fails after access: it is misinterpreted, partially understood, disconnected from action, overridden by high prior confidence, or lost during execution.
2. Most common failure chain: `evidence found -> misinterpreted -> wrong/no action -> failure`.
3. Most damaging failure mechanism: `evidence misinterpreted` by impact score.
4. Preventable failure percentage: central estimate 0.276839, with low/high counts 75.6/193.6 failed rows.
5. Is misgrounding dominant? Yes for this cloud-only aligned set: misinterpretation or action disconnect covers 0.561039 of failures, and grounding variables account for the large incremental diagnostic signal reported in the prior grounding assessment.

## Ranked By Frequency

| rank | mechanism | failed rows | share of failures | impact score |
| --- | --- | --- | --- | --- |
| 1 | evidence misinterpreted | 209 | 0.542857 | 37.150352 |
| 2 | evidence disconnected from action | 204 | 0.52987 | 32.003766 |
| 3 | evidence lost during execution | 139 | 0.361039 | 14.890399 |
| 4 | evidence not found | 24 | 0.062338 | 4.703871 |
| 5 | evidence partially understood | 14 | 0.036364 | 0.0 |
| 6 | evidence found but ignored | 12 | 0.031169 | 5.253035 |
| 7 | evidence overridden by prior belief | 10 | 0.025974 | 5.8061 |

## Ranked By Damage

| rank | mechanism | failed rows | share of failures | impact score |
| --- | --- | --- | --- | --- |
| 1 | evidence misinterpreted | 209 | 0.542857 | 37.150352 |
| 2 | evidence disconnected from action | 204 | 0.52987 | 32.003766 |
| 3 | evidence lost during execution | 139 | 0.361039 | 14.890399 |
| 7 | evidence overridden by prior belief | 10 | 0.025974 | 5.8061 |
| 6 | evidence found but ignored | 12 | 0.031169 | 5.253035 |
| 4 | evidence not found | 24 | 0.062338 | 4.703871 |
| 5 | evidence partially understood | 14 | 0.036364 | 0.0 |

## Contribution to Overall Failure

| mechanism | share of all failures | estimated contribution |
| --- | --- | --- |
| evidence misinterpreted | 0.542857 | dominant |
| evidence disconnected from action | 0.52987 | dominant |
| evidence lost during execution | 0.361039 | secondary |
| evidence not found | 0.062338 | secondary |
| evidence partially understood | 0.036364 | secondary |
| evidence found but ignored | 0.031169 | secondary |
| evidence overridden by prior belief | 0.025974 | minor |

## Final Determination

Misgrounding is the dominant measured cause of failure under the requested scope. The principal failure is not evidence absence. The principal failure is evidence failing to become grounded action, especially through misinterpretation and action disconnect.
