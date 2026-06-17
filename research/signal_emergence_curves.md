# Signal Emergence Curves

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Each row is a strict prefix: later execution events are not visible to earlier windows.

| window | feature count | holdout R2 | holdout R2 delta | holdout Brier gain | prospective R2 | prospective Brier gain |
| --- | --- | --- | --- | --- | --- | --- |
| 0% | 7 | 0.406068 | n/a | 0.090805 | 0.0 | -0.005365 |
| 10% | 9 | 0.342405 | -0.063663 | 0.076569 | 0.0 | -0.01362 |
| 25% | 13 | 0.423852 | 0.081447 | 0.094782 | 0.005219 | 0.000949 |
| 50% | 17 | 0.632214 | 0.208362 | 0.141375 | 0.109202 | 0.01985 |
| 75% | 21 | 0.613042 | -0.019172 | 0.137088 | 0.039278 | 0.00714 |
| pre-answer | 20 | 0.624795 | 0.011753 | 0.139716 | 0.099063 | 0.018007 |

## Reading

The 0% row captures pre-execution priors. The first material execution lift appears once retrieval and decisive evidence enter the prefix; most of the surviving Dynamic Assimilation signal is already visible by the grounded/converging middle of the run, with later verification adding less than grounding.
