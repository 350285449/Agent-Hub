# Interaction Falsification

Scope: cloud-only rows `918`; prior prospective reconstructed rows `67`.

Adversarial rule: do not tune for higher performance. A variant survives only if it improves prospective R2 by more than `0.01` and Brier gain by more than `0.003` over the existing clean model.

## Alternate Definitions, Thresholds, Scaling, And Normalization

| variant | holdout R2 | prospective R2 | delta R2 | delta Brier gain | verdict |
| --- | --- | --- | --- | --- | --- |
| raw product | 0.428453 | 0.022837 | 0.007024 | 0.001276 | eliminated |
| centered product | 0.428453 | 0.025525 | 0.009712 | 0.001765 | eliminated |
| difference | 0.434716 | 0.024182 | 0.008369 | 0.001521 | eliminated |
| ratio | 0.0 | 0.019073 | 0.00326 | 0.000592 | eliminated |
| threshold raw | 0.485686 | 0.064732 | 0.048919 | 0.008892 | survives weakly |
| threshold +0.05 | 0.436762 | 0.025405 | 0.009592 | 0.001743 | eliminated |
| threshold +0.10 | 0.434852 | 0.024268 | 0.008455 | 0.001536 | eliminated |
| median gate | 0.440398 | 0.017932 | 0.002119 | 0.000385 | eliminated |
| scaled threshold | 0.429301 | 0.041864 | 0.026051 | 0.004735 | survives weakly |

## Falsification Verdict

The literal `rho x distribution_shift_risk` claim is eliminated. The prior winner depends on a particular threshold-style definition, and even that effect is not robust across alternate thresholds and normalizations. This is a weak candidate signal, not a stable interaction law.
