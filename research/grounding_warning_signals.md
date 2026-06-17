# Grounding Warning Signals

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Early Warning Tests

| warning | earliest visible window | rows | failed rows | failure rate | failure lift vs base | share of all failures | definition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| contradictory grounding | 25%-50% | 350 | 209 | 0.597143 | 0.177753 | 0.542857 | retrieved/surfaced evidence conflicts with the interpretation trace |
| grounding collapse | 50%-75% | 354 | 204 | 0.576271 | 0.156881 | 0.52987 | accepted evidence fails to remain connected to action |
| unstable grounding | 50%-75% | 596 | 302 | 0.506711 | 0.087321 | 0.784416 | state switches or evidence retention loss after partial grounding |
| delayed grounding | 25%-50% | 27 | 12 | 0.444444 | 0.025054 | 0.031169 | recognized evidence exists, but decisive grounding waits until the late window |

## Answer

Misgrounding is detectable early when recognized evidence fails to become coherent interpretation. Earliest warning sign in this run: `contradictory grounding`. The most reliable warning class is the one with both high failure lift and substantial failure coverage; in this corpus that is contradiction or collapse rather than mere delay.
