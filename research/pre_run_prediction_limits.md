# Pre-Run Prediction Limits

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Limit Estimate

| candidate ceiling | estimate | basis |
| --- | --- | --- |
| observed strict pre-run prospective R2 | 0.0 | only variables available before execution |
| observed post-retrieval prospective R2 | 0.0 | after retrieval/context assembly, before generation |
| observed all-catalog pre-run prospective R2 | 0.0 | optimistic proxy set; still pre-run/frozen-history only |
| optimistic theoretical pre-run ceiling | 0.03 | best clean prospective result plus small allowance for better calibration |

## Calibration

Best clean prospective Brier gain in this pass is `-0.005365`. That is too small for reliable route-level probability promises.

## Maximum Predictive Power Using Only Pre-Run Information

The defensible current estimate is low: clean observed prospective R2 is at most `0`. An optimistic ceiling using the current variable family is about `0.03` R2, not the retrospective 0.7-0.8 range. Higher values require either better frozen pre-run measurements or information that currently appears only during execution.
