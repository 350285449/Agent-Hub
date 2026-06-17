# Preventable Failure Estimates

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Counterfactual Estimates

| counterfactual | candidate failed rows | current success rate for mode | success rate for full grounded chain | low prevented | central prevented | high prevented | central share of all failures |
| --- | --- | --- | --- | --- | --- | --- | --- |
| interpretation corrected | 209 | 0.402857 | 0.896296 | 73.1 | 103.1 | 187.3 | 0.267867 |
| action linkage corrected | 204 | 0.423729 | 0.896296 | 71.4 | 96.4 | 182.8 | 0.250399 |
| interpretation or action linkage corrected | 216 | 0.402857 | 0.896296 | 75.6 | 106.6 | 193.6 | 0.276839 |

## Overlap Accounting

| bucket | rows | share of failures |
| --- | --- | --- |
| failed rows | 385 | 1.0 |
| misinterpreted | 209 | 0.542857 |
| disconnected | 204 | 0.52987 |
| misinterpreted or disconnected | 216 | 0.561039 |
| not in either dominant pathway | 169 | 0.438961 |

## Estimate

Central estimate: correcting interpretation or evidence-to-action linkage would remove about 106.6 of 385 failures, or 0.276839 of all failures. This is an estimate, not a causal proof: overlapping mechanisms are counted once in the union row.
