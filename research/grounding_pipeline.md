# Grounding Pipeline

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Stages are measured from existing evidence-access and execution-dynamics fields only. No primitive search, interaction search, local model row, Codex row, Ollama row, self-hosted row, or edge row is admitted.

## Stage Transition Probabilities

| stage | rows reaching stage | marginal probability | transition probability | success if reached | success if not reached |
| --- | --- | --- | --- | --- | --- |
| evidence discovered | 879 | 0.957516 | 0.957516 | 0.589306 | 0.384615 |
| evidence recognized | 638 | 0.694989 | 0.725825 | 0.617555 | 0.496429 |
| evidence accepted | 629 | 0.685185 | 0.978056 | 0.631161 | 0.470588 |
| evidence connected to action | 355 | 0.38671 | 0.437202 | 0.907042 | 0.374778 |
| grounded execution | 247 | 0.269063 | 0.695775 | 0.88664 | 0.467958 |

## Reading

Grounding is not equivalent to evidence availability. The major discriminant is the conversion from accepted evidence into action and then grounded execution. Runs can discover and recognize evidence while still failing to ground if the evidence does not become an actionable path.
