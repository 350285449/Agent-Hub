# Execution Conservation Test

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

This test asks whether any existing execution quantity is approximately conserved during successful runs. Conservation here means a narrow successful-run band that also separates from failures. It is not a physics claim.

## Conservation Candidates

| quantity | expected direction | success mean | success sd | success coefficient of variation | failure mean | success-failure gap |
| --- | --- | --- | --- | --- | --- | --- |
| grounded-action accumulation | higher | 0.496622 | 0.284956 | 0.573788 | 0.098376 | 0.398247 |
| grounding latency | lower | 0.360225 | 0.376395 | 1.044888 | 0.477532 | -0.117307 |
| evidence-action latency | lower | 0.384615 | 0.315274 | 0.819711 | 0.480909 | -0.096294 |
| state-transition count | bounded | 0.56035 | 0.230008 | 0.410472 | 0.687446 | -0.127096 |
| branch-collapse incidence | higher | 0.138837 | 0.345776 | 2.490523 | 0.023377 | 0.11546 |
| verification-success incidence | higher | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

## Determination

No quantity is conserved in the strict sense. Grounded-action accumulation is the closest operational analogue: successful runs tend to maintain a much higher grounded-action ratio than failures. But its successful-run variance is too large to call it conserved. Evidence accumulation and uncertainty reduction behave like directional processes, not constants.
