# Grounding States

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## State Rates

| state | rows | transition/end-state rate | success rate | failure rate | success lift vs base |
| --- | --- | --- | --- | --- | --- |
| ungrounded | 275 | 0.299564 | 0.487273 | 0.512727 | -0.093337 |
| weakly grounded | 348 | 0.379085 | 0.393678 | 0.606322 | -0.186932 |
| grounded | 69 | 0.075163 | 0.869565 | 0.130435 | 0.288955 |
| strongly grounded | 226 | 0.246187 | 0.893805 | 0.106195 | 0.313195 |

## Transition Rates

| transition | count | transition share | success rate | direction |
| --- | --- | --- | --- | --- |
| ungrounded -> ungrounded | 665 | 0.241467 | 0.378947 | flat |
| weakly grounded -> grounded | 660 | 0.239651 | 0.640909 | up |
| grounded -> weakly grounded | 370 | 0.13435 | 0.448649 | down |
| weakly grounded -> weakly grounded | 332 | 0.120552 | 0.364458 | flat |
| grounded -> grounded | 308 | 0.111837 | 0.896104 | flat |
| grounded -> strongly grounded | 226 | 0.082062 | 0.893805 | up |
| ungrounded -> grounded | 85 | 0.030864 | 0.941176 | up |
| grounded -> ungrounded | 80 | 0.029049 | 0.9375 | down |
| weakly grounded -> ungrounded | 14 | 0.005084 | 0.142857 | down |
| ungrounded -> weakly grounded | 14 | 0.005084 | 0.142857 | up |

## State Definitions

| state | operational definition |
| --- | --- |
| ungrounded | little recognized evidence and low grounding score |
| weakly grounded | evidence recognized, but acceptance/action linkage is incomplete |
| grounded | decisive evidence or high score with usable action linkage |
| strongly grounded | grounded execution plus high score |

## Determination

Grounding states are useful because grounded and strongly grounded runs separate sharply from ungrounded or weakly grounded runs. Weak grounding is a real failure-prone intermediate state, not merely noise: it captures runs that have evidence but have not converted it into execution.
