# Grounding Failure Chains

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Ranked Chains

| rank | failure chain | failed rows | share of failures | mean grounding score | mean decisive evidence timing | mean evidence-to-action latency |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | evidence found -> misinterpreted -> wrong/no action -> failure | 209 | 0.542857 | 0.451171 | 0.182536 | 0.807895 |
| 2 | mixed/other misgrounding -> failure | 145 | 0.376623 | 0.157065 | 0.834483 | 0.072414 |
| 3 | evidence not found -> no grounding -> failure | 24 | 0.062338 | 0.025298 | 1.0 | 0.0 |
| 4 | evidence found -> understood -> not connected to action -> failure | 7 | 0.018182 | 0.582835 | 0.1 | 0.828571 |

## Chain Reading

The most common chain is `evidence found -> misinterpreted -> wrong/no action -> failure`. The highest-impact chains are the ones that pass evidence availability but fail before action: they are preventable in principle because the evidence was already inside the run.
